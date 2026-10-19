#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <variant>
#include <vector>

namespace imu {
enum class ErrorCode {
    transport, wrong_device, busy, configuration, packet_format,
    fifo_overflow, timestamp_discontinuity, interrupt_timeout, fsync_missing
};
struct Error {
    ErrorCode code;
    int system_errno{};
    std::uint8_t reg{};
};
template<class T> using Result = std::variant<T, Error>;
using Status = Result<std::monostate>;

// C++17 public transport view; storage remains owned by the caller.
struct MutableBytes {
    std::uint8_t* bytes;
    std::size_t length;
    std::uint8_t* data() const { return bytes; }
    std::size_t size() const { return length; }
    bool empty() const { return length == 0; }
};
struct CaptureConfig {
    bool fsync_enabled{false};
};

// Sensor-relative time and host arrival time intentionally have separate fields.
struct Sample {
    std::array<std::int16_t, 3> acceleration_raw;
    std::array<std::int16_t, 3> angular_velocity_raw;
    std::uint16_t timestamp_raw;
    std::uint64_t sensor_elapsed_ns;
    // FSYNC replaces this packet's ODR timestamp: elapsed is unavailable then.
    bool sensor_time_valid{};
    std::optional<std::uint64_t> fsync_offset_ns;
    std::uint8_t header;
    bool valid;
};
struct Batch {
    std::vector<Sample> samples;
    std::uint64_t host_read_begin_ns{};
    std::uint64_t host_read_end_ns{};
    std::optional<std::uint64_t> host_interrupt_ns;
    std::uint16_t fifo_bytes_before_read{};
};

class Icm42688 final {
public:
    // Single owner/thread. Serialize calls externally. A moved-from object may
    // only be destroyed or assigned. Destruction requires live dependencies.
    // Necessary transport is injected and must outlive the sensor.
    class Registers {
    public:
        virtual ~Registers() = default;
        virtual Status read(std::uint8_t reg, MutableBytes) = 0;
        virtual Status write(std::uint8_t reg, std::uint8_t value) = 0;
        virtual std::uint64_t monotonic_ns() const = 0;
    };
    // Optional notification source; it does not perform sensor register access.
    class Interrupt {
    public:
        virtual ~Interrupt() = default;
        virtual Result<std::uint64_t> wait(int timeout_ms) = 0;
    };

    explicit Icm42688(Registers&, Interrupt* = nullptr);
    ~Icm42688();
    Icm42688(Icm42688&&) noexcept;
    Icm42688& operator=(Icm42688&&) noexcept;
    Icm42688(const Icm42688&) = delete;
    Icm42688& operator=(const Icm42688&) = delete;

    Status start(CaptureConfig = {}); // 200 Hz, +/-4 g, +/-500 deg/s.
    Result<Batch> read_batch();
    Status stop(); // Restores saved configuration; destructor also attempts it.
private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace imu
