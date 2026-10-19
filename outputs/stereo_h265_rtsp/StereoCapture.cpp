#include "StereoCapture.hpp"
#include "sc132gs-hdr-ae-policy.hpp"
#include "BayerLuma.hpp"
#include "CaptureProgress.hpp"
#include "CaptureError.hpp"
#include "StereoPendingFrames.hpp"
#include "KernelSyncStatus.hpp"
#include "CaptureTrace.hpp"
#include "MoveHandoff.hpp"

#include <linux/videodev2.h>

#include <array>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <cstdlib>
#include <fcntl.h>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <optional>
#include <poll.h>
#include <stdexcept>
#include <string>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <utility>
#include <vector>
#include <thread>

namespace stereo_rtsp {
namespace {

constexpr int kWidth = 1088;
constexpr int kHeight = 1280;
constexpr auto kPixelFormat = v4l2_fourcc('p', 'R', 'A', 'A');
constexpr auto kBufferType = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
constexpr std::int64_t kMaxDeltaNs = 500'000;

bool is_binning(CaptureMode mode) noexcept {
    return mode == CaptureMode::experimental_linear120_binning ||
           mode == CaptureMode::experimental_linear60_binning || mode == CaptureMode::linear_binning;
}

void enable_trigger_60fps(const char* path) {
    const int fd = ::open(path, O_WRONLY | O_CLOEXEC);
    if (fd < 0)
        throw std::runtime_error(std::string("open ") + path + ": " +
                                 std::strerror(errno));
    const ssize_t written = ::write(fd, "1\n", 2);
    const int write_errno = errno;
    const int close_result = ::close(fd);
    if (written != 2) {
        throw std::runtime_error(std::string("enable 60 FPS ") + path + ": " +
                                 std::strerror(written < 0 ? write_errno : EIO));
    }
    if (close_result < 0)
        throw std::runtime_error(std::string("close ") + path + ": " +
                                 std::strerror(errno));
}

int xioctl(int fd, unsigned long request, void* data) {
    int result;
    do result = ::ioctl(fd, request, data);
    while (result < 0 && errno == EINTR);
    return result;
}

void checked_ioctl(int fd, unsigned long request, void* data,
                   const std::string& operation) {
    if (xioctl(fd, request, data) < 0) {
        throw std::runtime_error(operation + ": " + std::strerror(errno));
    }
}

struct Frame {
    std::uint32_t sequence{};
    std::int64_t timestamp_ns{};
    std::vector<std::uint8_t> luma;
    std::vector<std::uint16_t> luma10;
    sc132gs::hdr_ae::Statistics hdr;
    sc132gs::linear_ae::HighlightStatistics highlights;
};

class Device final {
public:
    Device(std::string path, int scale, bool hdr_display, CaptureMode mode, bool tenbit,
           detail::CaptureTrace& trace, unsigned eye)
        : path_(std::move(path)), scale_(scale),
          width_(is_binning(mode) ? 544 : kWidth),
          height_(is_binning(mode) ? 640 : kHeight),
          converter_(width_, height_, hdr_display), tenbit_(tenbit), trace_(trace), eye_(eye) {
        fd_ = ::open(path_.c_str(), O_RDWR | O_NONBLOCK | O_CLOEXEC);
        if (fd_ < 0) throw std::runtime_error("open " + path_ + ": " + std::strerror(errno));
        try {
            prepare();
        } catch (...) {
            for (auto [address, length] : mappings_) ::munmap(address, length);
            ::close(fd_);
            fd_ = -1;
            throw;
        }
    }

    ~Device() {
        if (streaming_) {
            auto type = kBufferType;
            (void)xioctl(fd_, VIDIOC_STREAMOFF, &type);
        }
        for (auto [address, length] : mappings_) ::munmap(address, length);
        if (fd_ >= 0) ::close(fd_);
    }
    Device(const Device&) = delete;
    Device& operator=(const Device&) = delete;

    int fd() const { return fd_; }

    void start() {
        for (std::uint32_t index = 0; index < mappings_.size(); ++index) {
            requeue(index);
        }
        auto type = kBufferType;
        checked_ioctl(fd_, VIDIOC_STREAMON, &type, "VIDIOC_STREAMON " + path_);
        streaming_ = true;
    }

