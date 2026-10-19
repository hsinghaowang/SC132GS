#include "StereoRtspServer.hpp"
#include "FrameTiming.hpp"
#include "StereoCapture.hpp"
#include "gs130wi/Capture.hpp"
#include "StereoComposeNV12.hpp"
#include "LinearVideoLuma.hpp"
#include "Main10Encoder.hpp"
#include "SensorSignalCalibration.hpp"
#include "StereoToneMapper.hpp"
#include "StereoDetailMapper.hpp"
#include "ImageProcessingPlan.hpp"
#include "GpuStereoRectifier.hpp"
#include "StereoOutputWorker.hpp"
#include <cstring>
#include "CaptureTrace.hpp"
#include "DepthPipeline.hpp"
#include "DepthRtspEndpoint.hpp"
#include "sc132gs-exposure-budget.hpp"
#include "sc132gs-ae.hpp"
#include "sc132gs-control-server.hpp"
#include "sc132gs-hdr-display.hpp"

#include <gst/app/gstappsrc.h>
#include <gst/app/gstappsink.h>
#include <gst/rtsp-server/rtsp-server.h>
#include <gst/video/video-event.h>

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <fstream>
#include <linux/tcp.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#include <iostream>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <unordered_map>

namespace stereo_rtsp {
namespace {

constexpr int kInputWidth = 1088;
constexpr int kInputEyeHeight = 1280;
volatile std::sig_atomic_t stop_signal = 0;

void signal_stop(int) { stop_signal = 1; }

// The deployed exact-pairing trigger belongs to the same capture session.
class KernelTrigger final {
    static constexpr const char* path = "/sys/bus/platform/devices/acb3000.camss/fsync_control";
    bool owned_{};
public:
    static bool available() {
        unsigned mode{};
        std::ifstream input("/sys/module/qcom_camss/parameters/fsync_mode");
        return bool(input >> mode) && mode == 2;
    }
    static void command(const char* value) {
        std::ofstream output(path);output << value << '\n';output.flush();
        if(!output)throw std::runtime_error("kernel trigger control failed");
    }
    KernelTrigger() {
        if(available()){command("stop");command("start");owned_=true;}
    }
    void stop(){if(owned_){command("stop");owned_=false;}}
    ~KernelTrigger(){if(owned_)try{command("stop");}catch(...){std::cerr<<"capture_trigger stop_failed=1\n";}}
    KernelTrigger(const KernelTrigger&)=delete;
    KernelTrigger& operator=(const KernelTrigger&)=delete;
};

} // namespace

struct StereoRtspServer::Impl {
    explicit Impl(Settings value) : settings(std::move(value)) {}

    Settings settings;
    detail::CaptureTrace processing_trace;
    detail::DepthRtspEndpoint depth_endpoint;
    GMainLoop* loop{};
    GstRTSPServer* server{};
    GstRTSPMediaFactory* factory{};
    std::string encoder_description;
    GstElement* encoder_pipeline{};
    GstAppSrc* encoder_source{};
    GstAppSink* encoder_sink{};
    guint attach_id{};
    guint timer_id{};
    std::mutex mutex;
    GstAppSrc* active_source{}; // owned reference; protected by mutex
    std::optional<Error> worker_error;
    std::int64_t first_timestamp_ns{-1};
    bool waiting_for_keyframe{true};
    bool media_playing{};
    bool rebase_media{true};
    GstClockTime last_media_pts{GST_CLOCK_TIME_NONE};
    std::chrono::steady_clock::time_point prepare_until{};
    std::atomic<std::uint64_t> encoded_pairs{0};
    std::atomic<std::uint64_t> delivered_pairs{0};
    std::uint64_t input_pairs{};
    std::uint64_t submitted_pairs{};
    std::uint64_t dropped_pairs{};
    std::int64_t last_timestamp_ns{};
    std::int64_t first_input_timestamp_ns{-1};
    bool have_timestamp{};
    std::atomic<bool> reader_done{false};
    std::atomic<bool> request_encoder_keyframe{false};
    std::chrono::steady_clock::time_point next_session_cleanup{};
    std::unique_ptr<AutoExposure> exposure_control;
    std::unique_ptr<ControlServer> control;
    std::jthread reader;
    int eye_width{}, eye_height{};
    bool stopping_capture{};
    std::optional<std::chrono::steady_clock::time_point> idle_since;
    struct ClientActivity {
        std::chrono::steady_clock::time_point last_activity;
        bool closed{};
        std::optional<std::uint32_t> received_segments;
    };
    std::unordered_map<GstRTSPClient*,ClientActivity> clients; // Owned refs, mutex protected.
    bool on_demand()const noexcept {
        // Other profiles still have an external, post-STREAMON timing setup.
        return settings.capture_mode==CaptureMode::external_trigger && settings.frame_rate==30;
    }

    ~Impl() {
        reader.request_stop();
        if(reader.joinable())reader.join();
        close_clients();
        // Stop the callback producer before releasing its RTSP destination.
        release_encoder();
        if (timer_id) g_source_remove(timer_id);
        if (attach_id) g_source_remove(attach_id);
        {
            std::lock_guard lock(mutex);
            if (active_source) gst_object_unref(active_source);
            active_source = nullptr;
        }
        if (factory) gst_object_unref(factory);
        if (server) gst_object_unref(server);
        if (loop) g_main_loop_unref(loop);
    }

    void close_clients() {
        // Stop accepting before taking client references. Do not close a client
        // inside server_client_filter: its callback runs with the server locked.
        if (attach_id) { g_source_remove(attach_id); attach_id = 0; }
        if (!server) return;
        GList* clients = gst_rtsp_server_client_filter(server, nullptr, nullptr);
        for (GList* item = clients; item; item = item->next) {
            auto* client = GST_RTSP_CLIENT(item->data);
            gst_rtsp_client_close(client);
            gst_object_unref(client);
        }
        g_list_free(clients);
        GstRTSPSessionPool* pool = gst_rtsp_server_get_session_pool(server);
        gst_rtsp_session_pool_filter(pool,
            [](GstRTSPSessionPool*, GstRTSPSession*, gpointer) {
                return GST_RTSP_FILTER_REMOVE;
            }, nullptr);
        gst_object_unref(pool);
        std::unordered_map<GstRTSPClient*,ClientActivity> retired;
        {std::lock_guard lock(mutex);retired.swap(this->clients);}
        for(const auto& entry:retired)gst_object_unref(entry.first);
    }

    static void release_object(gpointer object) {
        gst_object_unref(object);
    }

