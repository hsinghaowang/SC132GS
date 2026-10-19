#include "CameraConfiguration.hpp"
#include <algorithm>
#include <cerrno>
#include <map>
#include <sstream>
#include <string>
#include <vector>
#include <fcntl.h>
#include <sys/wait.h>
#include <unistd.h>

namespace sc132gs::configuration {
namespace {
struct Fd {
    int value;
    ~Fd() { if (value >= 0) ::close(value); }
    Fd(const Fd&) = delete;
    Fd& operator=(const Fd&) = delete;
    explicit Fd(int fd) : value(fd) {}
};
Result<State> invoke(std::vector<std::string> arguments) {
    int pipefd[2];
    if (::pipe2(pipefd, O_CLOEXEC) < 0) return Error{ErrorCode::device, errno};
    Fd input(pipefd[0]), output(pipefd[1]);
    arguments.insert(arguments.begin(), {"/usr/bin/python3", "/home/ubuntu/stereo-h265-rtsp/camera_platform.py"});
    std::vector<char*> argv;
    for (auto& value : arguments) argv.push_back(value.data());
    argv.push_back(nullptr);
    const auto pid = ::fork();
    if (pid < 0) return Error{ErrorCode::device, errno};
    if (pid == 0) {
        ::dup2(output.value, STDOUT_FILENO);
        ::execv(argv[0], argv.data());
        ::_exit(127);
    }
    ::close(output.value); output.value = -1;
    std::string result;
    char bytes[4096];
    for (;;) {
        const auto count = ::read(input.value, bytes, sizeof(bytes));
        if (count == 0) break;
        if (count < 0 && errno == EINTR) continue;
        if (count < 0) break;
        if (result.size() + static_cast<std::size_t>(count) <= 65536) result.append(bytes, count);
    }
    int exit_status{};
    while (::waitpid(pid, &exit_status, 0) < 0) if (errno != EINTR) return Error{ErrorCode::device, errno};
    std::map<std::string,std::string> fields;
    std::istringstream stream(result); std::string token;
    while (stream >> token) {
        const auto split = token.find('=');
        if (split != std::string::npos) fields[token.substr(0,split)] = token.substr(split+1);
    }
    try {
        auto number = [&](const char* key) { return std::stoi(fields.at(key)); };
        if (!WIFEXITED(exit_status) || WEXITSTATUS(exit_status) != 0 || fields.contains("error")) {
            const int code = fields.contains("error") ? number("error") : static_cast<int>(ErrorCode::device);
            if (code < 0 || code > static_cast<int>(ErrorCode::internal)) return Error{ErrorCode::internal};
            return Error{static_cast<ErrorCode>(code), fields.contains("errno") ? number("errno") : 0,
                         fields.contains("rollback_failed") && number("rollback_failed") != 0};
        }
        State state;
        state.settings.mode = fields.at("sensor_mode") == "hdr" ? Mode::hdr : Mode::linear;
        state.settings.binning = number("binning") != 0;
        state.settings.maximum_fps = number("max_fps");
        state.settings.exposure.automatic = number("ae") != 0;
        state.settings.exposure.brightness_percent = number("brightness");
        state.settings.exposure.maximum_time = std::chrono::microseconds(number("max_exposure_us"));
        state.settings.exposure.maximum_gain_index = number("max_gain_index");
        state.eye_resolution = {number("width"), number("height")};
        state.configured_fps = number("fps");
        state.measured_fps_x10 = number("measured_fps_x10");
        state.exposure_rows = number("exposure_rows");
        state.gain_index = number("gain_index");
        state.exposure_ceiling_rows = number("exposure_ceiling_rows");
        state.brightness_limited = number("limited") != 0;
        state.control_error = number("control_error");
        state.revision = number("revision");
        return state;
    } catch (...) { return Error{ErrorCode::internal}; }
}
}
struct LinuxBackend::Impl {};
LinuxBackend::LinuxBackend() : impl_(std::make_unique<Impl>()) {}
LinuxBackend::~LinuxBackend() = default;
LinuxBackend::LinuxBackend(LinuxBackend&&) noexcept = default;
LinuxBackend& LinuxBackend::operator=(LinuxBackend&&) noexcept = default;
Result<State> LinuxBackend::inspect() { return invoke({"status"}); }
Result<State> LinuxBackend::apply(const Plan& plan) {
    const auto& config = plan.settings;
    const auto& exposure = config.exposure;
    auto number = [](auto value) { return std::to_string(value); };
    return invoke({"apply", "--mode", config.mode == Mode::hdr ? "hdr" : "linear",
        "--binning", number(config.binning), "--max-fps", number(config.maximum_fps),
        "--fps", number(plan.effective_fps), "--ae", number(exposure.automatic),
        "--brightness", number(exposure.brightness_percent),
        "--exposure-us", number(exposure.time ? exposure.time->count() : -1),
        "--hdr-total-rows", number(exposure.hdr_total_rows.value_or(-1)),
        "--gain-index", number(exposure.gain_index.value_or(-1)),
        "--max-exposure-us", number(exposure.maximum_time.count()),
        "--max-gain-index", number(std::min(exposure.maximum_gain_index, plan.profile.maximum_gain_index)),
        "--revision", number(plan.expected_revision)});
}
} // namespace sc132gs::configuration