    std::optional<Frame> dequeue(bool acquiring = false, std::uint64_t session = 0) {
        v4l2_buffer buffer{};
        v4l2_plane plane{};
        buffer.type = kBufferType;
        buffer.memory = V4L2_MEMORY_MMAP;
        buffer.m.planes = &plane;
        buffer.length = 1;
        const auto dequeue_begin = detail::capture_now_ns();
        if (xioctl(fd_, VIDIOC_DQBUF, &buffer) < 0) {
            if (errno == EAGAIN) return std::nullopt;
            record(detail::CaptureOperation::dequeue, buffer.index, 0, dequeue_begin,
                   detail::capture_now_ns(), 0, 0, errno);
            throw std::runtime_error("VIDIOC_DQBUF " + path_ + ": " + std::strerror(errno));
        }
        ++application_held_;
        lease_begin_ns_ = detail::capture_now_ns();
        lease_sequence_ = buffer.sequence;
        record(detail::CaptureOperation::dequeue, buffer.index, buffer.sequence, dequeue_begin,
               detail::capture_now_ns(), plane.bytesused, buffer.flags);
        if (buffer.index >= mappings_.size())
            throw detail::CaptureError(detail::CaptureErrorCode::invalid_buffer);
        BufferLease lease(*this, buffer.index);
        if (buffer.flags & V4L2_BUF_FLAG_ERROR) {
            snapshot();
            lease.release();
            if (acquiring && buffer.index < mappings_.size()) {
                auto reader = sync::StatusReader::open("/sys/bus/platform/devices/acb3000.camss/fsync_control");
                if (auto* source = std::get_if<sync::StatusReader>(&reader)) {
                    auto state = source->read();
                    if (auto* status = std::get_if<sync::Status>(&state);
                        status && status->mode == 2 && status->running && status->driver_error == 0 &&
                        status->session == session) {
                        const auto node=std::filesystem::canonical(path_).string();
                        for (unsigned eye=0; eye<2; ++eye)
                            if (node=="/dev/video"+std::to_string(status->video_nodes[eye]) &&
                                status->is_startup_buffer(status->video_nodes[eye], buffer.sequence, session))
                                return std::nullopt; // Only the diagnosed startup ERROR prefix.
                    }
                }
            }
            throw detail::CaptureError(detail::CaptureErrorCode::invalid_buffer);
        }
        if (buffer.index >= mappings_.size() || plane.bytesused < static_cast<unsigned>(stride_ * height_)) {
            throw std::runtime_error("short RAW10 frame from " + path_);
        }
        Frame frame;
        {
            frame.sequence = buffer.sequence;
            frame.timestamp_ns =
                static_cast<std::int64_t>(buffer.timestamp.tv_sec) * 1'000'000'000 +
                static_cast<std::int64_t>(buffer.timestamp.tv_usec) * 1'000;
            const int output_width = width_ / scale_;
            const int output_height = height_ / scale_;
            const auto* raw = static_cast<const std::uint8_t*>(
                mappings_[buffer.index].first);
            const auto unpack_begin = detail::capture_now_ns();
            converter_.unpack(std::span<const std::uint8_t>(raw, plane.bytesused), stride_);
            record(detail::CaptureOperation::unpack, buffer.index, buffer.sequence,
                   unpack_begin, detail::capture_now_ns());
            // No operation below reads raw/the MMAP mapping. Return it before
            // metering, demosaic, output allocation or any downstream work.
            lease.release();
            const auto statistics_begin = detail::capture_now_ns();
            const auto meter = converter_.statistics();
            frame.hdr = sc132gs::hdr_ae::summarize(meter.histogram);
            if (tenbit_) frame.highlights = {meter.sample_count, meter.near_saturated_count, true};
            record(detail::CaptureOperation::statistics, buffer.index, buffer.sequence,
                   statistics_begin, detail::capture_now_ns());
            const auto render_begin = detail::capture_now_ns();
            if (tenbit_) {
                frame.luma10.resize(output_width * output_height);
                converter_.render10(frame.luma10, scale_);
                frame.hdr.luma_median=sc132gs::hdr_ae::median_luma10(frame.luma10,output_width,output_height);
            } else {
                frame.luma.resize(output_width * output_height);
                converter_.render(frame.luma, scale_);
            }
            record(detail::CaptureOperation::render, buffer.index, buffer.sequence,
                   render_begin, detail::capture_now_ns());
        }
        return frame;
    }

