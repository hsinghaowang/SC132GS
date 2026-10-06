// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include <exception>
#include <memory>

namespace sc132gs {
enum class CameraMode { linear, hdr };
enum class ModeErrorCode { none, busy, permission, device, service, verification, persistence, internal };
struct ModeError { ModeErrorCode code{ModeErrorCode::none}; int system_error{}; };
struct ModeFailure final : std::exception {
    explicit ModeFailure(ModeError error) : error(error) {}
    const char* what() const noexcept override { return "camera mode operation failed"; }
    ModeError error;
};
struct ModeState {
    CameraMode mode{CameraMode::hdr};
    int fps{30};
    bool running{};
    bool auto_exposure{true};
};
class ModeController final {
public:
    enum class Phase { inspecting, stopping, configuring, starting, verifying, persisting, restoring, ready };
    class Observer {
    public:
        virtual ~Observer() = default;
        virtual void on_phase(Phase phase) noexcept = 0;
    };
    // A backend owns platform resources/settings. Operations may throw ModeFailure.
    class Backend {
    public:
        virtual ~Backend() = default;
        virtual ModeState inspect() = 0;
        virtual void stop() = 0;
        virtual void configure(CameraMode mode) = 0;
        virtual void start(const ModeState& state) = 0;
        virtual void verify(const ModeState& state) = 0;
        virtual void persist(CameraMode mode) = 0;
    };
    struct Result {
        bool success{};
        bool restored{};
        ModeError error;
        ModeError restore_error;
    };
    // Blocking operation; single caller per instance. Backend serializes other processes.
    explicit ModeController(Backend& backend, Observer* observer = nullptr);
    ~ModeController();
    ModeController(ModeController&&) noexcept;
    ModeController& operator=(ModeController&&) noexcept;
    ModeController(const ModeController&) = delete;
    ModeController& operator=(const ModeController&) = delete;
    [[nodiscard]] Result set_mode(CameraMode mode);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
// Linux details remain in the implementation; lifetime covers the process lock.
class LinuxModeBackend final : public ModeController::Backend {
public:
    explicit LinuxModeBackend(bool writable);
    ~LinuxModeBackend();
    LinuxModeBackend(LinuxModeBackend&&) noexcept;
    LinuxModeBackend& operator=(LinuxModeBackend&&) noexcept;
    LinuxModeBackend(const LinuxModeBackend&) = delete;
    LinuxModeBackend& operator=(const LinuxModeBackend&) = delete;
    ModeState inspect() override;
    void stop() override;
    void configure(CameraMode mode) override;
    void start(const ModeState& state) override;
    void verify(const ModeState& state) override;
    void persist(CameraMode mode) override;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace sc132gs
