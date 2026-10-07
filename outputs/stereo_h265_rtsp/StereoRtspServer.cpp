#include "StereoRtspServer.hpp"
#include "StereoCapture.hpp"
#include "StereoComposeNV12.hpp"
#include "sc132gs-ae.hpp"
#include "sc132gs-control-server.hpp"

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
    std::chrono::steady_clock::time_point next_session_cleanup{};

    ~Impl() {
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

    static void release_object(gpointer object) {
        gst_object_unref(object);
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
        gst_element_send_event(GST_ELEMENT(self.encoder_sink),
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
            gst_rtsp_session_pool_cleanup(pool);
            gst_object_unref(pool);
            self.next_session_cleanup = now + std::chrono::seconds(1);
        }
        return G_SOURCE_CONTINUE;
    }

    std::variant<std::monostate, Error> run() {
        if ((settings.downscale != 1 && settings.downscale != 2 &&
             settings.downscale != 4) || settings.frame_rate < 1 ||
            settings.frame_rate > 60 || settings.mount.empty() ||
            settings.mount.front() != '/' ||
            settings.target_brightness_percent < 1 ||
            settings.target_brightness_percent > 90) {
            return Error{ErrorCode::invalid_config,
                         "downscale must be 1, 2 or 4; fps 1..60; brightness 1..90; mount starts with /"};
        }
        stop_signal = 0;
        const auto old_int = std::signal(SIGINT, signal_stop);
        const auto old_term = std::signal(SIGTERM, signal_stop);
        gst_init(nullptr, nullptr);
        const int eye_width = static_cast<int>(kInputWidth) / settings.downscale;
        const int eye_height = static_cast<int>(kInputEyeHeight) / settings.downscale;
        const int output_width = eye_width * 2;
        const std::string encoder_description =
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
                  << eye_height << '@' << settings.frame_rate << ")\n";
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
        std::signal(SIGINT, old_int);
        std::signal(SIGTERM, old_term);
        std::cerr << "input_pairs=" << input_pairs
                  << " submitted_pairs=" << submitted_pairs
                  << " dropped_pairs=" << dropped_pairs << '\n';
        if (worker_error) return *worker_error;
        return std::monostate{};
    }

    void read_frames(std::stop_token stop, int eye_width, int eye_height) {
        AutoExposure exposure(AutoExposure::LumaEncoding::hdr_display);
        exposure.set_target(settings.target_brightness_percent);
        if (!settings.auto_exposure) exposure.disable();
        ControlServer control(exposure);
        StereoCapture capture(settings.cam0, settings.cam1, settings.downscale,
                              settings.frame_rate, exposure.snapshot().hdr_enabled);
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
            exposure.process_luma(pair.left_luma, pair.right_luma,
                                  eye_width, eye_height, pair.cam0_sequence,
                                  pair.cam0_timestamp_ns);
            ++input_pairs;
            ++interval_input;
            GstAppSrc* source = GST_APP_SRC(gst_object_ref(encoder_source));
            if (first_input_timestamp_ns < 0)
                first_input_timestamp_ns = pair.cam0_timestamp_ns;
            const auto pts = static_cast<GstClockTime>(
                pair.cam0_timestamp_ns - first_input_timestamp_ns);
            if (source) {
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