    static void client_connected(GstRTSPServer*, GstRTSPClient* client, gpointer data) {
        auto& self=*static_cast<Impl*>(data);
        const auto segments=incoming_segments(client);
        {std::lock_guard lock(self.mutex);self.clients.emplace(
            GST_RTSP_CLIENT(gst_object_ref(client)),ClientActivity{std::chrono::steady_clock::now(),false,segments});}
        std::cerr << "rtsp_client phase=connected\n";
        g_signal_connect(client, "new-session", G_CALLBACK(+[](
            GstRTSPClient*, GstRTSPSession* session, gpointer) {
                gst_rtsp_session_set_timeout(session, 30);
                std::cerr << "rtsp_session phase=created timeout_seconds=30\n";
            }), nullptr);
        g_signal_connect(client, "closed", G_CALLBACK(+[](GstRTSPClient* client, gpointer data) {
            auto& self=*static_cast<Impl*>(data);std::lock_guard lock(self.mutex);
            if(auto found=self.clients.find(client);found!=self.clients.end())found->second.closed=true;
            std::cerr << "rtsp_client phase=closed\n";
        }), data);
        for(const char* signal:{"options-request","describe-request","setup-request","play-request",
                                "pause-request","teardown-request","get-parameter-request","set-parameter-request"})
            g_signal_connect(client,signal,G_CALLBACK(+[](GstRTSPClient* client,GstRTSPContext*,gpointer data){
                auto& self=*static_cast<Impl*>(data);std::lock_guard lock(self.mutex);
                if(auto found=self.clients.find(client);found!=self.clients.end())
                    found->second.last_activity=std::chrono::steady_clock::now();
            }),data);
    }

    static std::optional<std::uint32_t> incoming_segments(GstRTSPClient* client) {
        const auto* connection=gst_rtsp_client_get_connection(client);
        if(!connection)return std::nullopt;
        auto* socket=gst_rtsp_connection_get_read_socket(connection);
        if(!socket)return std::nullopt;
        tcp_info info{};socklen_t size=sizeof(info);
        if(::getsockopt(g_socket_get_fd(socket),IPPROTO_TCP,TCP_INFO,&info,&size)!=0 ||
            size<offsetof(tcp_info,tcpi_segs_in)+sizeof(info.tcpi_segs_in))return std::nullopt;
        return info.tcpi_segs_in;
    }

    void expire_clients(std::chrono::steady_clock::time_point now) {
        std::vector<GstRTSPClient*> retired,observed;
        {
            std::lock_guard lock(mutex);
            for(auto i=clients.begin();i!=clients.end();) {
                if(i->second.closed){retired.push_back(i->first);i=clients.erase(i);}
                else {
                    observed.push_back(GST_RTSP_CLIENT(gst_object_ref(i->first)));
                    ++i;
                }
            }
        }
        for(auto* client:retired)gst_object_unref(client);
        for(auto* client:observed){
            // ACKs and interleaved RTCP count as activity too. A healthy RTP
            // reader is not required to issue additional RTSP requests here.
            const auto segments=incoming_segments(client);
            bool expired=false;
            {
                std::lock_guard lock(mutex);
                if(auto found=clients.find(client);found!=clients.end() && !found->second.closed){
                    auto& activity=found->second;
                    if(segments && segments!=activity.received_segments){
                        activity.received_segments=segments;activity.last_activity=now;
                    }
                    expired=now-activity.last_activity>=std::chrono::seconds(35);
                }
            }
            if(expired){
                std::cerr<<"rtsp_client phase=expired transport_silence_seconds=35\n";
                gst_rtsp_client_close(client);
            }
            gst_object_unref(client);
        }
    }

    static GstFlowReturn encoded_sample(GstAppSink* sink, gpointer data) {
        auto& self = *static_cast<Impl*>(data);
        GstSample* sample = gst_app_sink_pull_sample(sink);
        if (!sample) return GST_FLOW_EOS;
        GstBuffer* encoded = gst_sample_get_buffer(sample);
        ++self.encoded_pairs;
        GstAppSrc* destination{};
        GstClockTime base{};
        {
            std::lock_guard lock(self.mutex);
            if (self.active_source && (self.media_playing || std::chrono::steady_clock::now()<self.prepare_until) &&
                GST_CLOCK_TIME_IS_VALID(GST_BUFFER_PTS(encoded))) {
                if (!GST_BUFFER_FLAG_IS_SET(encoded, GST_BUFFER_FLAG_DELTA_UNIT))
                    self.waiting_for_keyframe = false;
                if (!self.waiting_for_keyframe) {
                    if (self.rebase_media || self.first_timestamp_ns < 0) {
                        const auto next=GST_CLOCK_TIME_IS_VALID(self.last_media_pts) ?
                            self.last_media_pts+GST_SECOND/self.settings.frame_rate : 0;
                        self.first_timestamp_ns=GST_BUFFER_PTS(encoded)-next;
                        self.rebase_media=false;
                    }
                    base = self.first_timestamp_ns;
                    self.last_media_pts=GST_BUFFER_PTS(encoded)-base;
                    destination = GST_APP_SRC(gst_object_ref(self.active_source));
                }
            }
        }
        if (destination) {
            // RTP queues must not retain a V4L2 capture-buffer/VPU fd lease.
            GstBuffer* copy = gst_buffer_copy_deep(encoded);
            if (!copy) { gst_object_unref(destination); gst_sample_unref(sample); return GST_FLOW_ERROR; }
            GST_BUFFER_PTS(copy) = GST_BUFFER_PTS(encoded) - base;
            GST_BUFFER_DTS(copy) = GST_CLOCK_TIME_NONE;
            // The bounded, leaky RTSP queue never stalls the hardware encoder.
            if (gst_app_src_push_buffer(destination, copy) == GST_FLOW_OK)
                ++self.delivered_pairs;
            gst_object_unref(destination);
        }
        gst_sample_unref(sample);
        return GST_FLOW_OK;
    }

    static void media_unprepared(GstRTSPMedia* media, gpointer data) {
        std::cerr << "rtsp_media phase=unprepared\n";
        auto& self = *static_cast<Impl*>(data);
        auto* source = GST_APP_SRC(
            g_object_get_data(G_OBJECT(media), "stereo_source_identity"));
        {
            std::lock_guard lock(self.mutex);
            if (source && source == self.active_source) {
                gst_object_unref(self.active_source);
                self.active_source = nullptr;
                self.first_timestamp_ns = -1;
            }
        }
    }