    void snapshot() {
        for (std::uint32_t index = 0; index < mappings_.size(); ++index) {
            v4l2_buffer buffer{}; v4l2_plane plane{};
            buffer.type = kBufferType; buffer.memory = V4L2_MEMORY_MMAP;
            buffer.index = index; buffer.m.planes = &plane; buffer.length = 1;
            const auto begin = detail::capture_now_ns();
            const int result = xioctl(fd_, VIDIOC_QUERYBUF, &buffer);
            const int error = result < 0 ? errno : 0;
            record(detail::CaptureOperation::buffer_snapshot, index, buffer.sequence,
                   begin, detail::capture_now_ns(), plane.bytesused, buffer.flags, error);
        }
    }

private:
    class BufferLease final {
    public:
        BufferLease(Device& device, unsigned index) noexcept : device_(device), index_(index) {}
        ~BufferLease() { if (active_) { try { release(); } catch (...) {} } }
        BufferLease(const BufferLease&) = delete;
        BufferLease& operator=(const BufferLease&) = delete;
        void release() { active_ = false; device_.requeue(index_); }
    private:
        Device& device_; unsigned index_; bool active_{true};
    };
    void record(detail::CaptureOperation operation, unsigned index, unsigned sequence,
                std::uint64_t begin, std::uint64_t end, std::uint64_t value = 0,
                unsigned flags = 0, int error = 0) {
        trace_.record({operation, eye_, index, sequence, flags, application_held_, begin, end, value, error});
    }
    void prepare() {
        v4l2_format format{};
        format.type = kBufferType;
        format.fmt.pix_mp.width = width_;
        format.fmt.pix_mp.height = height_;
        format.fmt.pix_mp.pixelformat = kPixelFormat;
        format.fmt.pix_mp.field = V4L2_FIELD_NONE;
        checked_ioctl(fd_, VIDIOC_S_FMT, &format, "VIDIOC_S_FMT " + path_);
        if (format.fmt.pix_mp.width != static_cast<unsigned>(width_) ||
            format.fmt.pix_mp.height != static_cast<unsigned>(height_) ||
            format.fmt.pix_mp.pixelformat != kPixelFormat ||
            format.fmt.pix_mp.num_planes != 1 ||
            format.fmt.pix_mp.plane_fmt[0].bytesperline < static_cast<unsigned>(width_ * 5 / 4) ||
            format.fmt.pix_mp.plane_fmt[0].sizeimage <
                format.fmt.pix_mp.plane_fmt[0].bytesperline * height_) {
            throw std::runtime_error(path_ + " rejected expected RAW10 geometry");
        }
        stride_ = format.fmt.pix_mp.plane_fmt[0].bytesperline;
        v4l2_requestbuffers request{};
        request.count = 8;
        request.type = kBufferType;
        request.memory = V4L2_MEMORY_MMAP;
        checked_ioctl(fd_, VIDIOC_REQBUFS, &request, "VIDIOC_REQBUFS " + path_);
        const auto now = detail::capture_now_ns();
        record(detail::CaptureOperation::buffers, 8, 0, now, now, request.count);
        std::cerr << "capture_buffers eye=" << eye_ << " requested=8 actual=" << request.count << '\n';
        if (request.count < 4) throw std::runtime_error("too few V4L2 buffers: " + path_);
        mappings_.reserve(request.count);
        for (std::uint32_t index = 0; index < request.count; ++index) {
            v4l2_buffer buffer{};
            v4l2_plane planes[VIDEO_MAX_PLANES]{};
            buffer.type = kBufferType;
            buffer.memory = V4L2_MEMORY_MMAP;
            buffer.index = index;
            buffer.m.planes = planes;
            buffer.length = VIDEO_MAX_PLANES;
            checked_ioctl(fd_, VIDIOC_QUERYBUF, &buffer, "VIDIOC_QUERYBUF " + path_);
            void* address = ::mmap(nullptr, planes[0].length, PROT_READ | PROT_WRITE,
                                   MAP_SHARED, fd_, planes[0].m.mem_offset);
            if (address == MAP_FAILED)
                throw std::runtime_error("mmap " + path_ + ": " + std::strerror(errno));
            mappings_.emplace_back(address, planes[0].length);
        }
    }

