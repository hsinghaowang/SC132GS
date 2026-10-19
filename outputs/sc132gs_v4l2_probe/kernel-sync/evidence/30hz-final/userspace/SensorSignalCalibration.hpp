#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>

namespace stereo_rtsp::detail {
// Linear black-level calibration for the measured, unbinned SC132GS profile.
// The camera RAW buffer is never modified. No display transfer curve is used.
class SensorSignalCalibration final {
public:
    enum class ErrorCode { none, invalid_frame };
    explicit SensorSignalCalibration(bool hdr);
    ~SensorSignalCalibration();
    SensorSignalCalibration(SensorSignalCalibration&&) noexcept;
    SensorSignalCalibration& operator=(SensorSignalCalibration&&) noexcept;
    SensorSignalCalibration(const SensorSignalCalibration&)=delete;
    SensorSignalCalibration& operator=(const SensorSignalCalibration&)=delete;
    [[nodiscard]] ErrorCode apply(std::uint16_t* pixels,std::size_t count) const noexcept;
    [[nodiscard]] int black_level() const noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}