    static void media_configure(GstRTSPMediaFactory*, GstRTSPMedia* media,
                                gpointer data) {
        auto& self = *static_cast<Impl*>(data);
        GstElement* element = gst_rtsp_media_get_element(media);
        std::cerr << "rtsp_media phase=configured\n";
        GstElement* source = gst_bin_get_by_name_recurse_up(GST_BIN(element), "stereo_source");
        if (source) {
            std::lock_guard lock(self.mutex);
            if (self.active_source) gst_object_unref(self.active_source);
            self.active_source = GST_APP_SRC(source); // source has one owned ref
            self.first_timestamp_ns = -1;
            self.waiting_for_keyframe = true;
            self.media_playing=false;
            self.rebase_media=true;self.last_media_pts=GST_CLOCK_TIME_NONE;
            self.prepare_until=std::chrono::steady_clock::now()+std::chrono::seconds(10);
            g_object_set_data_full(G_OBJECT(media), "stereo_source_identity",
                                   gst_object_ref(source), release_object);
        }
        gst_object_unref(element);
        g_signal_connect(media, "unprepared", G_CALLBACK(media_unprepared), data);
        g_signal_connect(media,"new-state",G_CALLBACK(+[](GstRTSPMedia* media,gint state,gpointer data){
            auto& self=*static_cast<Impl*>(data);std::lock_guard lock(self.mutex);
            if(self.active_source!=g_object_get_data(G_OBJECT(media),"stereo_source_identity"))return;
            if(state==GST_STATE_PLAYING && !self.media_playing){
                self.rebase_media=true;self.waiting_for_keyframe=true;self.request_encoder_keyframe=true;
            }
            if(state==GST_STATE_PLAYING || self.media_playing)self.prepare_until={};
            self.media_playing=state==GST_STATE_PLAYING;
        }),data);
        self.request_encoder_keyframe.store(true);
    }

    static gboolean tick(gpointer data) {
        auto& self = *static_cast<Impl*>(data);
        GstBus* bus = self.encoder_pipeline ? gst_element_get_bus(self.encoder_pipeline) : nullptr;
        GstMessage* error = bus ? gst_bus_pop_filtered(bus, GST_MESSAGE_ERROR) : nullptr;
        if(bus)gst_object_unref(bus);
        if (error) {
            GError* detail{}; gchar* debug{};
            gst_message_parse_error(error, &detail, &debug);
            if (debug) std::cerr << "encoder error detail: " << debug << '\n';
            {
                std::lock_guard lock(self.mutex);
                self.worker_error = Error{ErrorCode::pipeline, detail ? detail->message : "encoder failed"};
            }
            if (detail) g_error_free(detail);
            g_free(debug);
            gst_message_unref(error);
            self.reader_done.store(true);
        }
        bool failed;
        {std::lock_guard lock(self.mutex);failed=self.worker_error.has_value();}
        if (stop_signal || failed) {
            self.timer_id = 0;
            g_main_loop_quit(self.loop);
            return G_SOURCE_REMOVE;
        }
        const auto now = std::chrono::steady_clock::now();
        self.expire_clients(now);
        self.update_capture(now);
        if (now >= self.next_session_cleanup) {
            GstRTSPSessionPool* pool = gst_rtsp_server_get_session_pool(self.server);
            const guint removed = gst_rtsp_session_pool_cleanup(pool);
            if (removed) std::cerr << "rtsp_sessions expired=" << removed << '\n';
            gst_object_unref(pool);
            self.next_session_cleanup = now + std::chrono::seconds(1);
        }
        return G_SOURCE_CONTINUE;
    }

    void create_encoder() {
        GError* parse_error{};
        encoder_pipeline=gst_parse_launch(encoder_description.c_str(),&parse_error);
        if(parse_error || !encoder_pipeline){
            const std::string message=parse_error ? parse_error->message : "cannot create encoder";
            if(parse_error)g_error_free(parse_error);
            throw std::runtime_error(message);
        }
        encoder_source=GST_APP_SRC(gst_bin_get_by_name(GST_BIN(encoder_pipeline),"encoder_source"));
        encoder_sink=GST_APP_SINK(gst_bin_get_by_name(GST_BIN(encoder_pipeline),"encoded_sink"));
        g_signal_connect(encoder_sink,"new-sample",G_CALLBACK(encoded_sample),this);
    }
    void release_encoder()noexcept {
        if(encoder_pipeline){
            gst_element_set_state(encoder_pipeline,GST_STATE_NULL);
            gst_element_get_state(encoder_pipeline,nullptr,nullptr,5*GST_SECOND);
            auto* bus=gst_element_get_bus(encoder_pipeline);gst_bus_set_flushing(bus,TRUE);gst_object_unref(bus);
        }
        if(encoder_source){gst_object_unref(encoder_source);encoder_source=nullptr;}
        if(encoder_sink){gst_object_unref(encoder_sink);encoder_sink=nullptr;}
        if(encoder_pipeline){gst_object_unref(encoder_pipeline);encoder_pipeline=nullptr;}
    }

    void update_capture(std::chrono::steady_clock::time_point now) {
        bool stereo;
        {std::lock_guard lock(mutex);stereo=active_source && (media_playing || now<prepare_until);}
        const bool demand=!on_demand()||stereo||depth_endpoint.has_demand();
        if(reader.joinable() && reader_done.load()) {
            reader.join();
            // All producers and camera leases are gone before releasing VPU.
            release_encoder();
            depth_endpoint.begin_capture(); // Clear a previous session's depth failure.
            stopping_capture=false;
            std::cerr<<"capture_lifecycle phase=idle resources_released=1\n";
        }
        if(demand)idle_since.reset();
        else if(!idle_since)idle_since=now;
        if(reader.joinable()) {
            if(!demand && !stopping_capture && now-*idle_since>=std::chrono::seconds(1)) {
                stopping_capture=true;reader.request_stop();
                std::cerr<<"capture_lifecycle phase=stopping reason=no_media\n";
            }
            return;
        }
        if(!demand)return;
        try{create_encoder();}catch(const std::exception& error){
            std::lock_guard lock(mutex);worker_error=Error{ErrorCode::pipeline,error.what()};return;
        }
        reader_done=false;have_timestamp=false;
        {std::lock_guard lock(mutex);waiting_for_keyframe=true;}
        depth_endpoint.begin_capture();
        std::cerr<<"capture_lifecycle phase=starting stereo="<<stereo<<" depth="<<depth_endpoint.has_demand()<<'\n';
        reader=std::jthread([this](std::stop_token stop){
            try {
                KernelTrigger trigger;
                if(gst_element_set_state(encoder_pipeline,GST_STATE_PLAYING)==GST_STATE_CHANGE_FAILURE)
                    throw std::runtime_error("cannot start encoder");
                read_frames(stop,eye_width,eye_height);
                trigger.stop();
            }catch(const std::exception& error){
                std::lock_guard lock(mutex);worker_error=Error{ErrorCode::input,error.what()};
            }
            reader_done=true;
        });
    }

