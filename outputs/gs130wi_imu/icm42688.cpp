#include "icm42688.hpp"

#include <algorithm>
#include <chrono>
#include <thread>
#include <utility>

namespace imu {
namespace {
struct Failure { Error error; };
void check(Status result) {
    if (auto* e = std::get_if<Error>(&result)) throw Failure{*e};
}
std::uint16_t be16(const std::uint8_t* p) {
    return static_cast<std::uint16_t>((unsigned(p[0]) << 8) | p[1]);
}
std::int16_t signed16(const std::uint8_t* p) {
    const auto n = be16(p);
    return static_cast<std::int16_t>(n < 32768 ? int(n) : int(n) - 65536);
}
}

class Icm42688::Impl {
public:
    Registers& bus;
    Interrupt* interrupt;
    // FIFO and power are restored separately in safe order.
    static constexpr std::array<std::uint8_t, 15> saved_regs{
        0x14,0x16,0x4c,0x4d,0x4e,0x4f,0x50,0x54,0x5f,0x60,0x61,0x63,0x64,0x65,0x62};
    std::array<std::uint8_t, saved_regs.size()> saved{};
    bool restore_needed{};
    bool started{};
    bool have_timestamp{};
    std::uint16_t previous{};
    std::uint64_t ticks{};
    CaptureConfig config{};
    std::optional<std::uint8_t> saved_pin9;
    unsigned skipped_timestamps{};

    Impl(Registers& r, Interrupt* i) : bus(r), interrupt(i) {}
    ~Impl() { (void)stop(); }
    std::uint8_t read1(std::uint8_t reg) {
        std::uint8_t value{};
        check(bus.read(reg, {&value,1}));
        return value;
    }
    void write(std::uint8_t reg, std::uint8_t value) { check(bus.write(reg,value)); }

    Status start(CaptureConfig requested) {
        if (started) return Error{ErrorCode::busy};
        if (restore_needed) return Error{ErrorCode::configuration};
        try {
            if (read1(0x76) != 0) return Error{ErrorCode::configuration,0,0x76};
            if (read1(0x75) != 0x47) return Error{ErrorCode::wrong_device,0,0x75};
            // Avoid taking ownership from an already active sensor/FIFO user.
            if ((read1(0x4e) & 0x0f) || (read1(0x16) & 0xc0))
                return Error{ErrorCode::busy};
            for (std::size_t n=0;n<saved_regs.size();++n) saved[n]=read1(saved_regs[n]);
            restore_needed=true;
            config=requested;
            if (config.fsync_enabled) {
                write(0x76,1);
                saved_pin9=read1(0x7b);
                const auto mux=static_cast<std::uint8_t>((*saved_pin9 & ~0x06) | 0x02);
                write(0x7b,mux); // PIN9 is FSYNC input, not INT2 output.
                if (read1(0x7b)!=mux) throw Failure{{ErrorCode::configuration,0,0x7b}};
                write(0x76,0);
            }
            write(0x65,0); // Disable INT1 sources while configuring.
            write(0x16,0); // FIFO bypass.
            write(0x4c,static_cast<std::uint8_t>((saved[2] & 0x0f) | 0x30));
            write(0x4d,static_cast<std::uint8_t>(saved[3] & ~0x04)); // Internal clock.
            write(0x4f,0x47); // +/-500 dps, 200 Hz.
            write(0x50,0x47); // +/-4 g, 200 Hz.
            // Preserve reserved bits. Absolute ODR timestamp, 1-us setting,
            // Keep absolute ODR counter mode. FSYNC packets replace, rather
            // than extend, the timestamp field. Never unwrap their offset.
            const auto tmst=static_cast<std::uint8_t>((saved[7] & 0xe0) |
                                                     (config.fsync_enabled?0x03:0x01));
            write(0x54,tmst);
            if (config.fsync_enabled)
                write(0x62,static_cast<std::uint8_t>((saved[14] & 0x8c) | 0x10));
            const auto fifo_config=static_cast<std::uint8_t>((interrupt?0x67:0x47) |
                                                           (config.fsync_enabled?0x08:0));
            // Re-evaluate watermark on each ODR in IRQ mode. While draining,
            // new samples may keep FIFO above threshold across status clearing.
            write(0x5f,fifo_config); // Resume partial reads, accel + gyro + temperature.
            write(0x60,64); // Four complete 16-byte packets per watermark.
            write(0x61,0);
            if (interrupt) {
                write(0x14,static_cast<std::uint8_t>((saved[0] & 0xf8) | 0x07));
                write(0x63,static_cast<std::uint8_t>(saved[11] & 0xf0));
                write(0x64,static_cast<std::uint8_t>(saved[12] & ~0x10));
            }
            write(0x4e,static_cast<std::uint8_t>((saved[4] & 0x30) | 0x0f));
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            write(0x4b,0x02); // Flush FIFO, not a full device reset.
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
            (void)read1(0x2d);
            // Verify the profile before allowing samples to be published.
            for (auto [reg,value] : {std::pair{0x4f,0x47}, {0x50,0x47}, {0x54,int(tmst)},
                                    {0x5f,int(fifo_config)}})
                if (read1(static_cast<std::uint8_t>(reg)) != value)
                    throw Failure{{ErrorCode::configuration,0,static_cast<std::uint8_t>(reg)}};
            if (config.fsync_enabled && read1(0x62)!=((saved[14] & 0x8c) | 0x10))
                throw Failure{{ErrorCode::configuration,0,0x62}};
            have_timestamp=false;
            ticks=0;
            skipped_timestamps=0;
            write(0x16,0x80); // Stop on full: overflow is an explicit error.
            if (interrupt) write(0x65,0x04);
            started=true;
            return std::monostate{};
        } catch (const Failure& f) {
            const auto restored=stop();
            if (auto* e=std::get_if<Error>(&restored)) return *e;
            return f.error;
        }
    }

