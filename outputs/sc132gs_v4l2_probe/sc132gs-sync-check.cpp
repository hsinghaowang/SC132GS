// SPDX-License-Identifier: GPL-2.0-only

#include <linux/videodev2.h>

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <exception>
#include <fcntl.h>
#include <iostream>
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
constexpr std::uint32_t kRaw10Packed = v4l2_fourcc('p', 'R', 'A', 'A');
constexpr std::uint32_t kBufferCount = 4;
constexpr v4l2_buf_type kBufferType = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;

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

struct Sample final {
    std::uint32_t sequence{};
    std::int64_t timestamp_ns{};
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
        for (const auto& buffer : buffers_) {
            if (buffer.address != MAP_FAILED) {
                ::munmap(buffer.address, buffer.length);
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
            format.fmt.pix_mp.num_planes != 1) {
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

        buffers_.reserve(request.count);
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
            buffers_.push_back({address, planes[0].length});
        }
    }

    void start() {
        for (std::uint32_t index = 0; index < buffers_.size(); ++index) {
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

    std::optional<Sample> dequeue() {
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

        const auto timestamp_ns =
            static_cast<std::int64_t>(buffer.timestamp.tv_sec) * 1'000'000'000LL +
            static_cast<std::int64_t>(buffer.timestamp.tv_usec) * 1'000LL;
        const Sample sample{buffer.sequence, timestamp_ns};
        checked_ioctl(VIDIOC_QBUF, &buffer, "VIDIOC_QBUF(requeue)");
        return sample;
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
    std::vector<Mapping> buffers_;
};

double percentile(std::vector<double> values, double fraction) {
    std::sort(values.begin(), values.end());
    const auto index = static_cast<std::size_t>(
        std::llround(fraction * static_cast<double>(values.size() - 1)));
    return values[index];
}

struct Alignment final {
    int offset{};
    std::vector<double> signed_delta_us;
    double median_abs_us{};
};

Alignment align_samples(const std::vector<Sample>& cam0,
                        const std::vector<Sample>& cam1) {
    std::optional<Alignment> best;
    for (int offset = -5; offset <= 5; ++offset) {
        Alignment candidate;
        candidate.offset = offset;
        std::vector<double> absolute;

        for (std::size_t i = 0; i < cam0.size(); ++i) {
            const auto j = static_cast<long long>(i) + offset;
            if (j < 0 || j >= static_cast<long long>(cam1.size())) {
                continue;
            }
            const auto delta = static_cast<double>(
                cam1[static_cast<std::size_t>(j)].timestamp_ns - cam0[i].timestamp_ns) /
                1000.0;
            candidate.signed_delta_us.push_back(delta);
            absolute.push_back(std::abs(delta));
        }
        candidate.median_abs_us = percentile(absolute, 0.5);
        if (!best || candidate.median_abs_us < best->median_abs_us) {
            best = std::move(candidate);
        }
    }
    return *best;
}

std::size_t parse_size(const char* text, std::string_view name) {
    try {
        const auto value = std::stoull(text);
        if (value == 0) {
            throw std::invalid_argument("zero");
        }
        return static_cast<std::size_t>(value);
    } catch (const std::exception&) {
        throw std::runtime_error(std::string(name) + " must be a positive integer");
    }
}

double parse_double(const char* text, std::string_view name) {
    try {
        const auto value = std::stod(text);
        if (!(value > 0.0)) {
            throw std::invalid_argument("non-positive");
        }
        return value;
    } catch (const std::exception&) {
        throw std::runtime_error(std::string(name) + " must be positive");
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc < 3) {
            throw std::invalid_argument("usage: sc132gs-sync-check CAM0_NODE CAM1_NODE [frames] [max_delta_us] [warmup_frames]; resolve nodes with sc132gs-discover pair");
        }
        const std::string cam0_path = argv[1];
        const std::string cam1_path = argv[2];
        const std::size_t frame_count = argc > 3 ? parse_size(argv[3], "frames") : 120;
        const double maximum_p95_us = argc > 4 ? parse_double(argv[4], "max_delta_us") : 500.0;
        const std::size_t warmup_count = argc > 5 ? parse_size(argv[5], "warmup_frames") : 8;
        const std::size_t capture_count = frame_count + warmup_count;

        CaptureDevice cam0(cam0_path);
        CaptureDevice cam1(cam1_path);
        cam0.prepare();
        cam1.prepare();

        // Both receivers are armed before the function waits for FSYNC frames.
        cam0.start();
        cam1.start();
        std::cout << "Both streams armed; waiting for common FSYNC trigger..."
                  << std::endl;

        std::vector<Sample> samples0;
        std::vector<Sample> samples1;
        samples0.reserve(capture_count);
        samples1.reserve(capture_count);

        while (samples0.size() < capture_count || samples1.size() < capture_count) {
            pollfd descriptors[2] = {
                {samples0.size() < capture_count ? cam0.fd() : -1, POLLIN, 0},
                {samples1.size() < capture_count ? cam1.fd() : -1, POLLIN, 0},
            };
            const int ready = ::poll(descriptors, 2, 3000);
            if (ready < 0) {
                if (errno == EINTR) {
                    continue;
                }
                throw Error("poll", errno);
            }
            if (ready == 0) {
                throw std::runtime_error(
                    "no frame for 3 seconds; verify both sensors are in slave mode "
                    "and the common FSYNC source is running");
            }
            for (const auto& descriptor : descriptors) {
                if (descriptor.revents & (POLLERR | POLLHUP | POLLNVAL)) {
                    throw std::runtime_error(
                        "capture poll reported an error or disconnected device");
                }
            }

            if ((descriptors[0].revents & POLLIN) && samples0.size() < capture_count) {
                if (auto sample = cam0.dequeue()) {
                    samples0.push_back(*sample);
                }
            }
            if ((descriptors[1].revents & POLLIN) && samples1.size() < capture_count) {
                if (auto sample = cam1.dequeue()) {
                    samples1.push_back(*sample);
                }
            }
        }

        samples0.erase(samples0.begin(), samples0.begin() + warmup_count);
        samples1.erase(samples1.begin(), samples1.begin() + warmup_count);

        const Alignment alignment = align_samples(samples0, samples1);
        std::vector<double> absolute_delta;
        absolute_delta.reserve(alignment.signed_delta_us.size());
        for (const double delta : alignment.signed_delta_us) {
            absolute_delta.push_back(std::abs(delta));
        }

        const double median = percentile(absolute_delta, 0.5);
        const double p95 = percentile(absolute_delta, 0.95);
        const double maximum = *std::max_element(absolute_delta.begin(), absolute_delta.end());
        const auto worst = static_cast<std::size_t>(
            std::distance(absolute_delta.begin(),
                          std::max_element(absolute_delta.begin(), absolute_delta.end())));
        const double drift = alignment.signed_delta_us.back() -
                             alignment.signed_delta_us.front();

        std::cout << "warmup_frames=" << warmup_count
                  << " cam0_sequence=" << samples0.front().sequence << ".."
                  << samples0.back().sequence << " cam1_sequence="
                  << samples1.front().sequence << ".." << samples1.back().sequence
                  << '\n'
                  << "paired_frames=" << alignment.signed_delta_us.size()
                  << " cam1_index_offset=" << alignment.offset << '\n'
                  << "abs_delta_us median=" << median << " p95=" << p95
                  << " max=" << maximum << " worst_pair=" << worst
                  << " signed_drift=" << drift << '\n'
                  << "timestamp_check=" << (p95 <= maximum_p95_us ? "PASS" : "FAIL")
                  << " threshold_us=" << maximum_p95_us << '\n';

        return p95 <= maximum_p95_us ? 0 : 2;
    } catch (const Error& error) {
        std::cerr << "error operation=" << error.operation
                  << " errno=" << error.error_number
                  << " message=" << error.what() << '\n';
    } catch (const std::exception& error) {
        std::cerr << "error message=" << error.what() << '\n';
    }
    return 1;
}