    std::variant<std::monostate, Error> run() {
        const auto planned=detail::image_processing_plan(settings);
        if(const auto* error=std::get_if<detail::ImagePlanError>(&planned))
            return Error{ErrorCode::invalid_config,"image_processing_plan code="+std::to_string(int(*error))};
        const bool experimental = settings.capture_mode != CaptureMode::external_trigger;
        const bool binning = settings.capture_mode == CaptureMode::experimental_linear120_binning ||
                             settings.capture_mode == CaptureMode::experimental_linear60_binning ||
                             settings.capture_mode == CaptureMode::linear_binning;
        const int expected_fps = settings.capture_mode == CaptureMode::linear_binning ? settings.frame_rate :
            (settings.capture_mode == CaptureMode::experimental_linear60_binning ? 60 : 120);
        if (settings.capture_mode == CaptureMode::linear_binning &&
            (settings.frame_rate < 1 || settings.frame_rate > 60))
            return Error{ErrorCode::invalid_config, "Linear binning supports integer FPS 1..60"};
        if (experimental && (settings.frame_rate != expected_fps || settings.auto_exposure))
            return Error{ErrorCode::invalid_config,
                         "experimental capture requires matching frame rate and manual startup; enable binning 60 AE after timing setup"};
        if (binning && settings.downscale != 1)
            return Error{ErrorCode::invalid_config, "hardware binning requires downscale=1"};
        if ((settings.downscale != 1 && settings.downscale != 2 &&
             settings.downscale != 4) || settings.frame_rate < 1 ||
            settings.frame_rate > (experimental ? expected_fps : 60) || settings.mount.empty() ||
            settings.mount.front() != '/' ||
            settings.target_brightness_percent < 0 ||
            settings.target_brightness_percent > 100 || settings.bitrate < 100000 ||
            settings.bitrate > 100000000) {
            return Error{ErrorCode::invalid_config,
                         "invalid downscale, frame rate, brightness or mount for capture mode"};
        }
        stop_signal = 0;
        const auto old_int = std::signal(SIGINT, signal_stop);
        const auto old_term = std::signal(SIGTERM, signal_stop);
        gst_init(nullptr, nullptr);
        const int sensor_scale = binning ? 2 : 1;
        eye_width = kInputWidth / sensor_scale / settings.downscale;
        eye_height = kInputEyeHeight / sensor_scale / settings.downscale;
        const int output_width = eye_width * 2;
        encoder_description = settings.main10 ?
            "appsrc name=encoder_source is-live=true block=false format=time "
            "max-buffers=32 max-bytes=0 max-time=0 "
            "caps=video/x-h265,stream-format=byte-stream,alignment=au "
            "! h265parse config-interval=-1 "
            "! video/x-h265,stream-format=byte-stream,alignment=au,profile=main-10 "
            "! appsink name=encoded_sink enable-last-sample=false emit-signals=true sync=false max-buffers=3 drop=true" :
            "appsrc name=encoder_source is-live=true block=false format=time "
            "max-buffers=3 max-bytes=0 max-time=0 leaky-type=downstream "
            "caps=video/x-raw,format=NV12,width=" +
            std::to_string(output_width) + ",height=" + std::to_string(eye_height) +
            ",framerate=" + std::to_string(settings.frame_rate) +
            "/1,interlace-mode=progressive,colorimetry="+
            std::string(settings.display_range==VideoRange::full?"1:3:5:1 ":"bt709 ")+
            "! queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 "
            "leaky=downstream "
            "! v4l2h265enc output-io-mode=mmap capture-io-mode=mmap "
            "extra-controls=\"controls,vui_timing_info=1,prepend_sps_and_pps_to_idr=1\" "
            "! h265parse config-interval=-1 "
            "! video/x-h265,stream-format=byte-stream,alignment=au "
            "! appsink name=encoded_sink enable-last-sample=false emit-signals=true sync=false max-buffers=3 drop=true";
        // A configured RTSP media requests frames for preparation and playback.
        // Hardware resources are scoped to the union of both media demands.
        const std::string pipeline =
            "( appsrc name=stereo_source is-live=true block=false format=time "
            "max-buffers=3 max-bytes=0 max-time=0 leaky-type=downstream "
            "caps=video/x-h265,stream-format=byte-stream,alignment=au "
            "! h265parse ! rtph265pay name=pay0 pt=96 config-interval=-1 )";
        loop = g_main_loop_new(nullptr, FALSE);
        server = gst_rtsp_server_new();
        g_signal_connect(server, "client-connected", G_CALLBACK(client_connected), this);
        factory = gst_rtsp_media_factory_new();
        gst_rtsp_server_set_address(server, settings.bind_address.c_str());
        gst_rtsp_server_set_service(server, settings.port.c_str());
        gst_rtsp_media_factory_set_shared(factory, TRUE);
        // TCP clients can disappear without TEARDOWN (player reconnect/crash).
        // Release that media instead of retaining a hardware encoder session.
        gst_rtsp_media_factory_set_stop_on_disconnect(factory, TRUE);
        gst_rtsp_media_factory_set_protocols(factory, GST_RTSP_LOWER_TRANS_TCP);
        gst_rtsp_media_factory_set_launch(factory, pipeline.c_str());
        g_signal_connect(factory, "media-configure", G_CALLBACK(media_configure), this);
        GstRTSPMountPoints* mounts = gst_rtsp_server_get_mount_points(server);
        gst_rtsp_mount_points_add_factory(mounts, settings.mount.c_str(),
                                          GST_RTSP_MEDIA_FACTORY(gst_object_ref(factory)));
        if(!settings.depth_calibration.empty())depth_endpoint.mount(mounts);
        gst_object_unref(mounts);
        attach_id = gst_rtsp_server_attach(server, nullptr);
        if (!attach_id) {
            std::signal(SIGINT, old_int);
            std::signal(SIGTERM, old_term);
            return Error{ErrorCode::server, "could not bind RTSP server"};
        }
        timer_id = g_timeout_add(100, tick, this);
        std::cerr << "RTSP ready: rtsp://" << settings.bind_address << ':'
                  << settings.port << settings.mount << " (" << output_width << 'x'
                  << eye_height << '@' << settings.frame_rate << ", "
                  << (settings.main10 ? "Main10 linear R16/P010" : "Main NV12") << ")\n";
        initialize_control();
        if(KernelTrigger::available())KernelTrigger::command("stop");
        if(on_demand())std::cerr<<"capture_lifecycle phase=idle resources_released=1\n";
        g_main_loop_run(loop);
        reader.request_stop();
        if(reader.joinable())reader.join();
        release_encoder();
        const char* trace_directory = std::getenv("SC132GS_CAPTURE_TRACE_DIR");
        const auto trace_path = std::string(trace_directory ? trace_directory : "/tmp") +
            "/sc132gs-processing-" + std::to_string(::getpid()) + "-" +
            std::to_string(detail::capture_now_ns()) + ".jsonl";
        if (processing_trace.dump(trace_path))
            std::cerr << "processing_trace path=" << trace_path << '\n';
        close_clients();
        std::signal(SIGINT, old_int);
        std::signal(SIGTERM, old_term);
        std::cerr << "input_pairs=" << input_pairs
                  << " submitted_pairs=" << submitted_pairs
                  << " dropped_pairs=" << dropped_pairs << '\n';
        if (worker_error) return *worker_error;
        return std::monostate{};
    }

