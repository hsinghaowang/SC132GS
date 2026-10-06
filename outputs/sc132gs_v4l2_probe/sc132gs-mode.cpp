// SPDX-License-Identifier: GPL-2.0-only
#include "sc132gs-mode.hpp"
#include <utility>
namespace sc132gs {
struct ModeController::Impl {
    Backend& backend;
    Observer* observer;
    void phase(Phase p) { if (observer) observer->on_phase(p); }
};
ModeController::ModeController(Backend& backend, Observer* observer)
    : impl_(std::make_unique<Impl>(Impl{backend, observer})) {}
ModeController::~ModeController() = default;
ModeController::ModeController(ModeController&&) noexcept = default;
ModeController& ModeController::operator=(ModeController&&) noexcept = default;
ModeController::Result ModeController::set_mode(CameraMode mode) {
    Result result;
    ModeState previous;
    bool changed = false;
    try {
        impl_->phase(Phase::inspecting);
        previous = impl_->backend.inspect();
        const ModeState desired{mode, mode == CameraMode::hdr ? 30 : 60, true, previous.auto_exposure};
        if (previous.mode == desired.mode && previous.running && previous.fps == desired.fps) {
            impl_->phase(Phase::verifying);
            impl_->backend.verify(desired);
        } else {
            // Stop/configure may fail after a partial change. Always restore both eyes.
            changed = true;
            impl_->phase(Phase::stopping);
            impl_->backend.stop();
            impl_->phase(Phase::configuring);
            impl_->backend.configure(mode);
            impl_->phase(Phase::starting);
            impl_->backend.start(desired);
            impl_->phase(Phase::verifying);
            impl_->backend.verify(desired);
        }
        impl_->phase(Phase::persisting);
        impl_->backend.persist(mode);
        impl_->phase(Phase::ready);
        result.success = true;
    } catch (const ModeFailure& e) { result.error = e.error; }
      catch (...) { result.error.code = ModeErrorCode::internal; }
    if (!result.success && changed) {
        impl_->phase(Phase::restoring);
        try {
            impl_->backend.stop();
            impl_->backend.configure(previous.mode);
            if (previous.running) {
                impl_->backend.start(previous);
                impl_->backend.verify(previous);
            }
            result.restored = true;
        } catch (const ModeFailure& e) { result.restore_error = e.error; }
          catch (...) { result.restore_error.code = ModeErrorCode::internal; }
    }
    return result;
}
} // namespace sc132gs
