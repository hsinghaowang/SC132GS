#include "CalibrationCapture.hpp"
#include "RawOpticalCapture.hpp"
#include "BayerLuma.hpp"
#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <condition_variable>
#include <csignal>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <mutex>
#include <thread>
#include <vector>

namespace calibration {
namespace {
volatile std::sig_atomic_t cli_stopped=0;
void signal_stop(int) { cli_stopped=1; }
struct OwnedFrame {
    int eye, width, height, stride;
    std::uint32_t sequence, flags;
    std::int64_t receiver_ns, dequeue_ns;
    std::vector<std::uint8_t> raw;
    std::uint64_t pair_id=0;
};
}
struct CalibrationCapture::Impl final : stereo_rtsp::optical::RawOpticalCapture::Observer {
    explicit Impl(Options value,CalibrationCapture::Observer* listener):options(std::move(value)),observer(listener) {}
    ~Impl() { finish(); }
    Options options;
    CalibrationCapture::Observer* observer;
    Result result;
    std::atomic<bool> stopped{false},storage_failed{false};
    std::mutex mutex;
    std::condition_variable available;
    std::deque<OwnedFrame> incoming;
    std::array<std::deque<OwnedFrame>,2> pending;
    bool closed=false,used=false;
    std::thread worker;
    std::array<std::uint32_t,2> previous{};
    std::array<bool,2> seen{};
    std::int64_t first_dequeue=0;
    void finish() noexcept {
        { std::lock_guard<std::mutex> lock(mutex);closed=true; }
        available.notify_all();
        if(worker.joinable())worker.join();
    }
    bool on_frame(const stereo_rtsp::optical::FrameView& frame) noexcept override {
        try {
            if(stopped || cli_stopped || storage_failed)return false;
            if(!first_dequeue)first_dequeue=frame.dequeue_timestamp_ns;
            if(frame.dequeue_timestamp_ns-first_dequeue>=std::int64_t(options.seconds)*1'000'000'000LL)return false;
            const auto eye=static_cast<std::size_t>(frame.eye);
            if(eye>=2 || frame.receiver_timestamp_ns<=0) { result.error={ErrorCode::camera,EINVAL,frame.eye};return false; }
            if(seen[eye] && frame.sequence>previous[eye]+1)result.driver_sequence_gaps[eye]+=frame.sequence-previous[eye]-1;
            previous[eye]=frame.sequence;seen[eye]=true;++result.captured[eye];
            OwnedFrame copy{frame.eye,frame.width,frame.height,frame.stride,frame.sequence,frame.flags,
                frame.receiver_timestamp_ns,frame.dequeue_timestamp_ns,{frame.packed_raw10.begin(),frame.packed_raw10.end()}};
            pending[eye].push_back(std::move(copy));
            if(pending[eye].size()>4) {pending[eye].pop_front();++result.unpaired[eye];}
            while(!pending[0].empty() && !pending[1].empty()) {
                const auto delta=pending[0].front().receiver_ns-pending[1].front().receiver_ns;
                const auto limit=std::int64_t(options.maximum_driver_stamp_delta_us)*1000;
                if(delta < -limit) {pending[0].pop_front();++result.unpaired[0];continue;}
                if(delta > limit) {pending[1].pop_front();++result.unpaired[1];continue;}
                const auto pair_id=result.timestamp_pairs++;
                if(pair_id%options.select_every_frames==0) {
                    std::lock_guard<std::mutex> lock(mutex);
                    if(incoming.size()>6) {result.error={ErrorCode::queue_full,ENOBUFS,frame.eye};return false;}
                    for(auto& eye_queue:pending) {
                        eye_queue.front().pair_id=pair_id;
                        incoming.push_back(std::move(eye_queue.front()));
                    }
                    result.maximum_storage_queue=std::max(result.maximum_storage_queue,std::uint64_t(incoming.size()));
                    available.notify_one();
                }
                for(auto& eye_queue:pending)eye_queue.pop_front();
            }
            return true;
        } catch(...) { result.error={ErrorCode::storage,ENOMEM,frame.eye};return false; }
    }
    void store() noexcept {
        try {
            const std::filesystem::path root(options.output_directory);
            std::ofstream index(root/"camera-frames.csv");
            index.exceptions(std::ios::badbit|std::ios::failbit);
            index<<"pair_id,eye,sequence,flags,receiver_timestamp_ns,dequeue_timestamp_ns,width,height,stride,image\n";
            std::array<stereo_rtsp::detail::BayerLuma,2> converters{
                stereo_rtsp::detail::BayerLuma(1088,1280),stereo_rtsp::detail::BayerLuma(1088,1280)};
            std::vector<std::uint8_t> gray(1088*1280);
            for(;;) {
                OwnedFrame frame;
                {
                    std::unique_lock<std::mutex> lock(mutex);
                    available.wait(lock,[this]{return closed || !incoming.empty();});
                    if(incoming.empty() && closed)break;
                    frame=std::move(incoming.front());incoming.pop_front();
                }
                const auto eye=static_cast<std::size_t>(frame.eye);
                converters[eye].convert(frame.raw,frame.stride,gray,1);
                const auto relative="cam"+std::to_string(eye)+"/"+std::to_string(frame.receiver_ns)+"-"+std::to_string(frame.sequence)+".pgm";
                std::ofstream image(root/relative,std::ios::binary);
                image.exceptions(std::ios::badbit|std::ios::failbit);
                image<<"P5\n1088 1280\n255\n";
                image.write(reinterpret_cast<const char*>(gray.data()),static_cast<std::streamsize>(gray.size()));image.close();
                index<<frame.pair_id<<','<<eye<<','<<frame.sequence<<','<<frame.flags<<','<<frame.receiver_ns<<','<<frame.dequeue_ns<<','
                    <<frame.width<<','<<frame.height<<','<<frame.stride<<','<<relative<<'\n';
                ++result.saved[eye];
                if(observer)observer->on_progress(Progress{result.saved});
            }
            index.flush();
        } catch(...) { storage_failed=true; }
    }
    Result run() noexcept {
        if(used) return {{ErrorCode::invalid_configuration,EINVAL,-1}};
        used=true;
        try {
            const std::filesystem::path root(options.output_directory);
            if(options.seconds<1 || options.seconds>180 || !options.select_every_frames ||
               options.select_every_frames>60 || !std::filesystem::is_directory(root) ||
               !options.maximum_driver_stamp_delta_us || options.maximum_driver_stamp_delta_us>10000 ||
               std::filesystem::exists(root/"camera-frames.csv"))return {{ErrorCode::invalid_configuration,EINVAL,-1}};
            std::filesystem::create_directory(root/"cam0");std::filesystem::create_directory(root/"cam1");
            worker=std::thread([this]{store();});
            {
                auto capture=stereo_rtsp::optical::RawOpticalCapture::open({options.first_camera,options.second_camera},*this);
                if(auto* error=std::get_if<stereo_rtsp::optical::Error>(&capture))result.error={ErrorCode::camera,error->system_errno,error->eye};
                else if(auto error=std::get<stereo_rtsp::optical::RawOpticalCapture>(capture).run())result.error={ErrorCode::camera,error->system_errno,error->eye};
            } // STREAMOFF/unmap/close before storage worker is joined.
            finish();
            if(storage_failed)result.error={ErrorCode::storage,EIO,-1};
            if(result.error.code==ErrorCode::none && (!result.saved[0] || !result.saved[1]))result.error={ErrorCode::camera,ENODATA,-1};
        } catch(...) { finish();result.error={ErrorCode::storage,EIO,-1}; }
        return result;
    }
};
CalibrationCapture::CalibrationCapture(Options value,Observer* observer):impl_(std::make_unique<Impl>(std::move(value),observer)) {}
CalibrationCapture::~CalibrationCapture()=default;
CalibrationCapture::CalibrationCapture(CalibrationCapture&&) noexcept=default;
CalibrationCapture& CalibrationCapture::operator=(CalibrationCapture&&) noexcept=default;
Result CalibrationCapture::run() noexcept { return impl_?impl_->run():Result{{ErrorCode::invalid_configuration,EINVAL,-1}}; }
void CalibrationCapture::request_stop() noexcept { if(impl_)impl_->stopped=true; }
}
int main(int argc,char** argv) {
    if(argc!=6) {std::cerr<<"usage: calibration-capture CAM0 CAM1 EXISTING_NEW_OUTPUT SECONDS SELECT_EVERY_FRAMES\n";return 2;}
    try {
        const auto seconds=std::stoul(argv[4]),every=std::stoul(argv[5]);
        if(seconds>180 || every>60)return 2;
        std::signal(SIGINT,calibration::signal_stop);std::signal(SIGTERM,calibration::signal_stop);
        calibration::CalibrationCapture capture({argv[1],argv[2],argv[3],static_cast<std::uint32_t>(seconds),static_cast<std::uint32_t>(every)});
        const auto result=capture.run();
        std::ofstream summary(std::filesystem::path(argv[3])/"camera-summary.json");
        summary<<"{\"error_code\":"<<static_cast<int>(result.error.code)<<",\"errno\":"<<result.error.system_errno
            <<",\"captured\":["<<result.captured[0]<<','<<result.captured[1]<<"],\"saved\":["<<result.saved[0]<<','<<result.saved[1]
            <<"],\"driver_sequence_gaps\":["<<result.driver_sequence_gaps[0]<<','<<result.driver_sequence_gaps[1]
            <<"],\"maximum_storage_queue\":"<<result.maximum_storage_queue<<",\"select_every_frames\":"<<every
            <<",\"timestamp_pairs\":"<<result.timestamp_pairs<<",\"unpaired\":["<<result.unpaired[0]<<','<<result.unpaired[1]<<']'
            <<",\"timestamp_scope\":\"V4L2 receiver and dequeue CLOCK_MONOTONIC; not exposure start\"}\n";
        summary.close();if(!summary)return 1;
        return result.error.code==calibration::ErrorCode::none?0:1;
    } catch(...) {return 2;}
}
