// SPDX-License-Identifier: GPL-2.0-only
#include "sc132gs-ae.hpp"
#include "sc132gs-control-server.hpp"

#include <linux/videodev2.h>

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <deque>
#include <exception>
#include <fcntl.h>
#include <iostream>
#include <limits>
#include <optional>
#include <poll.h>
#include <stdexcept>
#include <string>
#include <string_view>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <utility>
#include <vector>

namespace {

constexpr std::uint32_t kWidth = 1088;
constexpr std::uint32_t kHeight = 1280;
constexpr std::uint32_t kFrameBytes = kWidth * kHeight * 10 / 8;
constexpr std::uint32_t kRaw10Packed = v4l2_fourcc('p', 'R', 'A', 'A');
constexpr std::uint32_t kBufferCount = 4;
constexpr v4l2_buf_type kBufferType = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
constexpr std::size_t kMaximumQueuedFrames = 8;

struct Error final : std::runtime_error {
    Error(std::string operation, int error_number)
        : std::runtime_error(operation + ": " + std::strerror(error_number)),
          operation(std::move(operation)), error_number(error_number) {}

    std::string operation;
    int error_number;
};

int xioctl(int fd, unsigned long request, void* argument) {
    int result;
    do {
        result = ::ioctl(fd, request, argument);
    } while (result < 0 && errno == EINTR);
    return result;
}

struct Frame final {
    std::uint32_t sequence{};
    std::int64_t timestamp_ns{};
    std::vector<std::uint8_t> pixels;
};

class CaptureDevice final {
public:
    explicit CaptureDevice(std::string path) : path_(std::move(path)) {
        fd_ = ::open(path_.c_str(), O_RDWR | O_NONBLOCK | O_CLOEXEC);
        if (fd_ < 0) {
            throw Error("open " + path_, errno);
        }
    }

    CaptureDevice(const CaptureDevice&) = delete;
    CaptureDevice& operator=(const CaptureDevice&) = delete;
    CaptureDevice(CaptureDevice&&) = delete;
    CaptureDevice& operator=(CaptureDevice&&) = delete;

    ~CaptureDevice() {
        stop_noexcept();
        for (const auto& mapping : mappings_) {
            if (mapping.address != MAP_FAILED) {
                ::munmap(mapping.address, mapping.length);
            }
        }
        if (fd_ >= 0) {
            ::close(fd_);
        }
    }

    [[nodiscard]] int fd() const noexcept { return fd_; }
    [[nodiscard]] const std::string& path() const noexcept { return path_; }

    void prepare() {
        v4l2_format format{};
        format.type = kBufferType;
        format.fmt.pix_mp.width = kWidth;
        format.fmt.pix_mp.height = kHeight;
        format.fmt.pix_mp.pixelformat = kRaw10Packed;
        format.fmt.pix_mp.field = V4L2_FIELD_NONE;
        checked_ioctl(VIDIOC_S_FMT, &format, "VIDIOC_S_FMT");
        if (format.fmt.pix_mp.width != kWidth ||
            format.fmt.pix_mp.height != kHeight ||
            format.fmt.pix_mp.pixelformat != kRaw10Packed ||
            format.fmt.pix_mp.num_planes != 1 ||
            format.fmt.pix_mp.plane_fmt[0].sizeimage < kFrameBytes) {
            throw std::runtime_error(path_ + ": driver rejected 1088x1280 pRAA");
        }

        v4l2_requestbuffers request{};
        request.count = kBufferCount;
        request.type = kBufferType;
        request.memory = V4L2_MEMORY_MMAP;
        checked_ioctl(VIDIOC_REQBUFS, &request, "VIDIOC_REQBUFS");
        if (request.count < 2) {
            throw std::runtime_error(path_ + ": fewer than two MMAP buffers");
        }

        mappings_.reserve(request.count);
        for (std::uint32_t index = 0; index < request.count; ++index) {
            v4l2_buffer buffer{};
            v4l2_plane planes[VIDEO_MAX_PLANES]{};
            buffer.type = kBufferType;
            buffer.memory = V4L2_MEMORY_MMAP;
            buffer.index = index;
            buffer.m.planes = planes;
            buffer.length = VIDEO_MAX_PLANES;
            checked_ioctl(VIDIOC_QUERYBUF, &buffer, "VIDIOC_QUERYBUF");

            void* address = ::mmap(nullptr, planes[0].length,
                                   PROT_READ | PROT_WRITE, MAP_SHARED, fd_,
                                   planes[0].m.mem_offset);
            if (address == MAP_FAILED) {
                throw Error("mmap " + path_, errno);
            }
            mappings_.push_back({address, planes[0].length});
        }
    }