    static void calibrate_pair(const detail::SensorSignalCalibration& calibration, FramePair& pair) {
        using Code=detail::SensorSignalCalibration::ErrorCode;
        if(calibration.apply(pair.left_luma10.data(),pair.left_luma10.size())!=Code::none ||
           calibration.apply(pair.right_luma10.data(),pair.right_luma10.size())!=Code::none)
            throw std::runtime_error("invalid sensor signal frame");
    }

    void initialize_control() {
        const auto plan=std::get<detail::ImageProcessingPlan>(detail::image_processing_plan(settings));
        const bool sensor_signal=plan.sensor_signal;
        const bool binning60 = settings.capture_mode == CaptureMode::experimental_linear60_binning ||
                               settings.capture_mode == CaptureMode::linear_binning;
        exposure_control=std::make_unique<AutoExposure>(plan.capture10 ? (settings.hdr_display_b ?
                              AutoExposure::LumaEncoding::hdr_preview_b : (sensor_signal ?
                              AutoExposure::LumaEncoding::sensor_signal : AutoExposure::LumaEncoding::sensor_linear)) :
                                               AutoExposure::LumaEncoding::hdr_display,
                              binning60 ? AutoExposure::LinearTiming{
                                  sc132gs::configuration::detail::binning_rows_per_second(settings.frame_rate),
                                  2560, settings.frame_rate} :
                                  AutoExposure::LinearTiming{84000, 0, settings.frame_rate,
                                      settings.capture_mode==CaptureMode::external_trigger ?
                                      sc132gs::exposure_budget::reserved_rows(false,settings.frame_rate) : 0});
        auto& exposure=*exposure_control;
        if (settings.capture_mode != CaptureMode::external_trigger &&
            exposure.snapshot().hdr_enabled)
            throw std::runtime_error("experimental Linear 120 cannot run in HDR mode");
        exposure.set_target(settings.target_brightness_percent);
        if (!settings.auto_exposure) exposure.disable();
        if(settings.capture_mode==CaptureMode::external_trigger || binning60)
            control=std::make_unique<ControlServer>(exposure);
    }

