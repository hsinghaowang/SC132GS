#include "StereoCapture.hpp"
#include "BayerLuma.hpp"

#include <linux/videodev2.h>

#include <array>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <deque>
#include <fcntl.h>
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

namespace stereo_rtsp {
namespace {

constexpr int kWidth = 1088;
constexpr int kHeight = 1280;
constexpr int kRawBytes = kWidth * kHeight * 5 / 4;
constexpr int kStride = kWidth * 5 / 4;
constexpr auto kPixelFormat = v4l2_fourcc('p', 'R', 'A', 'A');
constexpr auto kBufferType = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
constexpr std::int64_t kMaxDeltaNs = 500'000;

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
};

class Device final {
public:
    Device(std::string path, int scale, bool hdr_display, bool tenbit)
        : path_(std::move(path)), scale_(scale), converter_(kWidth, kHeight, hdr_display), tenbit_(tenbit) {
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
            v4l2_buffer buffer{};
            v4l2_plane plane{};
            buffer.type = kBufferType;
            buffer.memory = V4L2_MEMORY_MMAP;
            buffer.index = index;
            buffer.m.planes = &plane;
            buffer.length = 1;
            checked_ioctl(fd_, VIDIOC_QBUF, &buffer, "VIDIOC_QBUF " + path_);
        }
        auto type = kBufferType;
        checked_ioctl(fd_, VIDIOC_STREAMON, &type, "VIDIOC_STREAMON " + path_);
        streaming_ = true;
    }

    std::optional<Frame> dequeue() {
        v4l2_buffer buffer{};
        v4l2_plane plane{};
        buffer.type = kBufferType;
        buffer.memory = V4L2_MEMORY_MMAP;
        buffer.m.planes = &plane;
        buffer.length = 1;
        if (xioctl(fd_, VIDIOC_DQBUF, &buffer) < 0) {
            if (errno == EAGAIN) return std::nullopt;
            throw std::runtime_error("VIDIOC_DQBUF " + path_ + ": " + std::strerror(errno));
        }
        if (buffer.index >= mappings_.size() || plane.bytesused < kRawBytes) {
            requeue(buffer.index);
            throw std::runtime_error("short RAW10 frame from " + path_);
        }
        Frame frame;
        try {
            frame.sequence = buffer.sequence;
            frame.timestamp_ns =
                static_cast<std::int64_t>(buffer.timestamp.tv_sec) * 1'000'000'000 +
                static_cast<std::int64_t>(buffer.timestamp.tv_usec) * 1'000;
            const int output_width = kWidth / scale_;
            const int output_height = kHeight / scale_;
            const auto* raw = static_cast<const std::uint8_t*>(
                mappings_[buffer.index].first);
            if (tenbit_) {
                frame.luma10.resize(output_width * output_height);
                converter_.convert10(std::span<const std::uint8_t>(raw, plane.bytesused),
                                     kStride, frame.luma10, scale_);
            } else {
                frame.luma.resize(output_width * output_height);
                converter_.convert(std::span<const std::uint8_t>(raw, plane.bytesused),
                                   kStride, frame.luma, scale_);
            }
        } catch (...) {
            requeue(buffer.index);
            throw;
        }
        requeue(buffer.index);
        return frame;
    }

private:
    void prepare() {
        v4l2_format format{};
        format.type = kBufferType;
        format.fmt.pix_mp.width = kWidth;
        format.fmt.pix_mp.height = kHeight;
        format.fmt.pix_mp.pixelformat = kPixelFormat;
        format.fmt.pix_mp.field = V4L2_FIELD_NONE;
        checked_ioctl(fd_, VIDIOC_S_FMT, &format, "VIDIOC_S_FMT " + path_);
        if (format.fmt.pix_mp.width != kWidth ||
            format.fmt.pix_mp.height != kHeight ||
            format.fmt.pix_mp.pixelformat != kPixelFormat ||
            format.fmt.pix_mp.num_planes != 1 ||
            format.fmt.pix_mp.plane_fmt[0].bytesperline != kStride ||
            format.fmt.pix_mp.plane_fmt[0].sizeimage < kRawBytes) {
            throw std::runtime_error(path_ + " rejected 1088x1280 pRAA");
        }
        v4l2_requestbuffers request{};
        request.count = 8;
        request.type = kBufferType;
        request.memory = V4L2_MEMORY_MMAP;
        checked_ioctl(fd_, VIDIOC_REQBUFS, &request, "VIDIOC_REQBUFS " + path_);
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
        checked_ioctl(fd_, VIDIOC_QBUF, &buffer, "VIDIOC_QBUF " + path_);
    }

