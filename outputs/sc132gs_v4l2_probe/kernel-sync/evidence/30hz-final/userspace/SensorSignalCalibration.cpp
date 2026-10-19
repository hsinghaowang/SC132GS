#include "SensorSignalCalibration.hpp"
#include "sc132gs-sensor-signal.hpp"
#include <array>

namespace stereo_rtsp::detail {
struct SensorSignalCalibration::Impl {
    int black;
    std::array<std::uint16_t,1024> lut{};
    explicit Impl(bool hdr):black(sc132gs::sensor_signal::black_level(hdr)) {
        for(int i=0;i<1024;++i) lut[i]=sc132gs::sensor_signal::luma10(i,black);
    }
};
SensorSignalCalibration::SensorSignalCalibration(bool hdr):impl_(std::make_unique<Impl>(hdr)) {}
SensorSignalCalibration::~SensorSignalCalibration()=default;
SensorSignalCalibration::SensorSignalCalibration(SensorSignalCalibration&&) noexcept=default;
SensorSignalCalibration& SensorSignalCalibration::operator=(SensorSignalCalibration&&) noexcept=default;
SensorSignalCalibration::ErrorCode SensorSignalCalibration::apply(std::uint16_t* pixels,std::size_t count) const noexcept {
    if(!impl_ || (!pixels && count)) return ErrorCode::invalid_frame;
    for(std::size_t i=0;i<count;++i) if(pixels[i]>1023) return ErrorCode::invalid_frame;
    for(std::size_t i=0;i<count;++i) pixels[i]=impl_->lut[pixels[i]];
    return ErrorCode::none;
}
int SensorSignalCalibration::black_level() const noexcept { return impl_ ? impl_->black : 0; }
}