    void requeue(std::uint32_t index) {
        v4l2_buffer buffer{};
        v4l2_plane plane{};
        buffer.type = kBufferType;
        buffer.memory = V4L2_MEMORY_MMAP;
        buffer.index = index;
        buffer.m.planes = &plane;
        buffer.length = 1;
        const auto begin = detail::capture_now_ns();
        const int result = xioctl(fd_, VIDIOC_QBUF, &buffer);
        const int error = result < 0 ? errno : 0;
        const auto end = detail::capture_now_ns();
        if (result == 0 && application_held_) {
            --application_held_;
            record(detail::CaptureOperation::buffer_hold, index, lease_sequence_, lease_begin_ns_, end);
        }
        record(detail::CaptureOperation::requeue, index, 0, begin,
               end, 0, buffer.flags, error);
        if (result < 0) throw std::runtime_error("VIDIOC_QBUF " + path_ + ": " + std::strerror(error));
    }

    std::string path_;
    int scale_;
    int width_;
    int height_;
    int stride_{};
    detail::BayerLuma converter_;
    bool tenbit_;
    int fd_{-1};
    bool streaming_{};
    std::vector<std::pair<void*, std::size_t>> mappings_;
    detail::CaptureTrace& trace_;
    unsigned eye_{}, application_held_{};
    std::uint64_t lease_begin_ns_{};
    unsigned lease_sequence_{};
};

} // namespace

struct StereoCapture::Impl {
    Impl(const std::string& cam0, const std::string& cam1, int scale,
         int frame_rate, bool hdr_display, CaptureMode mode, bool tenbit)
        : left(cam0, scale, hdr_display, mode, tenbit, trace, 0),
          right(cam1, scale, hdr_display, mode, tenbit, trace, 1) {
        left.start();
        right.start();
        if (mode != CaptureMode::external_trigger) {
            // Presentation pairing only: permit half the requested frame period
            // plus 0.5 ms receiver jitter. This does not imply exposure sync.
            max_delta_ns = 1'000'000'000LL / frame_rate / 2 + 500'000;
            progress.set_startup_timeout(std::chrono::seconds(15));
            std::cerr << "Both " << frame_rate << " FPS receivers armed; "
                      << (is_binning(mode) ?
                          "binning configured by experiment driver\n" :
                          "waiting for experimental sensor profile\n");
        } else if (frame_rate > 30) {
            enable_trigger_60fps("/sys/bus/i2c/devices/18-0032/trigger_60fps");
            enable_trigger_60fps("/sys/bus/i2c/devices/16-0030/trigger_60fps");
            warmup_until = std::chrono::steady_clock::now() +
                           std::chrono::seconds(1);
            // Receiver completion timing can offset timestamps at any high rate,
            // including 60 FPS. Presentation pairing is not exposure alignment.
            max_delta_ns = 1'000'000'000LL / frame_rate / 2 + 500'000;
            std::cerr << "High-rate timestamp pairing; max_delta_ns="
                      << max_delta_ns << "; exposure synchronization unverified\n";
        }
        std::ifstream kernel_mode("/sys/module/qcom_camss/parameters/fsync_mode");
        unsigned sync_mode = 0;
        if (kernel_mode >> sync_mode && sync_mode == 2) {
            auto reader = sync::StatusReader::open("/sys/bus/platform/devices/acb3000.camss/fsync_control");
            if (std::holds_alternative<sync::Error>(reader))
                throw detail::CaptureError(detail::CaptureErrorCode::invalid_sync_state);
            auto state = std::get<sync::StatusReader>(reader).read();
            if (std::holds_alternative<sync::Error>(state))
                throw detail::CaptureError(detail::CaptureErrorCode::invalid_sync_state);
            const auto& status = std::get<sync::Status>(state);
            if (status.mode != 2 || !status.running || status.driver_error)
                throw detail::CaptureError(detail::CaptureErrorCode::invalid_sync_state);
            if (mode != CaptureMode::external_trigger || frame_rate != 30)
                throw detail::CaptureError(detail::CaptureErrorCode::invalid_sync_state);
            max_delta_ns = 0;
            kernel_synchronized = true;
            kernel_session = status.session;
            const char* source_name = "fsync_host_reference";
            if (status.source == sync::TimestampSource::exposure_midpoint_estimate)
                source_name = "exposure_midpoint_estimate";
            else if (status.source == sync::TimestampSource::exposure_start_estimate)
                source_name = "exposure_start_estimate";
            std::cerr << "Kernel FSYNC exact pairing: timestamp_offset_ns=" << status.timestamp_offset_ns
                      << " source=" << source_name << '\n';
        }
        pending.set_maximum_delta(max_delta_ns);
        std::cerr << "Capture ready: fps=" << frame_rate << '\n';
    }