    Result<Batch> read_batch() {
        if (!started) return Error{ErrorCode::configuration};
        try {
            Batch batch;
            if (interrupt) {
                auto event=interrupt->wait(500);
                if (auto* e=std::get_if<Error>(&event)) return *e;
                batch.host_interrupt_ns=std::get<std::uint64_t>(event);
            }
            batch.host_read_begin_ns=bus.monotonic_ns();
            std::array<std::uint8_t,2> count{};
            check(bus.read(0x2e,{count.data(),count.size()}));
            const auto bytes=be16(count.data());
            batch.fifo_bytes_before_read=bytes;
            if (bytes >= 2048) return Error{ErrorCode::fifo_overflow,0,0x2e};
            if (bytes % 16) return Error{ErrorCode::packet_format,0,0x2e};
            std::vector<std::uint8_t> raw(bytes);
            // Transport reads FIFO_DATA with partial-read continuation enabled;
            // the chip resumes at the next unread byte, even inside a packet.
            for (std::size_t p=0;p<raw.size();p+=12)
                check(bus.read(0x30,{raw.data()+p,std::min<std::size_t>(12,raw.size()-p)}));
            batch.host_read_end_ns=bus.monotonic_ns();
            const auto status=read1(0x2d); // Clear latched interrupt after drain.
            std::array<std::uint8_t,2> lost{};
            check(bus.read(0x6c,{lost.data(),lost.size()}));
            if ((status & 0x02) || be16(lost.data()))
                return Error{ErrorCode::fifo_overflow,0,0x6c};
            for (std::size_t p=0;p<raw.size();p+=16) {
                const auto* b=raw.data()+p;
                const bool fsync=(b[0] & 0xfc)==0x6c;
                if ((b[0] & 0xfc) != 0x68 && !(config.fsync_enabled && fsync))
                    return Error{ErrorCode::packet_format,0,0x30};
                const auto stamp=be16(b+14);
                if (!fsync && have_timestamp) {
                    const auto delta=static_cast<std::uint16_t>(stamp-previous);
                    // 200 Hz should be around 4687/4688 internal timestamp ticks.
                    // Do not silently synthesize times when packets are missing.
                    const auto intervals=skipped_timestamps+1;
                    if (delta < 4000*intervals || delta > 5500*intervals)
                        return Error{ErrorCode::timestamp_discontinuity,0,0x30};
                    ticks+=delta;
                }
                Sample sample{};
                sample.timestamp_raw=stamp;
                if (fsync) {
                    // 30-Hz FSYNC and 200-Hz ODR: more than eight consecutive
                    // replacements is unsupported; avoid ambiguous wraps.
                    if (++skipped_timestamps>8)
                        return Error{ErrorCode::timestamp_discontinuity,0,0x30};
                    sample.fsync_offset_ns=std::uint64_t(stamp)*32000/30;
                } else {
                    previous=stamp;
                    have_timestamp=true;
                    skipped_timestamps=0;
                    sample.sensor_elapsed_ns=ticks*32000/30;
                    sample.sensor_time_valid=true;
                }
                sample.header=b[0];
                sample.valid=true;
                for (std::size_t axis=0;axis<3;++axis) {
                    sample.acceleration_raw[axis]=signed16(b+1+axis*2);
                    sample.angular_velocity_raw[axis]=signed16(b+7+axis*2);
                    if (sample.acceleration_raw[axis]==-32768 || sample.angular_velocity_raw[axis]==-32768)
                        sample.valid=false;
                }
                batch.samples.push_back(sample);
            }
            return batch;
        } catch (const Failure& f) { return f.error; }
    }

