#pragma once
#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <variant>
#include <vector>

namespace gs130wi {
enum class ErrorCode { configuration, busy, camera, imu, stopped, timestamp, allocation };
struct Error { ErrorCode code; int system_errno{}; int device_code{}; };
template<class T> using Result=std::variant<T,Error>;
enum class TimestampSource { fsync_host_reference, exposure_midpoint_estimate, exposure_start_estimate };
enum class AssociationState { unverified }; // No ordinal/arrival-time pairing is claimed.
struct Synchronization {
    std::uint64_t camera_session{};
    TimestampSource source{};
    std::uint64_t timestamp_offset_ns{};
    AssociationState imu_association{AssociationState::unverified};
};
struct ImageStatistics {
    int shadow{}, saturation_bp{}, luma_median{-1};
    std::array<unsigned,1024> histogram{};
    // All original RAW CFA samples, before luma conversion or black correction.
    std::uint64_t raw_sample_count{}, raw_near_saturated_count{};
    bool raw_highlights_valid{};
};
struct Image {
    std::uint32_t sequence{}, width{}, height{};
    std::uint64_t monotonic_timestamp_ns{};
    // Exactly one vector is populated. mono10 contains 0..1023 in 16-bit words.
    std::vector<std::uint8_t> mono8;
    std::vector<std::uint16_t> mono10;
    ImageStatistics statistics;
};
struct StereoFrame {
    std::array<Image,2> images;
    Synchronization synchronization;
    StereoFrame()=default;
    StereoFrame(StereoFrame&&) noexcept=default;
    StereoFrame& operator=(StereoFrame&&) noexcept=default;
    StereoFrame(const StereoFrame&)=delete;
    StereoFrame& operator=(const StereoFrame&)=delete;
};
struct ImuSample {
    std::uint64_t index{};
    bool valid{};
    std::uint8_t fifo_header{};
    std::uint16_t timestamp_raw{};
    std::optional<std::uint64_t> sensor_elapsed_ns;
    std::optional<std::uint64_t> fsync_offset_ns;
    std::array<double,3> acceleration_m_s2{}, angular_velocity_rad_s{};
};
struct ImuBatch {
    std::uint64_t host_read_begin_ns{}, host_read_end_ns{};
    std::optional<std::uint64_t> host_interrupt_ns;
    std::vector<ImuSample> samples;
    // Notification/read times are never sample times. No camera interval yet.
    AssociationState association{AssociationState::unverified};
};
struct Options {
    std::string left_device{"/dev/video0"}, right_device{"/dev/video3"};
    std::string imu_device{"/dev/i2c-18"}, imu_gpiochip{"/dev/gpiochip4"};
    unsigned imu_line{24};
    int downscale{1};
    bool ten_bit{true}, enable_imu{true};
};

// One hardware owner per process/session. This API has no ROS/GStreamer types.
// Only 30-Hz kernel-synchronized Linear capture is supported by this facade.
class Capture final {
public:
    class Observer {
    public:
        virtual ~Observer()=default;
        // Runs on the IMU worker, independently of next_frame(). The batch
        // expires on return. False requests stop; do not block/store references.
        virtual bool on_imu_batch(const ImuBatch&) noexcept=0;
    };
    // Observer must outlive Capture including stop/destruction. nullptr is
    // allowed only with enable_imu=false. No sensor is silently ignored.
    static Result<Capture> open(Options, Observer* = nullptr);
    ~Capture();
    Capture(Capture&&) noexcept;
    Capture& operator=(Capture&&) noexcept;
    Capture(const Capture&)=delete;
    Capture& operator=(const Capture&)=delete;
    Result<StereoFrame> next_frame(); // One caller; owning pixels survive QBUF.
    void request_stop() noexcept; // May run concurrently with next_frame().
    std::optional<Error> stop() noexcept; // Join then restore; not concurrent with next_frame().
private:
    struct Impl;
    explicit Capture(std::unique_ptr<Impl>) noexcept;
    std::unique_ptr<Impl> impl_;
};
}