    // Declared before devices: diagnostic storage outlives both ioctl owners.
    detail::CaptureTrace trace;
    Device left;
    Device right;
    detail::StereoPendingFrames<Frame> pending{kMaxDeltaNs};
    detail::CaptureProgress progress{std::chrono::steady_clock::now()};
    std::array<bool, 2> backlog_reported{};
    std::array<bool, 2> discard_reported{};
    bool have_pair{};
    bool kernel_synchronized{};
    std::uint64_t kernel_session{};
    std::uint32_t last0{}, last1{};
    std::int64_t last_timestamp_ns{};
    std::array<std::uint64_t, 2> dequeued{};
    std::int64_t max_delta_ns{kMaxDeltaNs};
    std::chrono::steady_clock::time_point warmup_until{};
    detail::MoveHandoff<FramePair> handoff;
    std::stop_source cancellation;
    std::thread worker;
    std::uint64_t last_delivery_ns{}; // Consumer thread only.
    const std::uint64_t trace_id{detail::capture_now_ns()};
    bool trace_dumped{}; // Producer, then destructor after join.
    std::uint64_t last_timing_report_ns{};

    ~Impl() {
        cancel();
        if (worker.joinable()) worker.join();
        if (!trace_dumped) { left.snapshot(); right.snapshot(); }
        dump_trace("stop");
    }
    void cancel() {
        cancellation.request_stop();
        handoff.close();
    }
    void dump_trace(const char* reason) noexcept {
        if (trace_dumped) return;
        trace_dumped = true;
        try {
            const char* directory = std::getenv("SC132GS_CAPTURE_TRACE_DIR");
            const auto path = std::string(directory ? directory : "/tmp") +
                "/sc132gs-capture-" + std::to_string(::getpid()) + "-" + std::to_string(trace_id) + ".jsonl";
            if (trace.dump(path)) {
                std::ifstream state("/sys/bus/platform/devices/acb3000.camss/fsync_control");
                std::ofstream state_copy(path + ".sync");
                if (state) state_copy << state.rdbuf();
                std::cerr << "capture_trace reason=" << reason << " path=" << path << '\n';
            } else std::cerr << "capture_trace write_failed path=" << path << '\n';
        } catch (...) {}
    }
    void start() {
        worker = std::thread([this] {
            try {
                while (!cancellation.stop_requested()) {
                    auto pair = capture_next(cancellation.get_token());
                    if (cancellation.stop_requested()) break;
                    const auto begin = detail::capture_now_ns();
                    if (!handoff.put(std::move(pair))) break;
                    trace.record({detail::CaptureOperation::handoff_wait, 2, 0, 0, 0, 0,
                                  begin, detail::capture_now_ns()});
                    const auto now = detail::capture_now_ns();
                    if (now - last_timing_report_ns >= 5'000'000'000ULL) {
                        last_timing_report_ns = now;
                        const auto h0 = trace.timing(detail::CaptureOperation::buffer_hold, 0);
                        const auto h1 = trace.timing(detail::CaptureOperation::buffer_hold, 1);
                        const auto wait = trace.timing(detail::CaptureOperation::handoff_wait);
                        std::cerr << "capture_timing held_mean_ms0=" << (h0.count ? h0.total_ns / 1e6 / h0.count : 0)
                                  << " held_mean_ms1=" << (h1.count ? h1.total_ns / 1e6 / h1.count : 0)
                                  << " held_max_ms0=" << h0.max_ns / 1e6 << " held_max_ms1=" << h1.max_ns / 1e6
                                  << " handoff_max_ms=" << wait.max_ns / 1e6 << '\n';
                    }
                }
                handoff.close();
            } catch (...) {
                const auto error = std::current_exception();
                // Snapshot both driver queues before teardown or a new session.
                left.snapshot(); right.snapshot();
                const auto now = detail::capture_now_ns();
                trace.record({detail::CaptureOperation::fault, 2, 0, 0, 0, 0, now, now});
                dump_trace("fault");
                handoff.fail(error);
            }
        });
    }
    FramePair next(std::stop_token stop) {
        std::stop_callback wake(stop, [this] { cancel(); });
        const auto begin = detail::capture_now_ns();
        if (last_delivery_ns)
            trace.record({detail::CaptureOperation::consumer_gap, 2, 0, 0, 0, 0,
                          last_delivery_ns, begin});
        auto pair = handoff.take();
        last_delivery_ns = detail::capture_now_ns();
        if (!pair) return {};
        return std::move(*pair);
    }

