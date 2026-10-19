#include "StereoRtspServer.hpp"
#include "FrameTiming.hpp"
#include "StereoCapture.hpp"
#include "StereoComposeNV12.hpp"
#include "LinearVideoLuma.hpp"
#include "Main10Encoder.hpp"
#include "SensorSignalCalibration.hpp"
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
#include <iostream>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>

namespace stereo_rtsp {
namespace {

constexpr int kInputWidth = 1088;
constexpr int kInputEyeHeight = 1280;
volatile std::sig_atomic_t stop_signal = 0;

void signal_stop(int) { stop_signal = 1; }

} // namespace

struct StereoRtspServer::Impl {
    explicit Impl(Settings value) : settings(std::move(value)) {}

    Settings settings;
    GMainLoop* loop{};
    GstRTSPServer* server{};
    GstRTSPMediaFactory* factory{};
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
    std::atomic<std::uint64_t> encoded_pairs{0};
    std::atomic<std::uint64_t> delivered_pairs{0};
    std::uint64_t input_pairs{};
    std::uint64_t submitted_pairs{};
    std::uint64_t dropped_pairs{};
    std::int64_t last_timestamp_ns{};
    bool have_timestamp{};
    std::atomic<bool> reader_done{false};
    std::atomic<bool> request_encoder_keyframe{false};
    std::chrono::steady_clock::time_point next_session_cleanup{};

    ~Impl() {
        close_clients();
        // Stop the callback producer before releasing its RTSP destination.
        if (encoder_pipeline) gst_element_set_state(encoder_pipeline, GST_STATE_NULL);
        if (encoder_source) gst_object_unref(encoder_source);
        if (encoder_sink) gst_object_unref(encoder_sink);
        if (encoder_pipeline) gst_object_unref(encoder_pipeline);
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
    }

    static void release_object(gpointer object) {
        gst_object_unref(object);
    }

    static void client_connected(GstRTSPServer*, GstRTSPClient* client, gpointer) {
        std::cerr << "rtsp_client phase=connected\n";
        g_signal_connect(client, "new-session", G_CALLBACK(+[](
            GstRTSPClient*, GstRTSPSession* session, gpointer) {
                gst_rtsp_session_set_timeout(session, 30);
                std::cerr << "rtsp_session phase=created timeout_seconds=30\n";
            }), nullptr);
        g_signal_connect(client, "closed", G_CALLBACK(+[](GstRTSPClient*, gpointer) {
            std::cerr << "rtsp_client phase=closed\n";
        }), nullptr);
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
            if (self.active_source && GST_CLOCK_TIME_IS_VALID(GST_BUFFER_PTS(encoded))) {
                if (!GST_BUFFER_FLAG_IS_SET(encoded, GST_BUFFER_FLAG_DELTA_UNIT))
                    self.waiting_for_keyframe = false;
                if (!self.waiting_for_keyframe) {
                    if (self.first_timestamp_ns < 0)
                        self.first_timestamp_ns = GST_BUFFER_PTS(encoded);
                    base = self.first_timestamp_ns;
                    destination = GST_APP_SRC(gst_object_ref(self.active_source));
                }
            }
        }
        if (destination) {
            GstBuffer* copy = gst_buffer_copy(encoded);
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
            g_object_set_data_full(G_OBJECT(media), "stereo_source_identity",
                                   gst_object_ref(source), release_object);
        }
        gst_object_unref(element);
        g_signal_connect(media, "unprepared", G_CALLBACK(media_unprepared), data);
        if (self.settings.main10) self.request_encoder_keyframe.store(true);
        else gst_element_send_event(GST_ELEMENT(self.encoder_sink),
            gst_video_event_new_upstream_force_key_unit(GST_CLOCK_TIME_NONE, TRUE, 0));
    }