    Status stop() noexcept {
        if (!restore_needed) return std::monostate{};
        // A failed banked operation may leave bank 1 selected. Never restore
        // bank-0 addresses into another bank.
        auto bank0=bus.write(0x76,0);
        if (auto* e=std::get_if<Error>(&bank0)) return *e;
        std::optional<Error> first;
        auto attempt=[&](std::uint8_t reg,std::uint8_t value) {
            auto r=bus.write(reg,value);
            if (auto* e=std::get_if<Error>(&r); e && !first) first=*e;
        };
        attempt(0x65,0);
        attempt(0x16,0);
        attempt(0x4e,0);
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
        if (saved_pin9) {
            const auto bank1=bus.write(0x76,1);
            if (auto* e=std::get_if<Error>(&bank1)) {
                if (!first) first=*e;
            } else {
                attempt(0x7b,*saved_pin9);
                std::uint8_t value{};
                auto r=bus.read(0x7b,{&value,1});
                if (auto* e=std::get_if<Error>(&r); e && !first) first=*e;
                if (std::holds_alternative<std::monostate>(r) && value!=*saved_pin9 && !first)
                    first=Error{ErrorCode::configuration,0,0x7b};
            }
            bank0=bus.write(0x76,0);
            if (auto* e=std::get_if<Error>(&bank0)) return *e;
        }
        for (std::size_t n=0;n<saved_regs.size();++n) {
            const auto reg=saved_regs[n];
            if (reg!=0x16 && reg!=0x4e && reg!=0x65) attempt(reg,saved[n]);
        }
        attempt(0x4e,saved[4]);
        attempt(0x16,saved[1]);
        attempt(0x65,saved[13]);
        for (std::size_t n=0;n<saved_regs.size();++n) {
            std::uint8_t value{};
            auto r=bus.read(saved_regs[n],{&value,1});
            if (auto* e=std::get_if<Error>(&r); e && !first) first=*e;
            if (std::holds_alternative<std::monostate>(r) && value!=saved[n] && !first)
                first=Error{ErrorCode::configuration,0,saved_regs[n]};
        }
        started=false;
        restore_needed=first.has_value();
        if (!restore_needed) saved_pin9.reset();
        if (first) return *first;
        return std::monostate{};
    }
};
Icm42688::Icm42688(Registers& r,Interrupt* i):impl_(std::make_unique<Impl>(r,i)){}
Icm42688::~Icm42688()=default;
Icm42688::Icm42688(Icm42688&&) noexcept=default;
Icm42688& Icm42688::operator=(Icm42688&&) noexcept=default;
Status Icm42688::start(CaptureConfig config){return impl_->start(config);}
Result<Batch> Icm42688::read_batch(){return impl_->read_batch();}
Status Icm42688::stop(){return impl_->stop();}
} // namespace imu