    void start() {
        for (std::uint32_t index = 0; index < mappings_.size(); ++index) {
            v4l2_buffer buffer{};
            v4l2_plane plane{};
            buffer.type = kBufferType;
            buffer.memory = V4L2_MEMORY_MMAP;
            buffer.index = index;
            buffer.m.planes = &plane;
            buffer.length = 1;
            checked_ioctl(VIDIOC_QBUF, &buffer, "VIDIOC_QBUF");
        }

        v4l2_buf_type type = kBufferType;
        checked_ioctl(VIDIOC_STREAMON, &type, "VIDIOC_STREAMON");
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
            if (errno == EAGAIN) {
                return std::nullopt;
            }
            throw Error("VIDIOC_DQBUF " + path_, errno);
        }

        Frame frame;
        try {
            if (buffer.index >= mappings_.size() || plane.bytesused < kFrameBytes) {
                throw std::runtime_error(path_ + ": short or invalid RAW10 buffer");
            }
            frame.sequence = buffer.sequence;
            frame.timestamp_ns =
                static_cast<std::int64_t>(buffer.timestamp.tv_sec) * 1'000'000'000LL +
                static_cast<std::int64_t>(buffer.timestamp.tv_usec) * 1'000LL;
            frame.pixels.resize(kFrameBytes);
            std::memcpy(frame.pixels.data(), mappings_[buffer.index].address,
                        kFrameBytes);
        } catch (...) {
            requeue(buffer.index);
            throw;
        }
        requeue(buffer.index);
        return frame;
    }

private:
    struct Mapping final {
        void* address{MAP_FAILED};
        std::size_t length{};
    };

