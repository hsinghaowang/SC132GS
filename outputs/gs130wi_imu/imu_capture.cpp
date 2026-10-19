#include "icm42688.hpp"
#include "LinuxImuTransport.hpp"

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstring>
#include <fcntl.h>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <linux/gpio.h>
#include <linux/i2c.h>
#include <linux/i2c-dev.h>
#include <poll.h>
#include <stdexcept>
#include <string>
#include <sys/file.h>
#include <sys/ioctl.h>
#include <thread>
#include <time.h>
#include <unistd.h>

namespace {
using imu::linux_detail::Failure;
volatile std::sig_atomic_t interrupted{};
void on_signal(int) { interrupted=1; }
using imu::linux_detail::monotonic_ns;
using imu::linux_detail::LinuxRegisters;
using imu::linux_detail::GpioInterrupt;
void check(imu::Status status){if(auto* e=std::get_if<imu::Error>(&status))throw Failure{*e};}
const char* name(imu::ErrorCode code) {
    switch(code){
    case imu::ErrorCode::transport:return "transport";
    case imu::ErrorCode::wrong_device:return "wrong_device";
    case imu::ErrorCode::busy:return "busy";
    case imu::ErrorCode::configuration:return "configuration";
    case imu::ErrorCode::packet_format:return "packet_format";
    case imu::ErrorCode::fifo_overflow:return "fifo_overflow";
    case imu::ErrorCode::timestamp_discontinuity:return "timestamp_discontinuity";
    case imu::ErrorCode::interrupt_timeout:return "interrupt_timeout";
    case imu::ErrorCode::fsync_missing:return "fsync_missing";
    }
    return "unknown";
}
}