    void read_frames(std::stop_token stop, int eye_width, int eye_height) {
        const auto plan=std::get<detail::ImageProcessingPlan>(detail::image_processing_plan(settings));
        const bool binning60 = settings.capture_mode == CaptureMode::experimental_linear60_binning ||
                               settings.capture_mode == CaptureMode::linear_binning;
        const bool sensor_signal=plan.sensor_signal;
        auto& exposure=*exposure_control;
        const bool linear_display = !exposure.snapshot().hdr_enabled;
        if(plan.shared_y8 && !linear_display)
            throw std::runtime_error("shared tone mapping requires Linear sensor mode");
        if(!linear_display && !settings.gpu_rectification_map.empty())
            throw std::runtime_error("GPU rectification is validated for Linear mono10 only");
        if(settings.main10 && !linear_display)
            std::cerr << "hdr_display_profile=" << (settings.hdr_display_b ? "b" : "sensor") << '\n';
        const sc132gs::HdrDisplay hdr_display;
        StereoToneMapper tone_mapper;
        StereoToneMapper::FrameInfo tone_info{};
        StereoDetailMapper detail_mapper;
        StereoDetailMapper::FrameInfo detail_info{};
        std::uint64_t depth_transition_pairs{};
        std::unique_ptr<detail::SensorSignalCalibration> calibration;
        if(sensor_signal) {
            calibration=std::make_unique<detail::SensorSignalCalibration>(!linear_display);
            std::cerr << "sensor_signal black_raw10=" << calibration->black_level() << " gamma=1\n";
        }
        std::unique_ptr<detail::Main10Encoder> main10;
        std::vector<std::uint16_t> stereo10;
        if (settings.main10) {
            main10 = std::make_unique<detail::Main10Encoder>(eye_width*2,eye_height,
                                                           settings.frame_rate,settings.bitrate);
            stereo10.resize(static_cast<std::size_t>(eye_width)*2*eye_height);
        }
        std::unique_ptr<detail::GpuStereoRectifier> rectifier;
        if(!settings.gpu_rectification_map.empty()) {
            try {rectifier=std::make_unique<detail::GpuStereoRectifier>(settings.gpu_rectification_map);}
            catch(const detail::RectificationError& e) {throw std::runtime_error("gpu_rectification initialization code="+std::to_string(int(e.code))+" native="+std::to_string(e.native_code));}
        }
        std::unique_ptr<detail::DepthPipeline> depth;
        if(!settings.depth_calibration.empty()) {
            try {depth=std::make_unique<detail::DepthPipeline>(settings.depth_calibration,depth_endpoint);}
            catch(const std::exception&) {depth_endpoint.on_depth_error({detail::DepthStage::initialization});}
        }
        struct Main10Sink final : detail::StereoOutputWorker::Observer {
            Impl& owner;explicit Main10Sink(Impl& o):owner(o){}
            void on_stereo_access_unit(const detail::StereoAccessUnit& unit)noexcept override {
                auto* buffer=gst_buffer_new_allocate(nullptr,unit.bytes,nullptr);
                if(!buffer){on_stereo_processing_error({detail::StereoProcessingStage::internal});return;}
                gst_buffer_fill(buffer,0,unit.data,unit.bytes);GST_BUFFER_PTS(buffer)=unit.pts_ns;
                GST_BUFFER_DTS(buffer)=GST_CLOCK_TIME_NONE;GST_BUFFER_DURATION(buffer)=GST_SECOND/owner.settings.frame_rate;
                if(!unit.keyframe)GST_BUFFER_FLAG_SET(buffer,GST_BUFFER_FLAG_DELTA_UNIT);
                if(gst_app_src_push_buffer(owner.encoder_source,buffer)!=GST_FLOW_OK)on_stereo_processing_error({detail::StereoProcessingStage::encoding});
            }
            void on_stereo_processing_error(detail::StereoProcessingError error)noexcept override {
                {std::lock_guard lock(owner.mutex);owner.worker_error=Error{ErrorCode::pipeline,"stereo_processing stage="+std::to_string(int(error.stage))+" native="+std::to_string(error.native_code)};}
                owner.reader_done=true;
            }
        } main10_sink(*this);
        struct Luma8Sink final : detail::StereoOutputWorker::Luma8Observer {
            Impl& owner;Main10Sink& errors;
            Luma8Sink(Impl& o,Main10Sink& e):owner(o),errors(e){}
            bool on_stereo_luma8(const detail::StereoLuma8& frame)noexcept override {
                if(gst_app_src_get_current_level_buffers(owner.encoder_source)>=3)return false;
                auto* buffer=gst_buffer_new_allocate(nullptr,frame.bytes*3/2,nullptr);
                if(!buffer){on_stereo_processing_error({detail::StereoProcessingStage::internal});return false;}
                GstMapInfo map{};
                if(!gst_buffer_map(buffer,&map,GST_MAP_WRITE)) {
                    gst_buffer_unref(buffer);on_stereo_processing_error({detail::StereoProcessingStage::internal});return false;
                }
                std::memcpy(map.data,frame.data,frame.bytes);
                std::memset(map.data+frame.bytes,128,frame.bytes/2);
                gst_buffer_unmap(buffer,&map);
                GST_BUFFER_PTS(buffer)=frame.pts_ns;GST_BUFFER_DTS(buffer)=GST_CLOCK_TIME_NONE;
                GST_BUFFER_DURATION(buffer)=GST_SECOND/owner.settings.frame_rate;
                const auto flow=gst_app_src_push_buffer(owner.encoder_source,buffer);
                if(flow!=GST_FLOW_OK && flow!=GST_FLOW_FLUSHING)
                    on_stereo_processing_error({detail::StereoProcessingStage::encoding,int(flow)});
                return flow==GST_FLOW_OK;
            }
            void on_stereo_processing_error(detail::StereoProcessingError error)noexcept override {
                errors.on_stereo_processing_error(error);
            }
        } luma8_sink(*this,main10_sink);
        std::unique_ptr<detail::StereoOutputWorker> stereo_worker;
        if(rectifier) {
            if(settings.main10)stereo_worker=std::make_unique<detail::StereoOutputWorker>(*main10,*rectifier,main10_sink);
            else stereo_worker=std::make_unique<detail::StereoOutputWorker>(*rectifier,luma8_sink,settings.display_range,settings.detail_tone_map?VideoRange::full:VideoRange::limited);
        }
        // Prepare the consumer before STREAMON: VPU startup must not exhaust
        // the cameras' eight hardware buffers before the first dequeue. The
        // reverse destruction order stops camera DMA before closing the VPU.
        struct ImuSink final : gs130wi::Capture::Observer {
            std::atomic<std::uint64_t> samples{},markers{};
            bool on_imu_batch(const gs130wi::ImuBatch& batch) noexcept override {
                samples+=batch.samples.size();
                for(const auto& sample:batch.samples)if(sample.fsync_offset_ns)++markers;
                return true;
            }
        } imu_sink;
        std::unique_ptr<StereoCapture> capture;
        std::optional<gs130wi::Capture> shared_capture;
        if(settings.capture_api) {
            if(!plan.capture10 || settings.frame_rate!=30 ||
               settings.capture_mode!=CaptureMode::external_trigger || exposure.snapshot().hdr_enabled)
                throw std::runtime_error("capture-api requires Linear/mono10/30-Hz external trigger");
            gs130wi::Options options;
            options.left_device=settings.cam0; options.right_device=settings.cam1;
            options.downscale=settings.downscale;
            auto opened=gs130wi::Capture::open(std::move(options),&imu_sink);
            if(const auto* error=std::get_if<gs130wi::Error>(&opened))
                throw std::runtime_error("capture-api open failed code="+std::to_string(int(error->code))+
                                         " errno="+std::to_string(error->system_errno));
            shared_capture.emplace(std::get<gs130wi::Capture>(std::move(opened)));
        } else {
            capture=std::make_unique<StereoCapture>(settings.cam0,settings.cam1,settings.downscale,
                settings.frame_rate,!plan.capture10 && exposure.snapshot().hdr_enabled,
                settings.capture_mode,plan.capture10);
        }
        std::stop_callback stop_shared(stop,[&] { if(shared_capture)shared_capture->request_stop(); });
        const std::size_t y_bytes = static_cast<std::size_t>(eye_width) * eye_height * 2;
        const std::size_t nv12_bytes = y_bytes * 3 / 2;
        auto interval_start = std::chrono::steady_clock::now();
        std::uint64_t interval_input = 0, interval_submitted = 0;
        std::uint64_t interval_dropped = 0;
        std::uint64_t previous_encoded = encoded_pairs.load(), previous_delivered = delivered_pairs.load();
        const auto submitted_base=submitted_pairs, dropped_base=dropped_pairs;
        std::uint64_t previous_worker_submitted{}, previous_worker_dropped{};
        while (!stop.stop_requested()) {
            FramePair pair;
            detail::CaptureSpan acquire_span(processing_trace, detail::CaptureOperation::acquire);
            if(shared_capture) {
                auto result=shared_capture->next_frame();
                if(const auto* error=std::get_if<gs130wi::Error>(&result)) {
                    if(stop.stop_requested())break;
                    throw std::runtime_error("capture-api read failed code="+std::to_string(int(error->code)));
                }
                auto frame=std::get<gs130wi::StereoFrame>(std::move(result));
                pair.cam0_sequence=frame.images[0].sequence; pair.cam1_sequence=frame.images[1].sequence;
                pair.cam0_timestamp_ns=frame.images[0].monotonic_timestamp_ns;
                pair.cam1_timestamp_ns=frame.images[1].monotonic_timestamp_ns;
                pair.left_luma10=std::move(frame.images[0].mono10);
                pair.right_luma10=std::move(frame.images[1].mono10);
                for(unsigned eye=0;eye<2;++eye) {
                    const auto& s=frame.images[eye].statistics;
                    auto& d=eye?pair.right_hdr:pair.left_hdr;
                    d={s.shadow,s.saturation_bp,s.histogram,s.luma_median};
                    auto& highlights=eye?pair.right_highlights:pair.left_highlights;
                    highlights={s.raw_sample_count,s.raw_near_saturated_count,s.raw_highlights_valid};
                }
            } else pair=capture->next(stop);
            acquire_span.finish();
            if (stop.stop_requested()) break;
            if (have_timestamp && pair.cam0_timestamp_ns <= last_timestamp_ns) {
                throw std::runtime_error("camera timestamps are not increasing");
            }
            have_timestamp = true;
            last_timestamp_ns = pair.cam0_timestamp_ns;
            // HDR statistics retain unmodified luma/RAW clipping; its AE
            // calibrates only the median. Linear AE reads calibrated frames.
            const bool control_pending=plan.shared_y8 && exposure.snapshot().remaining_holdoff_pairs>0;
            if(calibration && linear_display) {
                detail::CaptureSpan timing(processing_trace, detail::CaptureOperation::calibration, pair.cam0_sequence);
                calibrate_pair(*calibration,pair);
            }
            {
            detail::CaptureSpan timing(processing_trace, detail::CaptureOperation::automatic_exposure, pair.cam0_sequence);
            if (!linear_display)
                exposure.process_hdr_statistics(pair.left_hdr,pair.right_hdr,
                    pair.cam0_sequence,pair.cam0_timestamp_ns);
            else if (plan.capture10)
                exposure.process_linear_luma10(pair.left_luma10, pair.right_luma10,
                                       eye_width, eye_height,pair.left_highlights,pair.right_highlights,
                                       pair.cam0_sequence,pair.cam0_timestamp_ns);
            else exposure.process_luma(pair.left_luma, pair.right_luma,
                                  eye_width, eye_height, pair.cam0_sequence,
                                  pair.cam0_timestamp_ns);
            }
            if(calibration && !linear_display) {
                detail::CaptureSpan timing(processing_trace, detail::CaptureOperation::calibration, pair.cam0_sequence);
                calibrate_pair(*calibration,pair);
            }
            if(plan.shared_y8) {
                detail::CaptureSpan timing(processing_trace, detail::CaptureOperation::tone_mapping, pair.cam0_sequence);
                const auto count=pair.left_luma10.size();
                pair.left_luma.resize(count);pair.right_luma.resize(count);
                if(settings.detail_tone_map){
                    const auto result=detail_mapper.process(
                        {pair.left_luma10.data(),count},{pair.right_luma10.data(),pair.right_luma10.size()},
                        {pair.left_luma.data(),count},{pair.right_luma.data(),count},pair.cam0_timestamp_ns);
                    if(!result)throw std::runtime_error("stereo_detail_mapping code="+std::to_string(int(result.error)));
                    detail_info=result.frame;
                }else{
                const auto result=tone_mapper.process(
                    {pair.left_luma10.data(),count},{pair.right_luma10.data(),pair.right_luma10.size()},
                    {pair.left_luma.data(),count},{pair.right_luma.data(),count},pair.cam0_timestamp_ns);
                if(!result)throw std::runtime_error("stereo_tone_mapping code="+std::to_string(int(result.error)));
                tone_info=result.frame;
                }
            }
            // Depth receives a bounded copy and owns neither camera nor AE.
            if(depth) {
                detail::CaptureSpan timing(processing_trace, detail::CaptureOperation::depth_submit, pair.cam0_sequence);
                if(depth_endpoint.take_keyframe_request())depth->request_keyframe();
                // Exclude the command pair and the conservative settling window.
                // This is pacing, not proof of sensor setting/frame association.
                const bool control_transition=plan.shared_y8 &&
                    (control_pending || exposure.snapshot().remaining_holdoff_pairs>0);
                if(control_transition) ++depth_transition_pairs;
                else if(plan.shared_y8)
                    depth->submit8(pair.left_luma.data(),pair.right_luma.data(),pair.left_luma.size(),pair.cam0_timestamp_ns);
                else depth->submit(pair.left_luma10.data(),pair.right_luma10.data(),pair.left_luma10.size(),pair.cam0_timestamp_ns);
            }
            ++input_pairs;
            ++interval_input;
            if(!settings.main10 && request_encoder_keyframe.exchange(false))
                gst_element_send_event(GST_ELEMENT(encoder_sink),
                    gst_video_event_new_upstream_force_key_unit(GST_CLOCK_TIME_NONE,TRUE,0));
            GstAppSrc* source = GST_APP_SRC(gst_object_ref(encoder_source));
            if (first_input_timestamp_ns < 0)
                first_input_timestamp_ns = pair.cam0_timestamp_ns;
            const auto pts = static_cast<GstClockTime>(
                pair.cam0_timestamp_ns - first_input_timestamp_ns);
            detail::CaptureSpan encoder_timing(processing_trace, detail::CaptureOperation::encoder_submit, pair.cam0_sequence);
            if(stereo_worker) {
                if(settings.main10) {
                    if(request_encoder_keyframe.exchange(false))stereo_worker->request_keyframe();
                    stereo_worker->submit(std::move(pair));
                } else stereo_worker->submit8(std::move(pair),pts);
                gst_object_unref(source);
            } else if (settings.main10) {
                if (request_encoder_keyframe.exchange(false)) main10->request_keyframe();
                for(int y=0;y<eye_height;++y) {
                    auto* row=stereo10.data()+static_cast<std::size_t>(y)*eye_width*2;
                    for(int x=0;x<eye_width;++x) {
                        row[x]=pair.left_luma10[static_cast<std::size_t>(y)*eye_width+eye_width-1-x];
                        row[eye_width+x]=pair.right_luma10[static_cast<std::size_t>(y)*eye_width+eye_width-1-x];
                    }
                }
                // Drain the encoded queue every capture tick so downstream clients
                // never own the encoder or its hardware buffer lifetimes.
                auto push_encoded = [&](std::vector<detail::EncodedFrame> frames) {
                    for(auto& frame:frames) {
                        GstBuffer* b=gst_buffer_new_allocate(nullptr,frame.bytes.size(),nullptr);
                        if(!b) throw std::runtime_error("cannot allocate HEVC access unit");
                        gst_buffer_fill(b,0,frame.bytes.data(),frame.bytes.size());
                        GST_BUFFER_PTS(b)=frame.timestamp_ns;
                        GST_BUFFER_DTS(b)=GST_CLOCK_TIME_NONE;
                        GST_BUFFER_DURATION(b)=GST_SECOND/settings.frame_rate;
                        if(!frame.keyframe) GST_BUFFER_FLAG_SET(b,GST_BUFFER_FLAG_DELTA_UNIT);
                        if(gst_app_src_push_buffer(source,b)!=GST_FLOW_OK)
                            throw std::runtime_error("Main10 parser rejected access unit");
                    }
                };
                push_encoded(main10->receive());
                if(!linear_display && settings.hdr_display_b) hdr_display.apply(stereo10);
                if(main10->submit(stereo10,pts)) {++submitted_pairs;++interval_submitted;}
                else {++dropped_pairs;++interval_dropped;}
                push_encoded(main10->receive());
                gst_object_unref(source);
            } else if (source) {
                // Keep capture and auto exposure running when a client or encoder
                // falls behind. The appsrc limit also handles a race after this check.
                if (gst_app_src_get_current_level_buffers(source) >= 3) {
                    ++dropped_pairs;
                    ++interval_dropped;
                    gst_object_unref(source);
                } else {
                    GstBuffer* buffer = gst_buffer_new_allocate(nullptr, nv12_bytes, nullptr);
                    if (!buffer) {
                        gst_object_unref(source);
                        throw std::runtime_error("cannot allocate NV12 frame");
                    }
                    GstMapInfo map{};
                    if (!gst_buffer_map(buffer, &map, GST_MAP_WRITE)) {
                        gst_buffer_unref(buffer);
                        gst_object_unref(source);
                        throw std::runtime_error("cannot map NV12 frame");
                    }
                    detail::compose_mirrored_side_by_side_nv12(
                        pair.left_luma.data(), pair.right_luma.data(),
                        map.data, eye_width, eye_height);
                    if (linear_display && !plan.shared_y8)
                        detail::encode_linear_video_luma(std::span<std::uint8_t>(
                            map.data, static_cast<std::size_t>(eye_width) * 2 * eye_height));
                    gst_buffer_unmap(buffer, &map);
                    GST_BUFFER_PTS(buffer) = pts;
                    GST_BUFFER_DURATION(buffer) = GST_SECOND / settings.frame_rate;
                    const GstFlowReturn flow = gst_app_src_push_buffer(source, buffer);
                    gst_object_unref(source);
                    if (flow == GST_FLOW_OK) {
                        ++submitted_pairs;
                        ++interval_submitted;
                    } else if (flow != GST_FLOW_FLUSHING) {
                        throw std::runtime_error("GStreamer appsrc push failed: " +
                                                 std::to_string(flow));
                    }
                }
            }
            encoder_timing.finish();
            const auto now = std::chrono::steady_clock::now();
            const auto seconds = std::chrono::duration<double>(now - interval_start).count();
            if (seconds >= 5.0) {
                if(stereo_worker){
                    const auto s=stereo_worker->statistics();
                    const auto dropped=s.dropped+s.replaced;
                    interval_submitted=s.submitted-previous_worker_submitted;
                    interval_dropped=dropped-previous_worker_dropped;
                    previous_worker_submitted=s.submitted;previous_worker_dropped=dropped;
                    submitted_pairs=submitted_base+s.submitted;dropped_pairs=dropped_base+dropped;
                }
                const auto encoded = encoded_pairs.load();
                const auto delivered = delivered_pairs.load();
                std::cerr << "input_fps=" << interval_input / seconds
                          << " submitted_fps=" << interval_submitted / seconds
                          << " dropped_fps=" << interval_dropped / seconds
                          << " encoded_fps=" << (encoded - previous_encoded) / seconds
                          << " rtsp_fps=" << (delivered - previous_delivered) / seconds
                          << " pairs=" << input_pairs << '\n';
                std::cerr << "processing_timing";
                const auto report_timing = [&](detail::CaptureOperation operation, const char* label) {
                    const auto t = processing_trace.timing(operation);
                    std::cerr << ' ' << label << "_mean_ms=" << (t.count ? t.total_ns / 1e6 / t.count : 0)
                              << ' ' << label << "_max_ms=" << t.max_ns / 1e6;
                };
                report_timing(detail::CaptureOperation::calibration, "calibration");
                report_timing(detail::CaptureOperation::automatic_exposure, "ae");
                report_timing(detail::CaptureOperation::tone_mapping, "tone");
                report_timing(detail::CaptureOperation::depth_submit, "depth_submit");
                report_timing(detail::CaptureOperation::encoder_submit, "encoder");
                std::cerr << '\n';
                if(rectifier) {
                    const auto ae=exposure.snapshot();
                    const auto s=stereo_worker->statistics();
                    std::cerr<<"gpu_rectification active=1 order=cam1_cam0 width=2176 height=1280 bits="<<(settings.main10?10:8)<<" frames="<<s.processed
                             <<" mean_gpu_ms="<<(s.processed?s.gpu_ns/1e6/s.processed:0)
                             <<" depth_encoded="<<depth_endpoint.encoded()
                             <<" ae="<<ae.enabled<<" target="<<ae.target_percent
                             <<" exposure_rows="<<ae.exposure_lines<<" gain_index="<<ae.analogue_gain_index<<" ae_error="<<ae.last_error<<'\n';
                    if(depth){const auto d=depth->statistics();std::cerr<<"depth_pipeline submitted="<<d.submitted<<" processed="<<d.processed<<" replaced="<<d.replaced<<" busy="<<d.busy<<" failed="<<d.failed<<'\n';}
                }
                if (binning60) {
                    const auto ae = exposure.snapshot();
                    std::cerr << "ae=" << ae.enabled << " target_linear_percent=" << ae.target_percent
                              << " measured=" << ae.cam0_percent << ',' << ae.cam1_percent
                              << " exposure_rows=" << ae.exposure_lines << " cap=" << ae.max_exposure_lines
                              << " gain_index=" << ae.analogue_gain_index
                              << " limited=" << ae.brightness_limited << " error=" << ae.last_error << '\n';
                }
                if(plan.shared_y8) {
                    const auto ae=exposure.snapshot();
                    if(settings.detail_tone_map)std::cerr<<"detail_tone active=1 bits=8 range=full source_bits=10 strength=1 clip_limit=4 shared_lut=1"
                        <<" lut="<<detail_info.revision<<" fallback="<<detail_info.fallback
                        <<" video_range="<<(settings.display_range==VideoRange::full?"full":"limited")<<'\n';
                    else std::cerr<<"shared_tone bits=8 range=limited transfer=bt709 lut="<<tone_info.lut_revision
                             <<" gain="<<tone_info.applied_gain<<" fallback="<<tone_info.fallback
                             <<" raw_clip_bp="<<ae.cam0_saturation_bp<<','<<ae.cam1_saturation_bp
                             <<" highlight_limited="<<ae.highlight_limited
                             <<" effect_frame_validated="<<ae.control_effect_frame_validated<<'\n';
                    if(depth){const auto d=depth->statistics();std::cerr<<"depth_mono8 submitted="<<d.submitted<<" processed="<<d.processed<<" withheld_transition="<<depth_transition_pairs<<" failed="<<d.failed<<'\n';}
                }
                interval_start = now;
                previous_encoded = encoded;
                previous_delivered = delivered;
                interval_input = interval_submitted = interval_dropped = 0;
            }
        }
        if(shared_capture) {
            if(const auto error=shared_capture->stop())
                throw std::runtime_error("capture-api restore failed code="+std::to_string(int(error->code)));
            std::cout<<"capture_api_imu samples="<<imu_sink.samples<<" fsync_packets="<<imu_sink.markers
                     <<" frame_association_validated=false host_sample_time_validated=false\n";
        }
        capture.reset();
        if(depth)depth->stop();
        if(stereo_worker){stereo_worker->stop();const auto s=stereo_worker->statistics();submitted_pairs=submitted_base+s.submitted;dropped_pairs=dropped_base+s.dropped+s.replaced;}
    }
};

StereoRtspServer::StereoRtspServer(Settings settings)
    : impl_(std::make_unique<Impl>(std::move(settings))) {}
StereoRtspServer::~StereoRtspServer() = default;
StereoRtspServer::StereoRtspServer(StereoRtspServer&&) noexcept = default;
StereoRtspServer& StereoRtspServer::operator=(StereoRtspServer&&) noexcept = default;
std::variant<std::monostate, Error> StereoRtspServer::run() { return impl_->run(); }

} // namespace stereo_rtsp