    enum class HealthReason { backlog, discard, timeout };

    void report_health(HealthReason reason) const {
        const auto now = std::chrono::steady_clock::now();
        const auto age_ms = [&](unsigned eye) -> std::int64_t {
            return progress.age_ms(eye, now);
        };
        const char* label = reason == HealthReason::backlog ? "backlog" :
                            reason == HealthReason::discard ? "discard" : "timeout";
        std::cerr << "capture_health reason=" << label
                  << " queue0=" << pending.depth(0) << " queue1=" << pending.depth(1)
                  << " dequeued0=" << dequeued[0] << " dequeued1=" << dequeued[1]
                  << " dequeue_age_ms0=" << age_ms(0) << " dequeue_age_ms1=" << age_ms(1)
                  << " last_paired0=" << last0 << " last_paired1=" << last1
                  << " head_ns0=" << pending.head_timestamp(0)
                  << " head_ns1=" << pending.head_timestamp(1)
                  << " capacity_discarded0=" << pending.capacity_discarded(0)
                  << " capacity_discarded1=" << pending.capacity_discarded(1)
                  << " alignment_discarded0=" << pending.alignment_discarded(0)
                  << " alignment_discarded1=" << pending.alignment_discarded(1)
                  << '\n';
    }

    void drain(Device& device, unsigned eye) {
        // Alternate between cameras even when one V4L2 fd stays readable.
        for (int read = 0; read < 2; ++read) {
            auto frame = device.dequeue(kernel_synchronized && !have_pair, kernel_session);
            if (!frame) break;
            ++dequeued[eye];
            progress.received(eye, std::chrono::steady_clock::now());
            const auto result = pending.enqueue(eye, std::move(*frame));
            if (result == detail::StereoPendingFrames<Frame>::EnqueueResult::overflow)
                throw detail::CaptureError(detail::CaptureErrorCode::frame_overflow,
                                           static_cast<std::uint8_t>(1u << eye));
            if (pending.depth(eye) >= 8 && !backlog_reported[eye]) {
                report_health(HealthReason::backlog);
                backlog_reported[eye] = true;
            }
            if (result == detail::StereoPendingFrames<Frame>::EnqueueResult::oldest_discarded &&
                !discard_reported[eye]) {
                report_health(HealthReason::discard);
                discard_reported[eye] = true;
            }
        }
    }

