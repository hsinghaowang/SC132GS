#pragma once
#include "icm42688.hpp"
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

namespace imu::linux_detail {
struct Failure { imu::Error error; };
inline std::uint64_t monotonic_ns() {
    timespec t{};
    if (clock_gettime(CLOCK_MONOTONIC,&t)) throw Failure{{imu::ErrorCode::transport,errno}};
    return std::uint64_t(t.tv_sec)*1000000000+std::uint64_t(t.tv_nsec);
}
class Fd final {
    int fd_;
public:
    explicit Fd(int fd):fd_(fd){if(fd<0)throw Failure{{imu::ErrorCode::transport,errno}};}
    ~Fd(){if(fd_>=0)::close(fd_);}
    Fd(const Fd&)=delete;
    Fd& operator=(const Fd&)=delete;
    int get()const{return fd_;}
};
class LinuxRegisters final : public imu::Icm42688::Registers {
    Fd lock_;
    Fd device_;
    bool fifo_pointer_active_{};
    bool continue_fifo_{};
public:
    explicit LinuxRegisters(const std::string& path,bool continue_fifo=true)
        :lock_(::open(("/run/lock/gs130wi-imu-"+std::filesystem::path(path).filename().string()+"-68.lock").c_str(),O_CREAT|O_RDWR|O_CLOEXEC,0600)),
         device_(::open(path.c_str(),O_RDWR|O_CLOEXEC)),continue_fifo_(continue_fifo) {
        if(flock(lock_.get(),LOCK_EX|LOCK_NB))throw Failure{{imu::ErrorCode::busy,errno}};
        // Also reject a kernel-bound client. I2C_RDWR alone would bypass that check.
        if(ioctl(device_.get(),I2C_SLAVE,0x68)<0)throw Failure{{imu::ErrorCode::busy,errno}};
    }
    imu::Status read(std::uint8_t reg,imu::MutableBytes data)override {
        if(data.empty() || data.size()>12)return imu::Error{imu::ErrorCode::configuration,0,reg};
        i2c_msg messages[2]{{0x68,0,1,&reg},{0x68,I2C_M_RD,static_cast<__u16>(data.size()),data.data()}};
        const bool continuation=continue_fifo_ && reg==0x30 && fifo_pointer_active_;
        i2c_rdwr_ioctl_data transfer{continuation?messages+1:messages,continuation?1u:2u};
        int result;
        do {result=ioctl(device_.get(),I2C_RDWR,&transfer);}while(result<0 && errno==EINTR);
        if(result!=static_cast<int>(transfer.nmsgs))return imu::Error{imu::ErrorCode::transport,result<0?errno:EIO,reg};
        fifo_pointer_active_=reg==0x30;
        return std::monostate{};
    }
    imu::Status write(std::uint8_t reg,std::uint8_t value)override {
        fifo_pointer_active_=false;
        std::uint8_t bytes[]{reg,value};
        i2c_msg message{0x68,0,2,bytes};
        i2c_rdwr_ioctl_data transfer{&message,1};
        int result;
        do {result=ioctl(device_.get(),I2C_RDWR,&transfer);}while(result<0 && errno==EINTR);
        if(result!=1)return imu::Error{imu::ErrorCode::transport,result<0?errno:EIO,reg};
        return std::monostate{};
    }
    std::uint64_t monotonic_ns()const override {return imu::linux_detail::monotonic_ns();}
};
class GpioInterrupt final : public imu::Icm42688::Interrupt {
    Fd line_;
    std::uint32_t previous_sequence_{};
    static int request(const std::string& path,unsigned line) {
        Fd chip(::open(path.c_str(),O_RDONLY|O_CLOEXEC));
        gpio_v2_line_request request{};
        request.offsets[0]=line;
        request.num_lines=1;
        request.event_buffer_size=32;
        std::strncpy(request.consumer,"gs130wi-imu",sizeof(request.consumer)-1);
        request.config.flags=GPIO_V2_LINE_FLAG_INPUT|GPIO_V2_LINE_FLAG_EDGE_RISING|GPIO_V2_LINE_FLAG_BIAS_DISABLED;
        if(ioctl(chip.get(),GPIO_V2_GET_LINE_IOCTL,&request))throw Failure{{imu::ErrorCode::transport,errno}};
        return request.fd;
    }
public:
    GpioInterrupt(const std::string& path,unsigned line):line_(request(path,line)){}
    bool value() const {
        gpio_v2_line_values values{};
        values.mask=1;
        if(ioctl(line_.get(),GPIO_V2_LINE_GET_VALUES_IOCTL,&values))throw Failure{{imu::ErrorCode::transport,errno}};
        return (values.bits&1)!=0;
    }
    imu::Result<std::uint64_t> wait(int timeout_ms)override {
        pollfd p{line_.get(),POLLIN,0};
        int result;
        do {result=poll(&p,1,timeout_ms);}while(result<0 && errno==EINTR);
        if(result==0)return imu::Error{imu::ErrorCode::interrupt_timeout};
        if(result<0)return imu::Error{imu::ErrorCode::transport,errno};
        if(!(p.revents&POLLIN))return imu::Error{imu::ErrorCode::transport,EIO};
        gpio_v2_line_event event{};
        if(::read(line_.get(),&event,sizeof(event))!=sizeof(event))return imu::Error{imu::ErrorCode::transport,errno};
        if(previous_sequence_ && event.seqno!=previous_sequence_+1)
            return imu::Error{imu::ErrorCode::timestamp_discontinuity};
        previous_sequence_=event.seqno;
        return event.timestamp_ns; // Kernel GPIO event CLOCK_MONOTONIC, not read completion.
    }
};
}
