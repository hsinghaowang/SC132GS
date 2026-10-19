#include "CameraConfiguration.hpp"
#include "FrameTiming.hpp"
#include "../sc132gs_v4l2_probe/sc132gs-exposure-budget.hpp"
#include <algorithm>
#include <utility>
namespace sc132gs::configuration {
struct CameraController::Impl { Backend& backend; };
CameraController::CameraController(Backend& backend) : impl_(std::make_unique<Impl>(Impl{backend})) {}
CameraController::~CameraController() = default;
CameraController::CameraController(CameraController&&) noexcept = default;
CameraController& CameraController::operator=(CameraController&&) noexcept = default;
std::vector<Profile> CameraController::capabilities() {
    std::vector<int> linear, hdr;
    for (int fps=1; fps<=60; ++fps) linear.push_back(fps);
    for (int fps=1; fps<=30; ++fps) hdr.push_back(fps);
    return {{Mode::linear, false, {1088,1280}, linear, 84000, 2560, 128},
            {Mode::linear, true, {544,640}, linear, 162000, 2560, 128},
            {Mode::hdr, false, {1088,1280}, hdr, 0, 4350, 128}};
}
Result<State> CameraController::inspect() { return impl_->backend.inspect(); }
Result<State> CameraController::apply(const Settings& settings, int revision) {
    const auto& exposure = settings.exposure;
    if (settings.maximum_fps <= 0 || exposure.brightness_percent < 0 ||
        exposure.brightness_percent > 100 || exposure.maximum_time.count() < 0 ||
        exposure.maximum_time.count() > 40000 || exposure.maximum_gain_index < 0 ||
        exposure.maximum_gain_index > 128 ||
        (exposure.gain_index && (*exposure.gain_index < 0 || *exposure.gain_index > 128)) ||
        (exposure.time && exposure.time->count() <= 0) ||
        (exposure.hdr_total_rows && *exposure.hdr_total_rows < 8) ||
        (exposure.time && exposure.hdr_total_rows)) return Error{ErrorCode::invalid_argument};
    const auto profiles = capabilities();
    const auto found = std::find_if(profiles.begin(), profiles.end(), [&](const Profile& profile) {
        return profile.mode == settings.mode && profile.binning == settings.binning;
    });
    if (found == profiles.end()) return Error{ErrorCode::unsupported};
    int fps = 0;
    for (int rate : found->supported_fps) if (rate <= settings.maximum_fps) fps = std::max(fps, rate);
    if (fps == 0 || (settings.mode == Mode::hdr && (exposure.time || exposure.maximum_time.count() > 0)) ||
        (settings.mode == Mode::linear && exposure.hdr_total_rows) ||
        (exposure.hdr_total_rows && *exposure.hdr_total_rows > found->maximum_exposure_rows) ||
        (exposure.gain_index && *exposure.gain_index > std::min(found->maximum_gain_index,
                                                               exposure.maximum_gain_index)))
        return Error{ErrorCode::unsupported};
    if (exposure.automatic && (exposure.time || exposure.hdr_total_rows || exposure.gain_index))
        return Error{ErrorCode::invalid_argument};
    if(exposure.hdr_total_rows && *exposure.hdr_total_rows>sc132gs::exposure_budget::hdr_ceiling(fps))
        return Error{ErrorCode::invalid_argument};
    auto profile = *found;
    if (profile.binning) profile.rows_per_second = detail::binning_rows_per_second(fps);
    if (exposure.time) {
        const auto limit_rows = std::min(profile.maximum_exposure_rows,
            sc132gs::exposure_budget::ceiling(profile.rows_per_second,fps,
                                            sc132gs::exposure_budget::reserved_rows(profile.binning,fps)));
        const auto rows = (exposure.time->count() * profile.rows_per_second + 500000) / 1000000;
        if (rows < 8 || rows > limit_rows || (exposure.maximum_time.count() > 0 &&
            exposure.time->count() > exposure.maximum_time.count()))
            return Error{ErrorCode::invalid_argument};
    }
    return impl_->backend.apply(Plan{settings, profile, fps, revision});
}
} // namespace sc132gs::configuration