    FramePair capture_next(std::stop_token stop) {
        while (!stop.stop_requested()) {
            for (;;) {
                auto result = pending.take();
                if (const auto* error = std::get_if<detail::StereoPendingFrames<Frame>::PairingError>(&result))
                    throw detail::CaptureError(detail::CaptureErrorCode::timestamp_mismatch,
                                               3, error->delta_ns);
                auto* pair = std::get_if<detail::StereoPendingFrames<Frame>::Pair>(&result);
                if (!pair) break;
                Frame one = std::move((*pair)[0]);
                Frame two = std::move((*pair)[1]);
                for (unsigned eye = 0; eye < 2; ++eye)
                    if (pending.depth(eye) < 8) {
                        backlog_reported[eye] = false;
                        discard_reported[eye] = false;
                    }
                if (std::chrono::steady_clock::now() < warmup_until) {
                    have_pair = false;
                    continue;
                }
                if (have_pair && (one.sequence <= last0 ||
                                  two.sequence <= last1)) {
                    throw std::runtime_error(
                        "capture sequence regressed cam0=" + std::to_string(last0) +
                        "->" + std::to_string(one.sequence) + " cam1=" +
                        std::to_string(last1) + "->" + std::to_string(two.sequence));
                }
                if (have_pair && (one.sequence != last0 + 1 ||
                                  two.sequence != last1 + 1)) {
                    if (kernel_synchronized)
                        throw detail::CaptureError(detail::CaptureErrorCode::invalid_buffer, 3);
                    std::cerr << "capture frame gap cam0=" << last0 << "->"
                              << one.sequence << " cam1=" << last1 << "->"
                              << two.sequence << "; continuing\n";
                }
                have_pair = true;
                if (kernel_synchronized && one.timestamp_ns <= last_timestamp_ns)
                    throw detail::CaptureError(detail::CaptureErrorCode::invalid_buffer, 3);
                last_timestamp_ns = one.timestamp_ns;
                if (kernel_synchronized) pending.require_contiguous_pairs();
                progress.paired();
                last0 = one.sequence;
                last1 = two.sequence;
                const auto now = detail::capture_now_ns();
                trace.record({detail::CaptureOperation::pair, 2, last1, last0, 0, 0, now, now});
                return FramePair{one.sequence, two.sequence,
                                 one.timestamp_ns, two.timestamp_ns,
                                 std::move(one.luma), std::move(two.luma),
                                 std::move(one.luma10), std::move(two.luma10),one.hdr,two.hdr,
                                 one.highlights,two.highlights};
            }
            pollfd descriptors[2] = {{left.fd(), POLLIN, 0},
                                     {right.fd(), POLLIN, 0}};
            const int ready = ::poll(descriptors, 2, 200);
            if (ready < 0) {
                if (errno == EINTR) continue;
                throw std::runtime_error(std::string("poll cameras: ") +
                                         std::strerror(errno));
            }
            if (stop.stop_requested()) break;
            if ((descriptors[0].revents | descriptors[1].revents) &
                (POLLERR | POLLHUP | POLLNVAL))
                throw std::runtime_error("V4L2 camera poll error");
            if (descriptors[0].revents & POLLIN) drain(left, 0);
            if (descriptors[1].revents & POLLIN) drain(right, 1);
            // Drain available frames first: a slow consumer may have valid
            // hardware buffers waiting, rather than a stalled input.
            const auto stalled = progress.stalled_eyes(std::chrono::steady_clock::now());
            if (stalled) {
                report_health(HealthReason::timeout);
                throw detail::CaptureError(detail::CaptureErrorCode::frame_timeout, stalled);
            }
        }
        return {};
    }
};

StereoCapture::StereoCapture(const std::string& cam0, const std::string& cam1,
                             int scale, int frame_rate, bool hdr_display, CaptureMode mode, bool tenbit)
    : impl_(std::make_unique<Impl>(cam0, cam1, scale, frame_rate, hdr_display, mode, tenbit)) { impl_->start(); }
StereoCapture::~StereoCapture() = default;
StereoCapture::StereoCapture(StereoCapture&&) noexcept = default;
StereoCapture& StereoCapture::operator=(StereoCapture&&) noexcept = default;
FramePair StereoCapture::next(std::stop_token stop) { return impl_->next(stop); }

} // namespace stereo_rtsp
