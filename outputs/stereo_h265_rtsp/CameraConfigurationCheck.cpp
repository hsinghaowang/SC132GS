#include "CameraConfiguration.hpp"
#include "../sc132gs_v4l2_probe/sc132gs-exposure-budget.hpp"
#include <algorithm>
#include <type_traits>
using namespace sc132gs::configuration;
struct FakeBackend final : CameraController::Backend {
    int calls{};
    Plan last{};
    Result<State> inspect() override { return State{}; }
    Result<State> apply(const Plan& plan) override { ++calls; last=plan; return State{}; }
};
int main() {
    // Target cadence must include non-overlapping readout; a 15-FPS observed
    // stream must never relax a requested 30-FPS deadline.
    using sc132gs::exposure_budget::ceiling;
    using sc132gs::exposure_budget::reserved_rows;
    static_assert(ceiling(84000,30,reserved_rows(false,30))==1377);
    static_assert(ceiling(84000,24,reserved_rows(false,24))==2042);
    static_assert(ceiling(84000,60,reserved_rows(false,60))==1330);
    static_assert(ceiling(162000,30,reserved_rows(true,30))==5130);
    static_assert(sc132gs::exposure_budget::hdr_ceiling(30)==1492);
    static_assert(sc132gs::exposure_budget::hdr_ceiling(24)==2560);
    static_assert(sc132gs::exposure_budget::hdr_ceiling(20)==3629);
    static_assert(sc132gs::exposure_budget::hdr_ceiling(15)==4350);
    static_assert(!std::is_copy_constructible_v<CameraController>);
    static_assert(std::is_move_constructible_v<CameraController>);
    FakeBackend backend;
    CameraController camera(backend);
    Settings config;
    if (std::holds_alternative<Error>(camera.apply(config,6)) || backend.last.settings.binning ||
        backend.last.settings.mode!=Mode::linear || !backend.last.settings.exposure.automatic ||
        backend.last.effective_fps!=60 || backend.last.settings.exposure.brightness_percent!=30 ||
        backend.last.settings.exposure.maximum_time.count()!=0 ||
        backend.last.settings.exposure.maximum_gain_index!=128) return 9;
    config.maximum_fps=50;
    if (std::holds_alternative<Error>(camera.apply(config,7)) || backend.last.effective_fps!=50 ||
        backend.last.expected_revision!=7) return 1;
    config.mode=Mode::hdr;
    config.binning=true;
    const int prior_calls=backend.calls;
    if (!std::holds_alternative<Error>(camera.apply(config,7)) || backend.calls!=prior_calls) return 2;
    config.binning=false; config.maximum_fps=60;
    if (std::holds_alternative<Error>(camera.apply(config,7)) || backend.last.effective_fps!=30) return 3;
    config.exposure.automatic=false;
    config.exposure.time=std::chrono::microseconds(8000);
    if (!std::holds_alternative<Error>(camera.apply(config,7))) return 4;
    config.mode=Mode::linear;
    config.exposure.time=std::chrono::microseconds(20000);
    if (!std::holds_alternative<Error>(camera.apply(config,7))) return 5;
    config.exposure.time=std::chrono::microseconds(8000);
    if (std::holds_alternative<Error>(camera.apply(config,7))) return 6;
    config.exposure.automatic=true;
    if (!std::holds_alternative<Error>(camera.apply(config,7))) return 7;
    config.exposure.time.reset(); config.maximum_fps=0;
    if (!std::holds_alternative<Error>(camera.apply(config,7))) return 8;
    config=Settings{};
    for (int fps=1;fps<=60;++fps) {
        config.maximum_fps=fps;
        if (std::holds_alternative<Error>(camera.apply(config,7)) || backend.last.effective_fps!=fps) return 10;
    }
    config.binning=true;
    for (int fps=1;fps<=60;++fps) {
        config.maximum_fps=fps;
        if (std::holds_alternative<Error>(camera.apply(config,7)) || backend.last.effective_fps!=fps) return 11;
        const int expected_rate=fps==1 ? 54000 : fps==2 ? 81000 : 162000;
        if (backend.last.profile.rows_per_second!=expected_rate) return 12;
    }
    config.mode=Mode::hdr; config.binning=false;
    for (int fps=1;fps<=60;++fps) {
        config.maximum_fps=fps;
        if (std::holds_alternative<Error>(camera.apply(config,7)) || backend.last.effective_fps!=std::min(fps,30)) return 13;
    }
    config=Settings{}; config.mode=Mode::hdr; config.maximum_fps=30;
    config.exposure.automatic=false; config.exposure.hdr_total_rows=1492;
    config.exposure.maximum_gain_index=16; config.exposure.gain_index=16;
    if (std::holds_alternative<Error>(camera.apply(config,7)) ||
        backend.last.settings.exposure.gain_index!=16) return 16;
    config.exposure.gain_index=17;
    if (!std::holds_alternative<Error>(camera.apply(config,7))) return 17;
    config=Settings{}; config.binning=true; config.maximum_fps=1;
    config.exposure.automatic=false; config.exposure.time=std::chrono::microseconds(40000);
    if (std::holds_alternative<Error>(camera.apply(config,7))) return 14;
    config.maximum_fps=2;
    if (!std::holds_alternative<Error>(camera.apply(config,7))) return 15;
    config=Settings{}; config.maximum_fps=30; config.exposure.automatic=false;
    config.exposure.time=std::chrono::microseconds(16000);
    if(std::holds_alternative<Error>(camera.apply(config,7))) return 18;
    const int budget_calls=backend.calls;
    config.exposure.time=std::chrono::microseconds(17000);
    if(!std::holds_alternative<Error>(camera.apply(config,7)) || backend.calls!=budget_calls) return 19;
    config=Settings{}; config.mode=Mode::hdr; config.maximum_fps=20; config.exposure.automatic=false;
    config.exposure.hdr_total_rows=3629;
    if(std::holds_alternative<Error>(camera.apply(config,7))) return 20;
    config.exposure.hdr_total_rows=3630;
    if(!std::holds_alternative<Error>(camera.apply(config,7))) return 21;
    config.maximum_fps=30; config.exposure.hdr_total_rows=1493;
    if(!std::holds_alternative<Error>(camera.apply(config,7))) return 22;
    config.maximum_fps=15; config.exposure.hdr_total_rows=4350;
    if(std::holds_alternative<Error>(camera.apply(config,7))) return 23;
    const int hdr_boundary_calls=backend.calls;
    config.exposure.hdr_total_rows=4351;
    if(!std::holds_alternative<Error>(camera.apply(config,7)) || backend.calls!=hdr_boundary_calls) return 24;
}
