#include "gs130wi/Capture.hpp"
#include "StereoCapture.hpp"
#include "CaptureError.hpp"
#include "KernelSyncStatus.hpp"
#include "LinuxImuCapture.hpp"
#include <atomic>
#include <cerrno>
#include <chrono>
#include <fcntl.h>
#include <mutex>
#include <stop_token>
#include <sys/file.h>
#include <thread>
#include <unistd.h>

namespace gs130wi {
namespace {
struct Fault { Error error; };
Error imu_error(const imu::Error& e) { return {ErrorCode::imu,e.system_errno,int(e.code)}; }
}
struct Capture::Impl {
    Options options;
    Observer* observer;
    int ownership_fd{-1};
    std::stop_source cancellation;
    std::mutex error_mutex;
    std::optional<Error> worker_error;
    std::optional<Error> stop_error;
    std::unique_ptr<imu::LinuxImuCapture> inertial;
    std::unique_ptr<stereo_rtsp::StereoCapture> camera;
    std::optional<stereo_rtsp::sync::StatusReader> status;
    std::uint64_t camera_session{}, sample_index{};
    std::thread worker;
    bool closed{};
    Impl(Options opts, Observer* sink) : options(std::move(opts)), observer(sink) {}
    ~Impl() { (void)stop(); }
    void start() {
        if(options.left_device==options.right_device ||
           (options.downscale!=1 && options.downscale!=2 && options.downscale!=4) ||
           (options.enable_imu && !observer))throw Fault{{ErrorCode::configuration}};
        ownership_fd=::open("/run/lock/gs130wi-capture.lock",O_CREAT|O_RDWR|O_CLOEXEC,0600);
        if(ownership_fd<0)throw Fault{{ErrorCode::busy,errno}};
        if(::flock(ownership_fd,LOCK_EX|LOCK_NB))throw Fault{{ErrorCode::busy,errno}};
        if(options.enable_imu) {
            auto result=imu::LinuxImuCapture::open({options.imu_device,options.imu_gpiochip,options.imu_line,true});
            if(const auto* e=std::get_if<imu::Error>(&result))throw Fault{imu_error(*e)};
            inertial=std::make_unique<imu::LinuxImuCapture>(std::get<imu::LinuxImuCapture>(std::move(result)));
            worker=std::thread([this] { read_imu(); });
        }
        camera=std::make_unique<stereo_rtsp::StereoCapture>(options.left_device,options.right_device,
            options.downscale,30,false,stereo_rtsp::CaptureMode::external_trigger,options.ten_bit);
        auto reader=stereo_rtsp::sync::StatusReader::open("/sys/bus/platform/devices/acb3000.camss/fsync_control");
        if(const auto* e=std::get_if<stereo_rtsp::sync::Error>(&reader))throw Fault{{ErrorCode::timestamp,e->system_errno}};
        status.emplace(std::get<stereo_rtsp::sync::StatusReader>(std::move(reader)));
        camera_session=read_status().session;
    }
    stereo_rtsp::sync::Status read_status() {
        auto result=status->read();
        if(const auto* e=std::get_if<stereo_rtsp::sync::Error>(&result))throw Fault{{ErrorCode::timestamp,e->system_errno}};
        const auto state=std::get<stereo_rtsp::sync::Status>(result);
        if(state.mode!=2 || !state.running || state.driver_error ||
           (camera_session && state.session!=camera_session))throw Fault{{ErrorCode::timestamp}};
        return state;
    }
    void fail(Error error) {
        { std::lock_guard guard(error_mutex); if(!worker_error)worker_error=error; }
        cancellation.request_stop();
    }
    void read_imu() noexcept {
        try {
            while(!cancellation.stop_requested()) {
                auto result=inertial->read_batch();
                if(const auto* e=std::get_if<imu::Error>(&result)) {
                    if(!cancellation.stop_requested())fail(imu_error(*e));
                    break;
                }
                const auto& raw=std::get<imu::Batch>(result);
                ImuBatch batch;
                batch.host_read_begin_ns=raw.host_read_begin_ns;
                batch.host_read_end_ns=raw.host_read_end_ns;
                batch.host_interrupt_ns=raw.host_interrupt_ns;
                batch.samples.reserve(raw.samples.size());
                for(const auto& value:raw.samples) {
                    ImuSample sample;
                    sample.index=sample_index++;
                    sample.valid=value.valid;
                    sample.fifo_header=value.header;
                    sample.timestamp_raw=value.timestamp_raw;
                    if(value.sensor_time_valid)sample.sensor_elapsed_ns=value.sensor_elapsed_ns;
                    sample.fsync_offset_ns=value.fsync_offset_ns;
                    for(unsigned axis=0;axis<3;++axis) {
                        sample.acceleration_m_s2[axis]=double(value.acceleration_raw[axis])*9.80665/8192;
                        sample.angular_velocity_rad_s[axis]=double(value.angular_velocity_raw[axis])*
                            (500.0/32768)*(3.14159265358979323846/180);
                    }
                    batch.samples.push_back(sample);
                }
                if(!observer->on_imu_batch(batch))cancellation.request_stop();
                if(options.imu_gpiochip.empty())std::this_thread::sleep_for(std::chrono::milliseconds(5));
            }
        } catch(const std::bad_alloc&) { fail({ErrorCode::allocation,ENOMEM}); }
          catch(...) { fail({ErrorCode::imu}); }
    }
    Result<StereoFrame> next() {
        { std::lock_guard guard(error_mutex); if(worker_error)return *worker_error; }
        if(closed || cancellation.stop_requested())return Error{ErrorCode::stopped};
        auto pair=camera->next(cancellation.get_token());
        if(cancellation.stop_requested()) {
            std::lock_guard guard(error_mutex);
            return worker_error.value_or(Error{ErrorCode::stopped});
        }
        const auto state=read_status();
        if(pair.cam0_timestamp_ns<=0 || pair.cam0_timestamp_ns!=pair.cam1_timestamp_ns)
            return Error{ErrorCode::timestamp};
        StereoFrame frame;
        frame.synchronization.camera_session=state.session;
        frame.synchronization.timestamp_offset_ns=state.timestamp_offset_ns;
        frame.synchronization.source=static_cast<TimestampSource>(state.source);
        for(unsigned eye=0;eye<2;++eye) {
            auto& image=frame.images[eye];
            image.width=1088/options.downscale;
            image.height=1280/options.downscale;
            image.sequence=eye?pair.cam1_sequence:pair.cam0_sequence;
            image.monotonic_timestamp_ns=static_cast<std::uint64_t>(pair.cam0_timestamp_ns);
            image.mono8=eye?std::move(pair.right_luma):std::move(pair.left_luma);
            image.mono10=eye?std::move(pair.right_luma10):std::move(pair.left_luma10);
            const auto& meter=eye?pair.right_hdr:pair.left_hdr;
            image.statistics={meter.shadow,meter.saturation_bp,meter.luma_median,meter.histogram};
            const auto& highlights=eye?pair.right_highlights:pair.left_highlights;
            image.statistics.raw_sample_count=highlights.sample_count;
            image.statistics.raw_near_saturated_count=highlights.near_saturated_count;
            image.statistics.raw_highlights_valid=highlights.valid;
        }
        return frame;
    }
    std::optional<Error> stop() noexcept {
        if(closed)return stop_error;
        cancellation.request_stop();
        if(worker.joinable())worker.join();
        camera.reset();
        if(inertial) {
            const auto result=inertial->stop();
            if(const auto* e=std::get_if<imu::Error>(&result))stop_error=imu_error(*e);
            inertial.reset();
        }
        status.reset();
        if(ownership_fd>=0) { ::close(ownership_fd); ownership_fd=-1; }
        closed=true;
        return stop_error;
    }
};
Capture::Capture(std::unique_ptr<Impl> impl) noexcept : impl_(std::move(impl)) {}
Capture::~Capture()=default;
Capture::Capture(Capture&&) noexcept=default;
Capture& Capture::operator=(Capture&&) noexcept=default;
Result<Capture> Capture::open(Options options, Observer* observer) {
    try {
        auto impl=std::make_unique<Impl>(std::move(options),observer);
        impl->start();
        return Capture(std::move(impl));
    } catch(const Fault& fault) { return fault.error; }
      catch(const std::bad_alloc&) { return Error{ErrorCode::allocation,ENOMEM}; }
      catch(const stereo_rtsp::detail::CaptureError& e) { return Error{ErrorCode::camera,0,int(e.code)}; }
      catch(...) { return Error{ErrorCode::camera,errno}; }
}
Result<StereoFrame> Capture::next_frame() {
    try { return impl_->next(); }
    catch(const Fault& fault) { impl_->fail(fault.error); return fault.error; }
    catch(const stereo_rtsp::detail::CaptureError& e) {
        const Error error{ErrorCode::camera,0,int(e.code)}; impl_->fail(error); return error;
    } catch(const std::bad_alloc&) { const Error e{ErrorCode::allocation,ENOMEM}; impl_->fail(e); return e; }
      catch(...) { const Error e{ErrorCode::camera,errno}; impl_->fail(e); return e; }
}
void Capture::request_stop() noexcept { if(impl_)impl_->cancellation.request_stop(); }
std::optional<Error> Capture::stop() noexcept { return impl_?impl_->stop():std::nullopt; }
}
