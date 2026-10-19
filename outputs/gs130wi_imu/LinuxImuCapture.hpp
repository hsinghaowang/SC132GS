#pragma once
#include "icm42688.hpp"
#include <string>

namespace imu {
struct LinuxCaptureOptions {
    std::string device{"/dev/i2c-18"};
    std::string gpiochip{"/dev/gpiochip4"}; // Empty selects polling.
    unsigned line{24};
    bool fsync_enabled{true};
};
// Linux fd/GPIO/CCI details are private. One owner; serialize read/stop calls.
class LinuxImuCapture final {
public:
    static Result<LinuxImuCapture> open(const LinuxCaptureOptions&);
    ~LinuxImuCapture();
    LinuxImuCapture(LinuxImuCapture&&) noexcept;
    LinuxImuCapture& operator=(LinuxImuCapture&&) noexcept;
    LinuxImuCapture(const LinuxImuCapture&)=delete;
    LinuxImuCapture& operator=(const LinuxImuCapture&)=delete;
    Result<Batch> read_batch();
    Status stop();
private:
    struct Impl;
    explicit LinuxImuCapture(std::unique_ptr<Impl>) noexcept;
    std::unique_ptr<Impl> impl_;
};
}
