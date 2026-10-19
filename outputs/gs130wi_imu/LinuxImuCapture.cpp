#include "LinuxImuCapture.hpp"
#include "LinuxImuTransport.hpp"
#include <new>

namespace imu {
struct LinuxImuCapture::Impl {
    linux_detail::LinuxRegisters registers;
    std::unique_ptr<linux_detail::GpioInterrupt> interrupt;
    Icm42688 sensor;
    explicit Impl(const LinuxCaptureOptions& options)
        : registers(options.device),
          interrupt(options.gpiochip.empty()?nullptr:
              std::make_unique<linux_detail::GpioInterrupt>(options.gpiochip,options.line)),
          sensor(registers,interrupt.get()) {
        const auto status=sensor.start({options.fsync_enabled});
        if(const auto* error=std::get_if<Error>(&status))throw linux_detail::Failure{*error};
    }
};
LinuxImuCapture::LinuxImuCapture(std::unique_ptr<Impl> impl) noexcept : impl_(std::move(impl)) {}
LinuxImuCapture::~LinuxImuCapture()=default;
LinuxImuCapture::LinuxImuCapture(LinuxImuCapture&&) noexcept=default;
LinuxImuCapture& LinuxImuCapture::operator=(LinuxImuCapture&&) noexcept=default;
Result<LinuxImuCapture> LinuxImuCapture::open(const LinuxCaptureOptions& options) {
    try { return LinuxImuCapture(std::make_unique<Impl>(options)); }
    catch(const linux_detail::Failure& failure) { return failure.error; }
    catch(const std::bad_alloc&) { return Error{ErrorCode::transport,ENOMEM}; }
}
Result<Batch> LinuxImuCapture::read_batch() { return impl_->sensor.read_batch(); }
Status LinuxImuCapture::stop() { return impl_->sensor.stop(); }
}