int main(int argc,char** argv) {
    std::signal(SIGINT,on_signal);
    std::signal(SIGTERM,on_signal);
    try {
        std::string device="/dev/i2c-18",gpiochip;
        unsigned line=24;
        int seconds=10,stall_ms=0;
        bool benchmark=false;
        bool fsync=false;
        bool gpio_check=false;
        bool continue_fifo=true;
        bool gpio_line_set=false;
        for(int i=1;i<argc;++i){
            const std::string option=argv[i];
            if(option=="--benchmark"){benchmark=true;continue;}
            if(option=="--fsync"){fsync=true;continue;}
            if(option=="--gpio-check"){gpio_check=true;continue;}
            if(option=="--readdress-fifo"){continue_fifo=false;continue;}
            if(option=="--help"){
                std::cout<<"gs130wi-imu [--device /dev/i2c-N] [--seconds N] [--gpiochip /dev/gpiochipN --line N] [--fsync] [--stall-ms N] [--benchmark] [--readdress-fifo] [--gpio-check]\n"
                    <<"CSV on stdout, verification summary on stderr. Default: polling FIFO, 200 Hz.\n";
                return 0;
            }
            if(i+1==argc)throw std::invalid_argument("missing value");
            const std::string value=argv[++i];
            if(option=="--device")device=value;
            else if(option=="--seconds")seconds=std::stoi(value);
            else if(option=="--gpiochip")gpiochip=value;
            else if(option=="--line"){line=static_cast<unsigned>(std::stoul(value));gpio_line_set=true;}
            else if(option=="--stall-ms")stall_ms=std::stoi(value);
            else throw std::invalid_argument("unknown option");
        }
        if(seconds<1 || seconds>86400 || stall_ms<0 || stall_ms>5000 || gpiochip.empty()!=!gpio_line_set)
            throw std::invalid_argument("invalid capture options");
        if(gpio_check){
            if(gpiochip.empty())throw std::invalid_argument("GPIO check requires chip and line");
            GpioInterrupt gpio(gpiochip,line);
            std::cout<<"GPIO input/edge request succeeded; current level="<<gpio.value()
                <<". This does not verify external wiring or interrupt timing.\n";
            return 0;
        }
        LinuxRegisters bus(device,continue_fifo);
        if(benchmark){
            for(std::size_t length:{1u,6u,12u}){
                std::array<std::uint8_t,12> data{};
                const auto start=monotonic_ns();
                for(int n=0;n<100;++n)check(bus.read(0x1f,{data.data(),length}));
                std::cerr<<"read_bytes="<<length<<" average_transfer_us="<<double(monotonic_ns()-start)/100000<<'\n';
            }
            return 0;
        }
        std::unique_ptr<GpioInterrupt> gpio;
        if(!gpiochip.empty())gpio=std::make_unique<GpioInterrupt>(gpiochip,line);
        imu::Icm42688 sensor(bus,gpio.get());
        check(sensor.start({fsync}));
        const auto begin=monotonic_ns();
        const auto end=begin+std::uint64_t(seconds)*1000000000;
        std::uint64_t samples=0,valid=0,wraps=0,last_elapsed=0,min_delta=UINT64_MAX,max_delta=0,first_read=0,last_read=0;
        std::uint16_t last_raw=0,max_fifo=0;
        bool stalled=false;
        bool have_counter=false;
        std::uint64_t counter_index=0,first_counter_index=0,last_counter_index=0,fsync_samples=0;
        std::uint64_t fsync_min_ns=UINT64_MAX,fsync_max_ns=0;
        std::cout<<"index,valid,header,timestamp_raw,sensor_elapsed_ns,host_read_begin_ns,host_read_end_ns,host_interrupt_ns,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,sensor_time_valid,fsync_offset_ns\n";
        std::cout<<std::setprecision(10);
        while(!interrupted && monotonic_ns()<end){
            if(!stalled && stall_ms && monotonic_ns()-begin>500000000){
                stalled=true;
                std::this_thread::sleep_for(std::chrono::milliseconds(stall_ms));
            }
            auto result=sensor.read_batch();
            if(auto* e=std::get_if<imu::Error>(&result)){
                if(interrupted)break;
                throw Failure{*e};
            }
            const auto& batch=std::get<imu::Batch>(result);
            max_fifo=std::max(max_fifo,batch.fifo_bytes_before_read);
            for(const auto& s:batch.samples){
                if(s.sensor_time_valid){
                    if(have_counter){
                        const auto delta=(s.sensor_elapsed_ns-last_elapsed)/(samples-counter_index);
                        min_delta=std::min(min_delta,delta);max_delta=std::max(max_delta,delta);
                        if(s.timestamp_raw<last_raw)++wraps;
                    }else first_counter_index=samples;
                    have_counter=true;
                    counter_index=last_counter_index=samples;
                    last_raw=s.timestamp_raw;last_elapsed=s.sensor_elapsed_ns;
                }
                if(s.fsync_offset_ns){
                    ++fsync_samples;
                    fsync_min_ns=std::min(fsync_min_ns,*s.fsync_offset_ns);
                    fsync_max_ns=std::max(fsync_max_ns,*s.fsync_offset_ns);
                }
                if(!samples)first_read=batch.host_read_end_ns;
                last_read=batch.host_read_end_ns;
                std::cout<<samples++<<','<<s.valid<<','<<unsigned(s.header)<<','<<s.timestamp_raw<<',';
                if(s.sensor_time_valid)std::cout<<s.sensor_elapsed_ns;
                std::cout<<','<<batch.host_read_begin_ns<<','<<batch.host_read_end_ns<<',';
                if(batch.host_interrupt_ns)std::cout<<*batch.host_interrupt_ns;
                for(auto raw:s.acceleration_raw)std::cout<<','<<double(raw)/8192;
                for(auto raw:s.angular_velocity_raw)std::cout<<','<<double(raw)*500/32768;
                std::cout<<','<<s.sensor_time_valid<<',';
                if(s.fsync_offset_ns)std::cout<<*s.fsync_offset_ns;
                std::cout<<'\n';
                if(s.valid)++valid;
            }
            if(!gpio)std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        check(sensor.stop());
        if(samples<2 || valid<2 || !std::cout)throw Failure{{imu::ErrorCode::configuration}};
        if(fsync && fsync_samples<2)throw Failure{{imu::ErrorCode::fsync_missing}};
        if(!have_counter || !last_elapsed)throw Failure{{imu::ErrorCode::timestamp_discontinuity}};
        const auto host_span=last_read-first_read;
        std::cerr<<"{\"status\":\"ok\",\"mode\":\""<<(gpio?"gpio_irq":"fifo_poll")
            <<"\",\"samples\":"<<samples<<",\"valid\":"<<valid<<",\"wraps\":"<<wraps
            <<",\"min_sensor_delta_ns\":"<<min_delta<<",\"max_sensor_delta_ns\":"<<max_delta
            <<",\"sensor_rate_hz\":"<<double(last_counter_index-first_counter_index)*1e9/double(last_elapsed)
            <<",\"host_observed_rate_hz\":"<<double(samples-1)*1e9/double(host_span)
            <<",\"max_fifo_bytes\":"<<max_fifo<<",\"fsync_enabled\":"<<(fsync?"true":"false")
            <<",\"fsync_samples\":"<<fsync_samples
            <<",\"fsync_offset_min_ns\":"<<(fsync_samples?fsync_min_ns:0)
            <<",\"fsync_offset_max_ns\":"<<fsync_max_ns
            <<",\"restored\":true,\"host_sample_time_validated\":false,\"frame_association_validated\":false}\n";
        return 0;
    }catch(const Failure& f){
        std::cerr<<"{\"status\":\"error\",\"code\":\""<<name(f.error.code)
            <<"\",\"errno\":"<<f.error.system_errno<<",\"register\":"<<unsigned(f.error.reg)<<"}\n";
        return 1;
    }catch(const std::exception&){std::cerr<<"Invalid arguments or allocation failure; use --help.\n";return 2;}
}
