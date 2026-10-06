#include "sc132gs-mode.hpp"
#include <iostream>
#include <stdexcept>
#include <vector>
using namespace sc132gs;
void require(bool value) { if (!value) throw std::runtime_error("mode recovery invariant failed"); }
struct Fake final : ModeController::Backend {
    ModeState state{CameraMode::hdr,30,true,true};
    CameraMode second{CameraMode::hdr};
    CameraMode saved{CameraMode::hdr};
    int fault{}, starts{}, stops{}, configurations{};
    bool consumed{};
    ModeState inspect() override {
        if (fault==1) throw ModeFailure({ModeErrorCode::device,5});
        return state;
    }
    void stop() override { ++stops; state.running=false; }
    void configure(CameraMode mode) override {
        ++configurations; state.mode=mode;
        if (fault==2 && !consumed) { consumed=true; throw ModeFailure({ModeErrorCode::device,5}); }
        if (fault==5 && consumed) throw ModeFailure({ModeErrorCode::device,6});
        second=mode;
    }
    void start(const ModeState& desired) override { ++starts; state=desired; }
    void verify(const ModeState& desired) override {
        if ((fault==3 || fault==5) && !consumed) {
            consumed=true; throw ModeFailure({ModeErrorCode::verification,110});
        }
        require(state.mode==second && state.mode==desired.mode && state.running);
    }
    void persist(CameraMode mode) override {
        if (fault==4) throw ModeFailure({ModeErrorCode::persistence,28});
        saved=mode;
    }
};
int main() {
    try {
        for (int fault=0;fault<=5;++fault) {
            Fake backend; backend.fault=fault;
            ModeController controller(backend);
            const auto result=controller.set_mode(CameraMode::linear);
            if (fault==0) {
                require(result.success && backend.state.fps==60 && backend.saved==CameraMode::linear);
                const auto switches=backend.stops;
                require(controller.set_mode(CameraMode::linear).success && backend.stops==switches);
                require(controller.set_mode(CameraMode::hdr).success && backend.state.fps==30);
            } else if (fault==1) require(!result.success && backend.stops==0);
            else if (fault==5) require(!result.success && !result.restored && result.restore_error.code==ModeErrorCode::device);
            else require(!result.success && result.restored && backend.state.running &&
                         backend.state.mode==CameraMode::hdr && backend.second==CameraMode::hdr &&
                         backend.state.fps==30 && backend.saved==CameraMode::hdr);
        }
        Fake backend; backend.state.auto_exposure=false;
        ModeController controller(backend);
        require(controller.set_mode(CameraMode::linear).success && !backend.state.auto_exposure);
        std::cout << "mode transaction/recovery checks passed\n";
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
