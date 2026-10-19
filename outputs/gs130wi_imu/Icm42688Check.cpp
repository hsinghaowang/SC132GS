#include "icm42688.hpp"

#include <algorithm>
#include <iostream>
#include <stdexcept>

namespace {
void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
void ok(imu::Status status) {
    require(std::holds_alternative<std::monostate>(status), "unexpected driver error");
}
class Registers final : public imu::Icm42688::Registers {
public:
    std::array<std::array<std::uint8_t,128>,2> banks{};
    unsigned bank{};
    std::vector<std::uint8_t> fifo;
    bool fail_pin_read{};
    bool fail_pin_write{};
    bool overflow{};
    Registers() {
        banks[0][0x75]=0x47;
        banks[0][0x54]=0x23;
        banks[0][0x62]=0x13;
        banks[1][0x7b]=0xa0;
    }
    imu::Status read(std::uint8_t reg, imu::MutableBytes data) override {
        if (bank==1 && reg==0x7b && fail_pin_read) {
            fail_pin_read=false;
            return imu::Error{imu::ErrorCode::transport};
        }
        if (reg==0x76) { *data.data()=static_cast<std::uint8_t>(bank); return {}; }
        if (!bank && reg==0x2e) {
            data.data()[0]=static_cast<std::uint8_t>(fifo.size()>>8);
            data.data()[1]=static_cast<std::uint8_t>(fifo.size());
        } else if (!bank && reg==0x30) {
            require(data.size()<=12 && data.size()<=fifo.size(), "invalid partial read");
            std::copy_n(fifo.begin(),data.size(),data.data());
            fifo.erase(fifo.begin(),fifo.begin()+data.size());
        } else if (!bank && reg==0x2d) {
            *data.data()=overflow?2:0;
        } else {
            std::copy_n(banks[bank].begin()+reg,data.size(),data.data());
        }
        return {};
    }
    imu::Status write(std::uint8_t reg, std::uint8_t value) override {
        if (bank==1 && reg==0x7b && fail_pin_write) {
            fail_pin_write=false;
            return imu::Error{imu::ErrorCode::transport};
        }
        if (reg==0x76) { require(value<2,"invalid bank"); bank=value; }
        else banks[bank][reg]=value;
        return {};
    }
    std::uint64_t monotonic_ns() const override { return 1000000000; }
    void packet(std::uint8_t header, std::uint16_t stamp) {
        const auto base=fifo.size();
        fifo.resize(base+16);
        fifo[base]=header;
        fifo[base+14]=static_cast<std::uint8_t>(stamp>>8);
        fifo[base+15]=static_cast<std::uint8_t>(stamp);
    }
};
imu::Batch batch(imu::Icm42688& sensor) {
    auto result=sensor.read_batch();
    require(std::holds_alternative<imu::Batch>(result),"unexpected read error");
    return std::get<imu::Batch>(std::move(result));
}
void error(imu::Result<imu::Batch> result, imu::ErrorCode code) {
    const auto* e=std::get_if<imu::Error>(&result);
    require(e && e->code==code,"wrong error classification");
}
}
int main() {
    try {
        {
            Registers bus;
            const auto original=bus.banks;
            imu::Icm42688 sensor(bus);
            ok(sensor.start({true}));
            require(bus.banks[1][0x7b]==0xa2,"FSYNC mux not selected");
            require((bus.banks[0][0x54]&0x1f)==3,"wrong timestamp profile");
            require(bus.banks[0][0x5f]==0x4f,"missing FIFO FSYNC enable");
            require(bus.banks[0][0x62]==0x10,"wrong FSYNC polarity/tagging");
            bus.packet(0x68,65000);
            bus.packet(0x6c,1125);
            const auto first=batch(sensor);
            require(first.samples.size()==2,"samples lost");
            require(first.samples[0].sensor_time_valid,"normal counter missing");
            require(!first.samples[1].sensor_time_valid,"FSYNC offset used as counter");
            require(first.samples[1].fsync_offset_ns==1200000,"wrong FSYNC scale");
            bus.packet(0x68,8840); // 65000 + 2*4688, wrapping at 65536.
            const auto second=batch(sensor);
            require(second.samples[0].sensor_elapsed_ns==10001066,"counter bridge/wrap failed");
            bus.packet(0x68,13527);
            require(batch(sensor).samples[0].sensor_elapsed_ns==15000533,"counter continuity failed");
            ok(sensor.stop());
            // SIGNAL_PATH_RESET (0x4b) is a command, not saved configuration.
            bus.banks[0][0x4b]=original[0][0x4b];
            require(bus.bank==0 && bus.banks==original,"configuration not restored");
        }
        {
            Registers bus;
            imu::Icm42688 sensor(bus);
            ok(sensor.start());
            bus.packet(0x6c,100);
            error(sensor.read_batch(),imu::ErrorCode::packet_format);
            ok(sensor.stop());
        }
        {
            Registers bus;
            imu::Icm42688 sensor(bus);
            ok(sensor.start({true}));
            bus.packet(0x68,1000);
            (void)batch(sensor);
            bus.packet(0x6c,200);
            bus.packet(0x68,30000); // A gap must not become an invented sample time.
            error(sensor.read_batch(),imu::ErrorCode::timestamp_discontinuity);
            ok(sensor.stop());
        }
        {
            Registers bus;
            const auto original=bus.banks;
            bus.fail_pin_read=true;
            imu::Icm42688 sensor(bus);
            require(std::holds_alternative<imu::Error>(sensor.start({true})),"injected failure missed");
            require(bus.bank==0 && bus.banks==original,"failed banked start corrupted state");
        }
        {
            Registers bus;
            const auto original=bus.banks;
            bus.fail_pin_write=true;
            imu::Icm42688 sensor(bus);
            require(std::holds_alternative<imu::Error>(sensor.start({true})),"injected write failure missed");
            require(bus.bank==0 && bus.banks==original,"failed banked write corrupted state");
        }
        {
            Registers bus;
            imu::Icm42688 sensor(bus);
            ok(sensor.start({true}));
            bus.overflow=true;
            error(sensor.read_batch(),imu::ErrorCode::fifo_overflow);
            ok(sensor.stop());
        }
        {
            Registers bus;
            imu::Icm42688 sensor(bus);
            ok(sensor.start({true}));
            bus.packet(0x68,1000);
            bus.packet(0x6c,10);
            bus.packet(0x6c,4697);
            bus.packet(0x68,15063);
            const auto data=batch(sensor);
            require(data.samples.size()==4 && data.samples[3].sensor_elapsed_ns==15000533,
                    "adjacent FSYNC packets lost or mistaken for counter");
            ok(sensor.stop());
        }
        {
            Registers bus;
            imu::Icm42688 sensor(bus);
            ok(sensor.start({true}));
            for (unsigned i=0;i<9;++i)bus.packet(0x6c,100);
            error(sensor.read_batch(),imu::ErrorCode::timestamp_discontinuity);
            ok(sensor.stop());
        }
        std::cout<<"FSYNC parsing, counter bridge/wrap, rejection, overflow and restoration passed\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr<<e.what()<<'\n';
        return 1;
    }
}