    static gboolean tick(gpointer data) {
        auto& self = *static_cast<Impl*>(data);
        GstBus* bus = gst_element_get_bus(self.encoder_pipeline);
        GstMessage* error = gst_bus_pop_filtered(bus, GST_MESSAGE_ERROR);
        gst_object_unref(bus);
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
        if (stop_signal || self.reader_done.load()) {
            self.timer_id = 0;
            g_main_loop_quit(self.loop);
            return G_SOURCE_REMOVE;
        }
        const auto now = std::chrono::steady_clock::now();
        if (now >= self.next_session_cleanup) {
            GstRTSPSessionPool* pool = gst_rtsp_server_get_session_pool(self.server);
            const guint removed = gst_rtsp_session_pool_cleanup(pool);
            if (removed) std::cerr << "rtsp_sessions expired=" << removed << '\n';
            gst_object_unref(pool);
            self.next_session_cleanup = now + std::chrono::seconds(1);
        }
        return G_SOURCE_CONTINUE;
    }

    std::variant<std::monostate, Error> run() {
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
        const int eye_width = kInputWidth / sensor_scale / settings.downscale;
        const int eye_height = kInputEyeHeight / sensor_scale / settings.downscale;
        const int output_width = eye_width * 2;
        const std::string encoder_description = settings.main10 ?
            "appsrc name=encoder_source is-live=true block=false format=time "
            "max-buffers=32 max-bytes=0 max-time=0 "
            "caps=video/x-h265,stream-format=byte-stream,alignment=au "
            "! h265parse config-interval=-1 "
            "! video/x-h265,stream-format=byte-stream,alignment=au,profile=main-10 "
            "! appsink name=encoded_sink emit-signals=true sync=false max-buffers=3 drop=true" :
            "appsrc name=encoder_source is-live=true block=false format=time "
            "max-buffers=3 max-bytes=0 max-time=0 leaky-type=downstream "
            "caps=video/x-raw,format=NV12,width=" +
            std::to_string(output_width) + ",height=" + std::to_string(eye_height) +
            ",framerate=" + std::to_string(settings.frame_rate) +
            "/1,interlace-mode=progressive,colorimetry=bt709 "
            "! queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 "
            "leaky=downstream "
            "! v4l2h265enc output-io-mode=mmap capture-io-mode=mmap "
            "extra-controls=\"controls,vui_timing_info=1,prepend_sps_and_pps_to_idr=1\" "
            "! h265parse config-interval=-1 "
            "! video/x-h265,stream-format=byte-stream,alignment=au "
            "! appsink name=encoded_sink emit-signals=true sync=false max-buffers=3 drop=true";
        GError* parse_error{};
        encoder_pipeline = gst_parse_launch(encoder_description.c_str(), &parse_error);
        if (parse_error || !encoder_pipeline) {
            const std::string detail = parse_error ? parse_error->message : "cannot create encoder";
            if (parse_error) g_error_free(parse_error);
            std::signal(SIGINT, old_int); std::signal(SIGTERM, old_term);
            return Error{ErrorCode::pipeline, detail};
        }
        encoder_source = GST_APP_SRC(gst_bin_get_by_name(GST_BIN(encoder_pipeline), "encoder_source"));
        encoder_sink = GST_APP_SINK(gst_bin_get_by_name(GST_BIN(encoder_pipeline), "encoded_sink"));
        g_signal_connect(encoder_sink, "new-sample", G_CALLBACK(encoded_sample), this);
        if (gst_element_set_state(encoder_pipeline, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
            std::signal(SIGINT, old_int); std::signal(SIGTERM, old_term);
            return Error{ErrorCode::pipeline, "cannot start encoder"};
        }
        // RTSP client lifetimes own software packetization only. The one
        // hardware encoder belongs to this server and survives reconnects.
        const std::string pipeline =
            "( appsrc name=stereo_source is-live=true block=false format=time "
            "max-buffers=3 max-bytes=0 max-time=0 leaky-type=downstream "
            "caps=video/x-h265,stream-format=byte-stream,alignment=au "
            "! h265parse ! rtph265pay name=pay0 pt=96 config-interval=-1 )";
        loop = g_main_loop_new(nullptr, FALSE);
        server = gst_rtsp_server_new();
        g_signal_connect(server, "client-connected", G_CALLBACK(client_connected), nullptr);
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
        std::jthread reader([this, eye_width, eye_height](std::stop_token stop) {
            try {
                read_frames(stop, eye_width, eye_height);
            } catch (const std::exception& error) {
                std::lock_guard lock(mutex);
                worker_error = Error{ErrorCode::input, error.what()};
            }
            reader_done.store(true);
        });
        g_main_loop_run(loop);
        reader.request_stop();
        reader.join();
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

    void read_frames(std::stop_token stop, int eye_width, int eye_height) {
        const bool binning60 = settings.capture_mode == CaptureMode::experimental_linear60_binning ||
                               settings.capture_mode == CaptureMode::linear_binning;
        const bool sensor_signal=settings.main10 && !settings.hdr_display_b &&
                                 settings.capture_mode==CaptureMode::external_trigger;
        // Display and AE target encoding use the same explicitly selected profile.
        AutoExposure exposure(settings.main10 ? (settings.hdr_display_b ?
                              AutoExposure::LumaEncoding::hdr_preview_b : (sensor_signal ?
                              AutoExposure::LumaEncoding::sensor_signal : AutoExposure::LumaEncoding::sensor_linear)) :
                                               AutoExposure::LumaEncoding::hdr_display,
                              binning60 ? AutoExposure::LinearTiming{
                                  sc132gs::configuration::detail::binning_rows_per_second(settings.frame_rate),
                                  2560, settings.frame_rate} :
                                  AutoExposure::LinearTiming{84000, 0, settings.frame_rate,
                                      settings.capture_mode==CaptureMode::external_trigger ?
                                      sc132gs::exposure_budget::reserved_rows(false,settings.frame_rate) : 0});
        if (settings.capture_mode != CaptureMode::external_trigger &&
            exposure.snapshot().hdr_enabled)
            throw std::runtime_error("experimental Linear 120 cannot run in HDR mode");
        exposure.set_target(settings.target_brightness_percent);
        if (!settings.auto_exposure) exposure.disable();
        const bool linear_display = !exposure.snapshot().hdr_enabled;
        if(settings.main10 && !linear_display)
            std::cerr << "hdr_display_profile=" << (settings.hdr_display_b ? "b" : "sensor") << '\n';
        const sc132gs::HdrDisplay hdr_display;
        std::unique_ptr<detail::SensorSignalCalibration> calibration;
        if(sensor_signal) {
            calibration=std::make_unique<detail::SensorSignalCalibration>(!linear_display);
            std::cerr << "sensor_signal black_raw10=" << calibration->black_level() << " gamma=1\n";
        }
        // Binning 60 uses an explicit validated row-clock profile. Other
        // experimental modes still do not expose the legacy AE timing.
        std::unique_ptr<ControlServer> control;
        if (settings.capture_mode == CaptureMode::external_trigger || binning60)
            control = std::make_unique<ControlServer>(exposure);
        std::unique_ptr<detail::Main10Encoder> main10;
        std::vector<std::uint16_t> stereo10;
        if (settings.main10) {
            main10 = std::make_unique<detail::Main10Encoder>(eye_width*2,eye_height,
                                                           settings.frame_rate,settings.bitrate);
            stereo10.resize(static_cast<std::size_t>(eye_width)*2*eye_height);
        }
        // Prepare the consumer before STREAMON: VPU startup must not exhaust
        // the cameras' eight hardware buffers before the first dequeue. The
        // reverse destruction order stops camera DMA before closing the VPU.
        StereoCapture capture(settings.cam0, settings.cam1, settings.downscale,
                              settings.frame_rate, !settings.main10 && exposure.snapshot().hdr_enabled,
                              settings.capture_mode, settings.main10);
        const std::size_t y_bytes = static_cast<std::size_t>(eye_width) * eye_height * 2;
        const std::size_t nv12_bytes = y_bytes * 3 / 2;
        auto interval_start = std::chrono::steady_clock::now();
        std::uint64_t interval_input = 0, interval_submitted = 0;
        std::uint64_t interval_dropped = 0;
        std::int64_t first_input_timestamp_ns = -1;
        std::uint64_t previous_encoded = 0, previous_delivered = 0;
        while (!stop.stop_requested()) {
            FramePair pair = capture.next(stop);
            if (stop.stop_requested()) break;
            if (have_timestamp && pair.cam0_timestamp_ns <= last_timestamp_ns) {
                throw std::runtime_error("camera timestamps are not increasing");
            }
            have_timestamp = true;
            last_timestamp_ns = pair.cam0_timestamp_ns;
            // HDR statistics retain unmodified luma/RAW clipping; its AE
            // calibrates only the median. Linear AE reads calibrated frames.
            if(calibration && linear_display) calibrate_pair(*calibration,pair);
            if (!linear_display)
                exposure.process_hdr_statistics(pair.left_hdr,pair.right_hdr,
                    pair.cam0_sequence,pair.cam0_timestamp_ns);
            else if (settings.main10)
                exposure.process_luma10(pair.left_luma10, pair.right_luma10,
                                       eye_width, eye_height, pair.cam0_sequence,
                                       pair.cam0_timestamp_ns);
            else exposure.process_luma(pair.left_luma, pair.right_luma,
                                  eye_width, eye_height, pair.cam0_sequence,
                                  pair.cam0_timestamp_ns);
            if(calibration && !linear_display) calibrate_pair(*calibration,pair);
            ++input_pairs;
            ++interval_input;
            GstAppSrc* source = GST_APP_SRC(gst_object_ref(encoder_source));
            if (first_input_timestamp_ns < 0)
                first_input_timestamp_ns = pair.cam0_timestamp_ns;
            const auto pts = static_cast<GstClockTime>(
                pair.cam0_timestamp_ns - first_input_timestamp_ns);
            if (settings.main10) {
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
                    if (linear_display)
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
            const auto now = std::chrono::steady_clock::now();
            const auto seconds = std::chrono::duration<double>(now - interval_start).count();
            if (seconds >= 5.0) {
                const auto encoded = encoded_pairs.load();
                const auto delivered = delivered_pairs.load();
                std::cerr << "input_fps=" << interval_input / seconds
                          << " submitted_fps=" << interval_submitted / seconds
                          << " dropped_fps=" << interval_dropped / seconds
                          << " encoded_fps=" << (encoded - previous_encoded) / seconds
                          << " rtsp_fps=" << (delivered - previous_delivered) / seconds
                          << " pairs=" << input_pairs << '\n';
                if (binning60) {
                    const auto ae = exposure.snapshot();
                    std::cerr << "ae=" << ae.enabled << " target_linear_percent=" << ae.target_percent
                              << " measured=" << ae.cam0_percent << ',' << ae.cam1_percent
                              << " exposure_rows=" << ae.exposure_lines << " cap=" << ae.max_exposure_lines
                              << " gain_index=" << ae.analogue_gain_index
                              << " limited=" << ae.brightness_limited << " error=" << ae.last_error << '\n';
                }
                interval_start = now;
                previous_encoded = encoded;
                previous_delivered = delivered;
                interval_input = interval_submitted = interval_dropped = 0;
            }
        }
    }
};

StereoRtspServer::StereoRtspServer(Settings settings)
    : impl_(std::make_unique<Impl>(std::move(settings))) {}
StereoRtspServer::~StereoRtspServer() = default;
StereoRtspServer::StereoRtspServer(StereoRtspServer&&) noexcept = default;
StereoRtspServer& StereoRtspServer::operator=(StereoRtspServer&&) noexcept = default;
std::variant<std::monostate, Error> StereoRtspServer::run() { return impl_->run(); }

} // namespace stereo_rtsp