    std::string path_;
    int scale_;
    detail::BayerLuma converter_;
    bool tenbit_;
    int fd_{-1};
    bool streaming_{};
    std::vector<std::pair<void*, std::size_t>> mappings_;
};

} // namespace

struct StereoCapture::Impl {
    Impl(const std::string& cam0, const std::string& cam1, int scale,
         int frame_rate, bool hdr_display, bool tenbit)
        : left(cam0, scale, hdr_display, tenbit), right(cam1, scale, hdr_display, tenbit) {
        left.start();
        right.start();
        if (frame_rate == 60) {
            // Presentation pairing tolerates receiver completion jitter.
            // This does not establish physical exposure synchronization.
            max_delta_ns = 1'000'000'000LL / frame_rate / 2 + 500'000;
            enable_trigger_60fps("/sys/bus/i2c/devices/18-0032/trigger_60fps");
            enable_trigger_60fps("/sys/bus/i2c/devices/16-0030/trigger_60fps");
            warmup_until = std::chrono::steady_clock::now() +
                           std::chrono::seconds(1);
        }
    }

    Device left;
    Device right;
    std::deque<Frame> queue0;
    std::deque<Frame> queue1;
    std::int64_t max_delta_ns{kMaxDeltaNs};
    bool have_pair{};
    std::uint32_t last0{}, last1{};
    std::chrono::steady_clock::time_point warmup_until{};

    void drain(Device& device, std::deque<Frame>& queue) {
        // Alternate between cameras even when one V4L2 fd stays readable.
        for (int read = 0; read < 2; ++read) {
            auto frame = device.dequeue();
            if (!frame) break;
            queue.push_back(std::move(*frame));
            if (queue.size() > 32)
                throw std::runtime_error("camera queue overran 32 frames");
        }
    }

    FramePair next(std::stop_token stop) {
        int idle_ticks = 0;
        int unmatched = 0;
        while (!stop.stop_requested()) {
            while (!queue0.empty() && !queue1.empty()) {
                const auto delta = queue1.front().timestamp_ns -
                                   queue0.front().timestamp_ns;
                if (delta > max_delta_ns || delta < -max_delta_ns) {
                    if (++unmatched > 300)
                        throw std::runtime_error(
                            "cannot pair camera timestamps; latest delta_ns=" +
                            std::to_string(delta));
                    if (delta > 0) queue0.pop_front();
                    else queue1.pop_front();
                    continue;
                }
                Frame one = std::move(queue0.front());
                Frame two = std::move(queue1.front());
                queue0.pop_front();
                queue1.pop_front();
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
                    std::cerr << "capture frame gap cam0=" << last0 << "->"
                              << one.sequence << " cam1=" << last1 << "->"
                              << two.sequence << "; continuing\n";
                }
                have_pair = true;
                last0 = one.sequence;
                last1 = two.sequence;
                return FramePair{one.sequence, two.sequence,
                                 one.timestamp_ns, two.timestamp_ns,
                                 std::move(one.luma), std::move(two.luma),
                                 std::move(one.luma10), std::move(two.luma10)};
            }
            pollfd descriptors[2] = {{left.fd(), POLLIN, 0},
                                     {right.fd(), POLLIN, 0}};
            const int ready = ::poll(descriptors, 2, 200);
            if (ready < 0) {
                if (errno == EINTR) continue;
                throw std::runtime_error(std::string("poll cameras: ") +
                                         std::strerror(errno));
            }
            if (ready == 0) {
                if (++idle_ticks >= 15)
                    throw std::runtime_error("no synchronized camera frames for 3 seconds");
                continue;
            }
            idle_ticks = 0;
            if ((descriptors[0].revents | descriptors[1].revents) &
                (POLLERR | POLLHUP | POLLNVAL))
                throw std::runtime_error("V4L2 camera poll error");
            if (descriptors[0].revents & POLLIN) drain(left, queue0);
            if (descriptors[1].revents & POLLIN) drain(right, queue1);
        }
        return {};
    }
};

StereoCapture::StereoCapture(const std::string& cam0, const std::string& cam1,
                             int scale, int frame_rate, bool hdr_display, bool tenbit)
    : impl_(std::make_unique<Impl>(cam0, cam1, scale, frame_rate, hdr_display, tenbit)) {}
StereoCapture::~StereoCapture() = default;
StereoCapture::StereoCapture(StereoCapture&&) noexcept = default;
StereoCapture& StereoCapture::operator=(StereoCapture&&) noexcept = default;
FramePair StereoCapture::next(std::stop_token stop) { return impl_->next(stop); }

} // namespace stereo_rtsp
