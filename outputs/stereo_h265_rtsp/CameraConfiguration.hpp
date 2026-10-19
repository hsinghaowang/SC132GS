#pragma once
#include <chrono>
#include <memory>
#include <optional>
#include <variant>
#include <vector>

namespace sc132gs::configuration {
enum class Mode { linear, hdr };
enum class ErrorCode { invalid_argument, unsupported, busy, device, verification, internal };
struct Error { ErrorCode code{ErrorCode::internal}; int system_error{}; bool rollback_failed{}; };
template<class T> using Result = std::variant<T, Error>;
struct Resolution { int width{}; int height{}; };
struct Profile {
    Mode mode;
    bool binning;
    Resolution eye_resolution;
    std::vector<int> supported_fps;
    int rows_per_second; // Zero means conversion to time is not characterized.
    int maximum_exposure_rows;
    int maximum_gain_index;
};
struct Exposure {
    bool automatic{true};
    int brightness_percent{30}; // Calibrated sensor signal P50 percent in unbinned Main10 Linear/HDR; excludes player curves.
    // Omitted manual values freeze the current settings for the same profile.
    std::optional<std::chrono::microseconds> time;
    std::optional<int> hdr_total_rows;
    std::optional<int> gain_index;
    std::chrono::microseconds maximum_time{}; // Zero uses the FPS/profile limit.
    int maximum_gain_index{128};
};
struct Settings {
    Mode mode{Mode::linear};
    bool binning{false};
    int maximum_fps{60}; // Upper bound; select greatest supported cadence <= it.
    Exposure exposure;
};
struct State {
    Settings settings;
    Resolution eye_resolution;
    int configured_fps{};
    int measured_fps_x10{};
    int exposure_rows{};
    int gain_index{};
    int exposure_ceiling_rows{};
    bool brightness_limited{};
    int control_error{};
    int revision{};
};
struct Plan { Settings settings; Profile profile; int effective_fps{}; int expected_revision{}; };

class CameraController final {
public:
    class Backend {
    public:
        virtual ~Backend() = default;
        virtual Result<State> inspect() = 0;
        // Owns the cross-process lock and performs verified apply/rollback.
        virtual Result<State> apply(const Plan& plan) = 0;
    };
    explicit CameraController(Backend& backend);
    ~CameraController();
    CameraController(CameraController&&) noexcept;
    CameraController& operator=(CameraController&&) noexcept;
    CameraController(const CameraController&) = delete;
    CameraController& operator=(const CameraController&) = delete;
    [[nodiscard]] static std::vector<Profile> capabilities();
    [[nodiscard]] Result<State> inspect();
    [[nodiscard]] Result<State> apply(const Settings& settings, int expected_revision);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
class LinuxBackend final : public CameraController::Backend {
public:
    LinuxBackend();
    ~LinuxBackend();
    LinuxBackend(LinuxBackend&&) noexcept;
    LinuxBackend& operator=(LinuxBackend&&) noexcept;
    LinuxBackend(const LinuxBackend&) = delete;
    LinuxBackend& operator=(const LinuxBackend&) = delete;
    Result<State> inspect() override;
    Result<State> apply(const Plan& plan) override;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace sc132gs::configuration
