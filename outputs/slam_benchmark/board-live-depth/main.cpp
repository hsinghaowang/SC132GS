#include "GpuStereoDepth.hpp"
#include "VideoStream.hpp"
#include <gs130wi/Capture.hpp>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <csignal>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <thread>
#include <time.h>

namespace {
volatile std::sig_atomic_t interrupted{};
void interrupt(int){interrupted=1;}
std::uint64_t now(){timespec value{};if(clock_gettime(CLOCK_MONOTONIC,&value))throw std::runtime_error("clock");return value.tv_sec*1000000000ull+value.tv_nsec;}
template<class T>std::vector<T> read(const std::string& name,size_t count){
    std::vector<T> out(count);std::ifstream file(name,std::ios::binary);
    if(!file.read(reinterpret_cast<char*>(out.data()),count*sizeof(T)))throw std::runtime_error("input: "+name);
    return out;
}
template<class T>void write(const std::string& name,const std::vector<T>& data){
    std::ofstream file(name,std::ios::binary);file.write(reinterpret_cast<const char*>(data.data()),data.size()*sizeof(T));
    if(!file)throw std::runtime_error("output: "+name);
}
struct Frame {gs130wi::StereoFrame stereo;std::uint64_t index,ready;};
struct Latest {
    std::mutex mutex;std::condition_variable condition;std::optional<Frame> frame;
    bool done{};std::atomic<std::uint64_t> captured{},replaced{},first_ready{};
    std::atomic<int> error{},system_error{};
};
void rotate(std::ofstream& file,const char* path,const char* header){
    if(file.tellp()<8*1024*1024)return;
    file.close();std::filesystem::path previous=std::string(path)+".previous";
    std::error_code e;std::filesystem::remove(previous,e);std::filesystem::rename(path,previous);
    file.open(path);file<<header;
}
}

