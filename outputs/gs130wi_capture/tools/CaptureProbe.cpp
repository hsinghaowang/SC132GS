#include "gs130wi/Capture.hpp"
#include <algorithm>
#include <atomic>
#include <csignal>
#include <fstream>
#include <iostream>

namespace {
volatile std::sig_atomic_t interrupted{};
void interrupt(int) { interrupted=1; }
class Sink final : public gs130wi::Capture::Observer {
public:
    std::atomic<std::uint64_t> samples{}, fsync{}, batches{};
    std::ofstream output;
    bool on_imu_batch(const gs130wi::ImuBatch& batch) noexcept override {
        try {
            ++batches;
            for(const auto& s:batch.samples) {
                ++samples;
                if(s.fsync_offset_ns)++fsync;
                if(output.is_open()) {
                    output<<s.index<<','<<unsigned(s.fifo_header)<<','<<s.timestamp_raw<<',';
                    if(s.sensor_elapsed_ns)output<<*s.sensor_elapsed_ns;
                    output<<',';
                    if(s.fsync_offset_ns)output<<*s.fsync_offset_ns;
                    output<<','<<batch.host_read_begin_ns<<','<<batch.host_read_end_ns<<'\n';
                    if(!output)return false;
                }
            }
            return !interrupted;
        } catch(...) { return false; }
    }
};
}
int main(int argc,char** argv) {
    std::signal(SIGINT,interrupt); std::signal(SIGTERM,interrupt);
    try {
        const auto frames=argc>1?std::stoul(argv[1]):300;
        if(!frames || frames>20000)return 2;
        Sink sink;
        if(argc>2) {
            sink.output.open(std::string(argv[2])+"-imu.csv");
            sink.output<<"index,header,timestamp_raw,sensor_elapsed_ns,fsync_offset_ns,host_read_begin_ns,host_read_end_ns\n";
            if(!sink.output)return 2;
        }
        auto result=gs130wi::Capture::open({},&sink);
        if(const auto* e=std::get_if<gs130wi::Error>(&result)) {
            std::cerr<<"open_error="<<int(e->code)<<" errno="<<e->system_errno<<'\n'; return 1;
        }
        auto capture=std::get<gs130wi::Capture>(std::move(result));
        std::uint64_t count=0, first=0, last=0, session=0, offset=0;
        int source=0;
        std::optional<gs130wi::Error> failure;
        while(count<frames && !interrupted) {
            auto value=capture.next_frame();
            if(const auto* e=std::get_if<gs130wi::Error>(&value)) { failure=*e; break; }
            const auto& frame=std::get<gs130wi::StereoFrame>(value);
            const auto stamp=frame.images[0].monotonic_timestamp_ns;
            if((count && stamp<=last) || stamp!=frame.images[1].monotonic_timestamp_ns) {
                failure=gs130wi::Error{gs130wi::ErrorCode::timestamp}; break;
            }
            if(!count)first=stamp;
            last=stamp;
            session=frame.synchronization.camera_session;
            source=int(frame.synchronization.source);
            offset=frame.synchronization.timestamp_offset_ns;
            for(const auto& image:frame.images)
                if(image.mono10.size()!=std::size_t(image.width)*image.height ||
                   std::any_of(image.mono10.begin(),image.mono10.end(),[](auto p){return p>1023;}))
                    failure=gs130wi::Error{gs130wi::ErrorCode::camera};
            ++count;
            if(failure)break;
        }
        if(auto e=capture.stop())failure=e;
        sink.output.close();
        const bool passed=!failure && count==frames && sink.samples>0 && sink.fsync>0;
        std::cout<<"{\"passed\":"<<(passed?"true":"false")<<",\"frames\":"<<count
            <<",\"imu_samples\":"<<sink.samples<<",\"fsync_packets\":"<<sink.fsync
            <<",\"camera_session\":"<<session<<",\"timestamp_source\":"<<source
            <<",\"timestamp_offset_ns\":"<<offset<<",\"first_frame_ns\":"<<first
            <<",\"last_frame_ns\":"<<last<<",\"frame_association_validated\":false"
            <<",\"host_sample_time_validated\":false,\"error_code\":"<<(failure?int(failure->code):-1)<<"}\n";
        return passed?0:1;
    } catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 2; }
}
