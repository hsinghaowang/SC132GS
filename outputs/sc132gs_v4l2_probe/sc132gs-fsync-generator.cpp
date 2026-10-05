// SPDX-License-Identifier: GPL-2.0-only

#include <linux/gpio.h>

#include <atomic>
#include <cerrno>
#include <cmath>
#include <csignal>
#include <cstring>
#include <exception>
#include <fcntl.h>
#include <iostream>
#include <limits>
#include <sched.h>
#include <stdexcept>
#include <string>
#include <string_view>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <utility>

namespace {

std::atomic_bool stop_requested{false};
std::atomic_bool start_requested{false};

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

void handle_stop_signal(int) noexcept { stop_requested.store(true); }
void handle_start_signal(int) noexcept { start_requested.store(true); }

std::uint32_t parse_u32(const char* text, std::string_view name) {
    try {
        const auto value = std::stoull(text);
        if (value > std::numeric_limits<std::uint32_t>::max()) {
            throw std::out_of_range("u32");
        }
        return static_cast<std::uint32_t>(value);
    } catch (const std::exception&) {
        throw std::runtime_error(std::string(name) + " must be an unsigned integer");
    }
}

double parse_positive(const char* text, std::string_view name) {
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

std::string discover_chip(std::uint32_t highest_offset) {
    std::string fallback;
    for (int index = 0; index < 32; ++index) {
        const std::string path = "/dev/gpiochip" + std::to_string(index);
        const int fd = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
        if (fd < 0) {
            continue;
        }

        gpiochip_info info{};
        const bool usable = xioctl(fd, GPIO_GET_CHIPINFO_IOCTL, &info) == 0 &&
                            info.lines > highest_offset;
        ::close(fd);
        if (!usable) {
            continue;
        }

        const std::string identity = std::string(info.name) + " " + info.label;
        if (identity.find("pinctrl") != std::string::npos ||
            identity.find("tlmm") != std::string::npos) {
            return path;
        }
        if (fallback.empty()) {
            fallback = path;
        }
    }
    if (fallback.empty()) {
        throw std::runtime_error("cannot find a GPIO chip containing both FSYNC offsets");
    }
    return fallback;
}

class DualLine final {
public:
    DualLine(std::string chip_path, std::uint32_t line0, std::uint32_t line1,
             bool idle_high)
        : chip_path_(std::move(chip_path)), idle_high_(idle_high) {
        chip_fd_ = ::open(chip_path_.c_str(), O_RDONLY | O_CLOEXEC);
        if (chip_fd_ < 0) {
            throw Error("open " + chip_path_, errno);
        }

        gpio_v2_line_request request{};
        request.offsets[0] = line0;
        request.offsets[1] = line1;
        request.num_lines = 2;
        request.config.flags = GPIO_V2_LINE_FLAG_OUTPUT;
        std::strncpy(request.consumer, "sc132gs-fsync", sizeof(request.consumer) - 1);
        if (xioctl(chip_fd_, GPIO_V2_GET_LINE_IOCTL, &request) < 0) {
            throw Error("request GPIO lines " + std::to_string(line0) + "," +
                            std::to_string(line1),
                        errno);
        }
        line_fd_ = request.fd;
        set(idle_high_);
    }

    DualLine(const DualLine&) = delete;
    DualLine& operator=(const DualLine&) = delete;
    DualLine(DualLine&&) = delete;
    DualLine& operator=(DualLine&&) = delete;

    ~DualLine() {
        try {
            set(idle_high_);
        } catch (...) {
        }
        if (line_fd_ >= 0) {
            ::close(line_fd_);
        }
        if (chip_fd_ >= 0) {
            ::close(chip_fd_);
        }
    }

    void set(bool high) {
        if (line_fd_ < 0) {
            return;
        }
        gpio_v2_line_values values{};
        values.mask = 0x3;
        values.bits = high ? 0x3 : 0;
        if (xioctl(line_fd_, GPIO_V2_LINE_SET_VALUES_IOCTL, &values) < 0) {
            throw Error("set both FSYNC GPIOs", errno);
        }
    }

private:
    std::string chip_path_;
    bool idle_high_{};
    int chip_fd_{-1};
    int line_fd_{-1};
};

timespec add_ns(timespec value, std::int64_t nanoseconds) {
    value.tv_sec += nanoseconds / 1'000'000'000LL;
    value.tv_nsec += nanoseconds % 1'000'000'000LL;
    if (value.tv_nsec >= 1'000'000'000L) {
        ++value.tv_sec;
        value.tv_nsec -= 1'000'000'000L;
    }
    return value;
}

void sleep_until(const timespec& deadline) {
    while (!stop_requested.load()) {
        const int result = ::clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME,
                                             &deadline, nullptr);
        if (result == 0) {
            return;
        }
        if (result != EINTR) {
            throw Error("clock_nanosleep", result);
        }
    }
}

void wait_for_start_signal() {
    const timespec interval{0, 10'000'000L};
    while (!start_requested.load() && !stop_requested.load()) {
        timespec remaining{};
        if (::nanosleep(&interval, &remaining) < 0 && errno != EINTR) {
            throw Error("nanosleep", errno);
        }
    }
}

void improve_timing_best_effort() {
    if (::mlockall(MCL_CURRENT | MCL_FUTURE) < 0) {
        std::cerr << "warning: mlockall failed: " << std::strerror(errno) << '\n';
    }
    sched_param parameters{};
    parameters.sched_priority = 80;
    if (::sched_setscheduler(0, SCHED_FIFO, &parameters) < 0) {
        std::cerr << "warning: SCHED_FIFO failed: " << std::strerror(errno) << '\n';
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const std::string requested_chip = argc > 1 ? argv[1] : "auto";
        const std::uint32_t line0 = argc > 2 ? parse_u32(argv[2], "line0") : 18;
        const std::uint32_t line1 = argc > 3 ? parse_u32(argv[3], "line1") : 19;
        const double fps = argc > 4 ? parse_positive(argv[4], "fps") : 30.0;
        const double pulse_us = argc > 5 ? parse_positive(argv[5], "pulse_us") : 100.0;
        const std::string polarity = argc > 6 ? argv[6] : "active-low";
        if (polarity != "active-low" && polarity != "active-high") {
            throw std::runtime_error("polarity must be active-low or active-high");
        }
        const bool active_high = polarity == "active-high";

        const auto period_ns = static_cast<std::int64_t>(std::llround(1.0e9 / fps));
        const auto pulse_ns = static_cast<std::int64_t>(std::llround(pulse_us * 1000.0));
        if (pulse_ns >= period_ns) {
            throw std::runtime_error("pulse_us must be shorter than the frame period");
        }

        const std::string chip_path = requested_chip == "auto"
                                          ? discover_chip(std::max(line0, line1))
                                          : requested_chip;
        std::signal(SIGINT, handle_stop_signal);
        std::signal(SIGTERM, handle_stop_signal);
        std::signal(SIGUSR1, handle_start_signal);
        DualLine lines(chip_path, line0, line1, !active_high);
        improve_timing_best_effort();

        std::cout << "FSYNC generator armed chip=" << chip_path
                  << " lines=" << line0 << ',' << line1 << " fps=" << fps
                  << " pulse_us=" << pulse_us << " polarity=" << polarity
                  << "; send SIGUSR1 to start" << std::endl;
        wait_for_start_signal();
        if (stop_requested.load()) {
            std::cout << "FSYNC generator stopped before start\n";
            return 0;
        }

        timespec rising{};
        if (::clock_gettime(CLOCK_MONOTONIC, &rising) < 0) {
            throw Error("clock_gettime", errno);
        }
        rising = add_ns(rising, 100'000'000LL);

        std::cout << "FSYNC generator started" << std::endl;

        std::uint64_t pulses = 0;
        while (!stop_requested.load()) {
            sleep_until(rising);
            if (stop_requested.load()) {
                break;
            }
            lines.set(active_high);
            const timespec falling = add_ns(rising, pulse_ns);
            sleep_until(falling);
            lines.set(!active_high);
            rising = add_ns(rising, period_ns);
            ++pulses;
        }
        std::cout << "FSYNC generator stopped pulses=" << pulses << '\n';
        return 0;
    } catch (const Error& error) {
        std::cerr << "error operation=" << error.operation
                  << " errno=" << error.error_number
                  << " message=" << error.what() << '\n';
    } catch (const std::exception& error) {
        std::cerr << "error message=" << error.what() << '\n';
    }
    return 1;
}