int main(int argc,char** argv){
    std::signal(SIGINT,interrupt);std::signal(SIGTERM,interrupt);
    try{
        const int seconds=argc>1?std::stoi(argv[1]):30;
        const int warmup=2;
        if(seconds<0||seconds>1800)return 2;
        board_depth::Calibration calibration;
        calibration.left_map=read<std::int32_t>("left-map.i32",544*640*2);
        calibration.right_map=read<std::int32_t>("right-map.i32",544*640*2);
        calibration.left_valid=read<std::uint8_t>("left-valid.u8",544*640);
        calibration.right_valid=read<std::uint8_t>("right-valid.u8",544*640);
        calibration.full_left_map=read<std::int32_t>("full-left-map.i32",1088*1280*2);
        calibration.full_right_map=read<std::int32_t>("full-right-map.i32",1088*1280*2);
        calibration.yuv_palette=read<std::uint8_t>("palette.u8",1024);
        {std::ifstream file("focal-baseline.txt");if(!(file>>calibration.focal_times_baseline_m_px))throw std::runtime_error("calibration scale");}
        auto gpu_open=board_depth::GpuStereoDepth::open(calibration);
        if(const auto* e=std::get_if<board_depth::Error>(&gpu_open)){std::cerr<<"gpu_open_error="<<int(e->stage)<<" native="<<e->native_code<<'\n';return 1;}
        auto gpu=std::get<board_depth::GpuStereoDepth>(std::move(gpu_open));
        board_depth::VideoStream gray_stream(2176,1280,8554,"/stereo","gray-encoder.csv");
        board_depth::VideoStream depth_stream(544,640,8556,"/depth","depth-encoder.csv",seconds!=0);
        gs130wi::Options options;options.enable_imu=false;options.ten_bit=true;options.downscale=1;
        auto capture_open=gs130wi::Capture::open(options);
        if(const auto* e=std::get_if<gs130wi::Error>(&capture_open)){std::cerr<<"capture_open_error="<<int(e->code)<<" native="<<e->device_code<<" errno="<<e->system_errno<<'\n';return 1;}
        auto capture=std::get<gs130wi::Capture>(std::move(capture_open));
        Latest latest;
        std::ofstream input("capture.csv"),output("depth.csv");
        const char* capture_header="index,stamp_ns,api_ready_ns,sequence0,sequence1,session,source,offset_ns\n";
        const char* depth_header="index,stamp_ns,api_ready_ns,process_begin_ns,depth_ready_ns,gpu_ms,rectify_ms,valid_pixels,sample_hash,published_ns\n";
        input<<capture_header;output<<depth_header;
        if(!input||!output)throw std::runtime_error("CSV open");
        std::thread reader([&]{
            try{
                std::uint64_t previous=0,session=0,offset=0;int source=-1;
                while(!interrupted){
                    auto value=capture.next_frame();const auto ready=now();
                    if(const auto* e=std::get_if<gs130wi::Error>(&value)){
                        std::ifstream state("/sys/bus/platform/devices/acb3000.camss/fsync_control");std::string detail;std::getline(state,detail);
                        std::cerr<<"capture_api_error code="<<int(e->code)<<" errno="<<e->system_errno<<" device="<<e->device_code<<" sync="<<detail<<'\n';
                        latest.error=10+int(e->code);latest.system_error=e->device_code;break;
                    }
                    auto stereo=std::get<gs130wi::StereoFrame>(std::move(value));
                    auto stamp=stereo.images[0].monotonic_timestamp_ns;
                    if(stamp<=previous||stamp!=stereo.images[1].monotonic_timestamp_ns)throw std::runtime_error("stereo timestamp");
                    if(previous&&(session!=stereo.synchronization.camera_session||source!=int(stereo.synchronization.source)||offset!=stereo.synchronization.timestamp_offset_ns))throw std::runtime_error("timing source changed");
                    previous=stamp;session=stereo.synchronization.camera_session;source=int(stereo.synchronization.source);offset=stereo.synchronization.timestamp_offset_ns;
                    for(const auto& image:stereo.images)if(image.width!=1088||image.height!=1280||image.mono10.size()!=1088*1280)throw std::runtime_error("native geometry");
                    auto index=++latest.captured;if(index==1)latest.first_ready=ready;
                    input<<index<<','<<stamp<<','<<ready<<','<<stereo.images[0].sequence<<','<<stereo.images[1].sequence<<','<<session<<','<<source<<','<<offset<<'\n';
                    if(!input)throw std::runtime_error("capture CSV");
                    if(!seconds)rotate(input,"capture.csv",capture_header);
                    {std::lock_guard<std::mutex> lock(latest.mutex);if(latest.frame)++latest.replaced;latest.frame.emplace(Frame{std::move(stereo),index,ready});}
                    latest.condition.notify_one();
                    if(seconds&&ready-latest.first_ready>=std::uint64_t(seconds+warmup)*1000000000ull)break;
                }
            }catch(const std::exception& e){latest.error=99;std::cerr<<"capture_failure="<<e.what()<<'\n';}
            {std::lock_guard<std::mutex> lock(latest.mutex);latest.done=true;}latest.condition.notify_all();
        });
        std::uint64_t processed=0,next_status=0,saved=0;
        int processing_error=0;
        try{
            while(!interrupted){
                std::optional<Frame> frame;
                {std::unique_lock<std::mutex> lock(latest.mutex);
                    latest.condition.wait_for(lock,std::chrono::milliseconds(200),[&]{return latest.done||latest.frame.has_value();});
                    if(!latest.frame){if(latest.done)break;continue;}
                    frame=std::move(latest.frame);latest.frame.reset();
                }
                auto begin=now();
                const bool preview=begin-latest.first_ready>=std::uint64_t(warmup)*1000000000ull&&(!saved||begin-saved>=30000000000ull);
                auto value=gpu.process({frame->stereo.images[0].mono10.data(),frame->stereo.images[1].mono10.data(),1088*1280},preview?board_depth::Preview::left_luma:board_depth::Preview::none);
                auto finish=now();
                if(const auto* e=std::get_if<board_depth::Error>(&value)){processing_error=1;std::cerr<<"gpu_process_error="<<int(e->stage)<<" native="<<e->native_code<<'\n';break;}
                auto& result=std::get<board_depth::DepthFrame>(value);
                auto stamp=frame->stereo.images[0].monotonic_timestamp_ns;
                if(!gray_stream.push(result.gray_nv12,stamp,finish)||!depth_stream.push(result.depth_nv12,stamp,finish))throw std::runtime_error("RTSP encoder push failed");
                std::uint64_t valid=0,hash=1469598103934665603ull;
                for(size_t i=0;i<result.meters.size();++i)if(std::isfinite(result.meters[i])){++valid;if(i%97==0){hash^=std::uint64_t(result.meters[i]*1000000);hash*=1099511628211ull;}}
                output<<frame->index<<','<<frame->stereo.images[0].monotonic_timestamp_ns<<','<<frame->ready<<','<<begin<<','<<finish<<','<<result.gpu_ms<<','<<result.rectify_ms<<','<<valid<<','<<hash<<','<<now()<<'\n';
                if(!output)throw std::runtime_error("depth CSV");
                if(!seconds)rotate(output,"depth.csv",depth_header);
                ++processed;
                if(preview){
                    const auto prefix=seconds?"sample-"+std::to_string(frame->index):std::string("latest");
                    write(prefix+"-depth.f32",result.meters);write(prefix+"-left.u8",result.left_luma);saved=begin;
                    write(prefix+"-gray.nv12",result.gray_nv12);write(prefix+"-color.nv12",result.depth_nv12);
                    // Native full-resolution input retained for independent CPU replay.
                    if(processed<100){write("sample-cam0.u16",frame->stereo.images[0].mono10);write("sample-cam1.u16",frame->stereo.images[1].mono10);std::ofstream meta("sample-index.txt");meta<<frame->index;}
                }
                if(finish>=next_status){std::cout<<"captured="<<latest.captured<<" processed="<<processed<<" replaced="<<latest.replaced<<" process_ms="<<(finish-begin)/1e6<<" timestamp_age_ms="<<(finish-frame->stereo.images[0].monotonic_timestamp_ns)/1e6<<'\n'<<std::flush;next_status=finish+(seconds?1000000000ull:10000000000ull);}
                gpu.recycle(std::move(result));
            }
        }catch(const std::exception& e){processing_error=2;std::cerr<<"processing_failure="<<e.what()<<'\n';}
        capture.request_stop();reader.join();const auto restore=capture.stop();
        gray_stream.close();depth_stream.close();
        const auto gray_stats=gray_stream.statistics(),depth_stats=depth_stream.statistics();
        input.flush();output.flush();
        std::ofstream report("runtime.json");
        report<<"{\"captured\":"<<latest.captured<<",\"processed\":"<<processed<<",\"replaced\":"<<latest.replaced
              <<",\"capture_error\":"<<latest.error<<",\"capture_device_error\":"<<latest.system_error
              <<",\"processing_error\":"<<processing_error<<",\"capture_stop_error\":"<<(restore?1:0)
              <<",\"warmup_seconds\":"<<warmup<<",\"requested_seconds\":"<<seconds<<",\"first_api_ready_ns\":"<<latest.first_ready
              <<",\"gray_encoded\":"<<gray_stats.encoded<<",\"depth_encoded\":"<<depth_stats.encoded
              <<",\"gray_max_queue\":"<<gray_stats.max_queue<<",\"depth_max_queue\":"<<depth_stats.max_queue
              <<",\"encoder_failed\":"<<(gray_stats.failed||depth_stats.failed?"true":"false")
              <<",\"interrupted\":"<<(interrupted?"true":"false")<<",\"workers_joined\":true}\n";
        return latest.error||processing_error||restore||interrupted?1:0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}
}
