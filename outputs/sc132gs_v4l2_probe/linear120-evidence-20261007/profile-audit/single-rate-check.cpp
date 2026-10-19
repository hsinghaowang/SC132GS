// SPDX-License-Identifier: GPL-2.0-only

#include <linux/videodev2.h>

#include <algorithm>
#include <fstream>
#include <set>
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
    std::uint64_t checksum{};
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
        if ((buffer.flags & V4L2_BUF_FLAG_ERROR) || plane.bytesused != 1740800)
            throw std::runtime_error("invalid RAW10 payload or V4L2 error flag");
        const auto* bytes = static_cast<const unsigned char*>(buffers_[buffer.index].address);
        std::uint64_t checksum = 14695981039346656037ULL;
        for (std::size_t offset = 0; offset < plane.bytesused; offset += 4096)
            checksum = (checksum ^ bytes[offset]) * 1099511628211ULL;
        const Sample sample{buffer.sequence, timestamp_ns, checksum};
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
        if (argc != 3) throw std::invalid_argument("usage: single-rate-check CAMERA_NODE FRAMES");
        const auto count = parse_size(argv[2], "frames");
        CaptureDevice camera(argv[1]);
        camera.prepare();
        camera.start();
        std::cout << "Stream armed" << std::endl;
        std::vector<Sample> samples;
        while (samples.size() < count + 120) {
            pollfd descriptor{camera.fd(), POLLIN, 0};
            int ready = ::poll(&descriptor, 1, 10000);
            if (ready < 0 && errno == EINTR) continue;
            if (ready <= 0 || (descriptor.revents & (POLLERR|POLLHUP|POLLNVAL)))
                throw std::runtime_error("no valid frame or capture poll error");
            if (auto sample = camera.dequeue()) samples.push_back(*sample);
        }
        samples.erase(samples.begin(), samples.begin()+120);
        std::ofstream csv("cam0.csv");
        csv << "sequence,timestamp_ns,sparse_payload_hash\n";
        std::size_t gaps=0;
        for (std::size_t i=0; i<samples.size(); ++i) {
            csv << samples[i].sequence << ',' << samples[i].timestamp_ns << ',' << samples[i].checksum << '\n';
            if(i) gaps += samples[i].sequence != samples[i-1].sequence+1;
        }
        double fps = (samples.size()-1)*1e9/(samples.back().timestamp_ns-samples.front().timestamp_ns);
        std::cout << "frames=" << samples.size() << " measured_fps=" << fps << " sequence_gap_events=" << gaps << '\n';
        return fps >= 118 && fps <= 122 && gaps == 0 ? 0 : 2;
    } catch(const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}