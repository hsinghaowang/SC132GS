#include "RawOpticalCapture.hpp"
#include "BayerLuma.hpp"
#include <array>
#include <csignal>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <vector>

namespace {
volatile std::sig_atomic_t stopped=0;
void stop(int) { stopped=1; }
// Offline diagnostic executable; views remain owned by RawOpticalCapture.
class Recorder final : public stereo_rtsp::optical::RawOpticalCapture::Observer {
public:
    explicit Recorder(const std::filesystem::path& directory)
        : directory_(directory), converter_(1088,1280,false), luma_(1088*1280),
          stream_(directory/"patches.bin",std::ios::binary) {
        stream_.write("SCNP001\0",8);
    }
    bool on_frame(const stereo_rtsp::optical::FrameView& frame) noexcept override {
        try {
            if(stopped) { failed_=true; return false; }
            if(++seen_[frame.eye]<=8) return true;
            if(counts_[frame.eye]>=60) return true;
            converter_.convert10(frame.packed_raw10,frame.stride,luma_,1);
            if(counts_[frame.eye]==0) {
                std::ofstream full(directory_/("eye"+std::to_string(frame.eye)+"-first-luma10.bin"),std::ios::binary);
                full.write(reinterpret_cast<const char*>(luma_.data()),luma_.size()*sizeof(luma_[0]));
                if(!full) { failed_=true; return false; }
            }
            write(static_cast<std::uint32_t>(frame.eye));
            write(frame.sequence); write(frame.receiver_timestamp_ns);
            for(const auto& box:boxes_) for(int y=box[1];y<box[3];++y)
                for(int x=box[0];x<box[2];++x)
                    // Match the Main10 RTSP per-eye horizontal reflection.
                    write(luma_[y*1088+1087-x]);
            if(!stream_) { failed_=true; return false; }
            ++counts_[frame.eye];
            return counts_[0]<60 || counts_[1]<60;
        } catch(...) { failed_=true; return false; }
    }
    bool good() const { return !failed_ && counts_[0]==60 && counts_[1]==60 && stream_.good(); }
private:
    template<class T> void write(T value) { stream_.write(reinterpret_cast<const char*>(&value),sizeof(value)); }
    inline static constexpr std::array<std::array<int,4>,2> boxes_{{{30,80,160,220},{500,470,660,620}}};
    std::filesystem::path directory_;
    stereo_rtsp::detail::BayerLuma converter_;
    std::vector<std::uint16_t> luma_;
    std::ofstream stream_;
    std::array<int,2> seen_{},counts_{};
    bool failed_{};
};
}
int main(int argc,char** argv) {
    if(argc!=4) { std::cerr<<"usage: raw-noise-capture CAM0 CAM1 OUTPUT\n"; return 2; }
    try {
        std::filesystem::create_directories(argv[3]);
        Recorder recorder(argv[3]);
        std::signal(SIGINT,stop); std::signal(SIGTERM,stop);
        auto result=stereo_rtsp::optical::RawOpticalCapture::open({argv[1],argv[2]},recorder);
        if(auto* error=std::get_if<stereo_rtsp::optical::Error>(&result)) {
            std::cerr<<"error_code="<<static_cast<int>(error->code)<<" errno="<<error->system_errno
                     <<" operation="<<error->operation<<'\n'; return 1;
        }
        auto error=std::get<stereo_rtsp::optical::RawOpticalCapture>(result).run();
        if(error || !recorder.good()) { std::cerr<<"error_code=1 operation=record\n"; return 1; }
        return 0;
    } catch(...) { std::cerr<<"error_code=1 operation=configure\n"; return 1; }
}
