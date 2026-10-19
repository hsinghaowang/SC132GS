#include "SensorSignalCalibration.hpp"
#include "sc132gs-sensor-signal.hpp"
#include <array>
#include <type_traits>
#include <cstdlib>
#include <utility>

int main() {
    using Calibration=stereo_rtsp::detail::SensorSignalCalibration;
    static_assert(!std::is_copy_constructible<Calibration>::value);
    for(bool hdr:{false,true}) {
        Calibration calibration(hdr);
        const int black=calibration.black_level();
        std::array<std::uint16_t,1024> ramp{};
        for(int i=0;i<1024;++i) ramp[i]=i;
        if(calibration.apply(ramp.data(),ramp.size())!=Calibration::ErrorCode::none) return 1;
        if(ramp[0]!=0 || ramp[black]!=0 || ramp[1023]!=1023) return 2;
        for(int i=1;i<1024;++i) if(ramp[i]<ramp[i-1]) return 3;
        for(int target=0;target<=100;++target) {
            const int raw=sc132gs::sensor_signal::raw_target(target,black);
            const int signal=ramp[raw];
            if(std::abs(signal-(target*1023+50)/100)>1) return 4;
        }
        // Invalid input must fail before partially modifying a frame.
        std::array<std::uint16_t,2> invalid{{100,1024}};
        if(calibration.apply(invalid.data(),invalid.size())!=Calibration::ErrorCode::invalid_frame || invalid[0]!=100) return 5;
        if(calibration.apply(nullptr,1)!=Calibration::ErrorCode::invalid_frame) return 6;
        Calibration moved(std::move(calibration));
        if(calibration.apply(ramp.data(),ramp.size())!=Calibration::ErrorCode::invalid_frame || moved.black_level()!=black) return 7;
    }
}