    void checked_ioctl(unsigned long request, void* argument,
                       std::string_view operation) {
        if (xioctl(fd_, request, argument) < 0) {
            throw Error(std::string(operation) + " " + path_, errno);
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
        checked_ioctl(VIDIOC_QBUF, &buffer, "VIDIOC_QBUF(requeue)");
    }

    void stop_noexcept() noexcept {
        if (!streaming_) {
            return;
        }
        v4l2_buf_type type = kBufferType;
        (void)xioctl(fd_, VIDIOC_STREAMOFF, &type);
        streaming_ = false;
    }

    std::string path_;
    int fd_{-1};
    bool streaming_{false};
    std::vector<Mapping> mappings_;
};

#pragma pack(push, 1)
struct PairHeader final {
    std::array<char, 8> magic{'S', '1', '3', '2', 'P', 'A', 'I', 'R'};
    std::uint32_t version{1};
    std::uint32_t header_bytes{64};
    std::uint32_t frame_bytes{kFrameBytes};
    std::uint32_t width{kWidth};
    std::uint32_t height{kHeight};
    std::uint32_t reserved{};
    std::uint64_t pair_index{};
    std::int64_t cam0_timestamp_ns{};
    std::int64_t cam1_timestamp_ns{};
    std::uint32_t cam0_sequence{};
    std::uint32_t cam1_sequence{};
};
#pragma pack(pop)

static_assert(sizeof(PairHeader) == 64);

bool write_all(const void* data, std::size_t size) {
    const auto* bytes = static_cast<const std::uint8_t*>(data);
    while (size > 0) {
        const ssize_t count = ::write(STDOUT_FILENO, bytes, size);
        if (count < 0) {
            if (errno == EINTR) {
                continue;
            }
            if (errno == EPIPE) {
                return false;
            }
            throw Error("write paired stream", errno);
        }
        bytes += count;
        size -= static_cast<std::size_t>(count);
    }
    return true;
}

std::uint32_t parse_u32(const char* text, std::string_view name) {
    try {
        const auto value = std::stoull(text);
        if (value == 0 || value > std::numeric_limits<std::uint32_t>::max()) {
            throw std::out_of_range("u32");
        }
        return static_cast<std::uint32_t>(value);
    } catch (const std::exception&) {
        throw std::runtime_error(std::string(name) + " must be a positive integer");
    }
}

void keep_bounded(std::deque<Frame>& frames) {
    while (frames.size() > kMaximumQueuedFrames) {
        frames.pop_front();
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc < 3) {
            throw std::invalid_argument("usage: sc132gs-paired-stream CAM0_NODE CAM1_NODE [preview_step] [max_delta_us]; resolve nodes with sc132gs-discover pair");
        }
        const std::string cam0_path = argv[1];
        const std::string cam1_path = argv[2];
        const std::uint32_t preview_step = argc > 3
                                               ? parse_u32(argv[3], "preview_step")
                                               : 3;
        const std::int64_t tolerance_ns =
            static_cast<std::int64_t>(argc > 4
                                          ? parse_u32(argv[4], "max_delta_us")
                                          : 1000) *
            1000LL;

        CaptureDevice cam0(cam0_path);
        CaptureDevice cam1(cam1_path);
        cam0.prepare();
        cam1.prepare();
        cam0.start();
        cam1.start();
        AutoExposure exposure;
        ControlServer control(exposure);

        std::cerr << "paired stream armed cam0=" << cam0_path
                  << " cam1=" << cam1_path << " preview_step=" << preview_step
                  << " max_delta_us=" << tolerance_ns / 1000 << '\n';

        std::deque<Frame> queue0;
        std::deque<Frame> queue1;
        std::uint64_t matched_pairs = 0;
        std::uint64_t emitted_pairs = 0;
        std::uint64_t dropped0 = 0;
        std::uint64_t dropped1 = 0;

        for (;;) {
            pollfd descriptors[2] = {
                {cam0.fd(), POLLIN, 0},
                {cam1.fd(), POLLIN, 0},
            };
            const int ready = ::poll(descriptors, 2, 3000);
            if (ready < 0) {
                if (errno == EINTR) {
                    continue;
                }
                throw Error("poll paired cameras", errno);
            }
            if (ready == 0) {
                throw std::runtime_error(
                    "no paired camera frame for 3 seconds; verify common FSYNC");
            }
            for (const auto& descriptor : descriptors) {
                if (descriptor.revents & (POLLERR | POLLHUP | POLLNVAL)) {
                    throw std::runtime_error("camera poll error or disconnected device");
                }
            }
            if (descriptors[0].revents & POLLIN) {
                if (auto frame = cam0.dequeue()) {
                    queue0.push_back(std::move(*frame));
                    keep_bounded(queue0);
                }
            }
            if (descriptors[1].revents & POLLIN) {
                if (auto frame = cam1.dequeue()) {
                    queue1.push_back(std::move(*frame));
                    keep_bounded(queue1);
                }
            }

            while (!queue0.empty() && !queue1.empty()) {
                const auto delta_ns =
                    queue1.front().timestamp_ns - queue0.front().timestamp_ns;
                if (delta_ns > tolerance_ns) {
                    queue0.pop_front();
                    ++dropped0;
                    continue;
                }
                if (delta_ns < -tolerance_ns) {
                    queue1.pop_front();
                    ++dropped1;
                    continue;
                }

                Frame frame0 = std::move(queue0.front());
                Frame frame1 = std::move(queue1.front());
                queue0.pop_front();
                queue1.pop_front();
                exposure.process(frame0.pixels, frame1.pixels,
                                 frame0.sequence, frame0.timestamp_ns);
                const bool emit = matched_pairs % preview_step == 0;
                ++matched_pairs;
                if (!emit) {
                    continue;
                }

                PairHeader header;
                header.pair_index = emitted_pairs++;
                header.cam0_timestamp_ns = frame0.timestamp_ns;
                header.cam1_timestamp_ns = frame1.timestamp_ns;
                header.cam0_sequence = frame0.sequence;
                header.cam1_sequence = frame1.sequence;
                if (!write_all(&header, sizeof(header)) ||
                    !write_all(frame0.pixels.data(), frame0.pixels.size()) ||
                    !write_all(frame1.pixels.data(), frame1.pixels.size())) {
                    return 0;
                }

                if (emitted_pairs % 100 == 0) {
                    std::cerr << "paired stream emitted=" << emitted_pairs
                              << " matched=" << matched_pairs
                              << " dropped_cam0=" << dropped0
                              << " dropped_cam1=" << dropped1 << '\n';
                }
            }
        }
    } catch (const Error& error) {
        std::cerr << "error operation=" << error.operation
                  << " errno=" << error.error_number
                  << " message=" << error.what() << '\n';
    } catch (const std::exception& error) {
        std::cerr << "error message=" << error.what() << '\n';
    }
    return 1;
}
