#include "RawOpticalCapture.hpp"
#include <array>
#include <bit>
#include <chrono>
#include <csignal>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <vector>

using namespace stereo_rtsp::optical;
namespace {
volatile std::sig_atomic_t stopped=0;
void stop(int) { stopped=1; }
class Recorder final : public RawOpticalCapture::Observer {
public:
    Recorder(const std::filesystem::path& directory,int seconds)
        : directory_(directory),seconds_(seconds),stream_(directory/"frames.bin",std::ios::binary) {
        stream_.write("SCOP001\0",8);
        write(std::uint32_t{1088}); write(std::uint32_t{1280}); write(std::uint32_t{8});
    }
    bool on_frame(const FrameView& frame) noexcept override {
        try {
            if(stopped) return false;
            if(!start_) {
                start_=frame.dequeue_timestamp_ns;
                std::ofstream ready(directory_/"capture-ready.json");
                ready<<"{\"start_ns\":"<<start_<<"}\n";
                if(!ready) { failed_=true; return false; }
            }
            if(frame.dequeue_timestamp_ns-start_>=seconds_*1'000'000'000LL) return false;
            std::vector<std::uint32_t> sums(136*160);
            std::vector<std::uint8_t> saturated(sums.size());
            for(int y=0;y<1280;++y) {
                const auto* row=frame.packed_raw10.data()+y*frame.stride;
                for(int x=0;x<1088;x+=4) {
                    const auto* group=row+(x/4)*5;
                    auto& sum=sums[(y/8)*136+x/8];
                    for(int p=0;p<4;++p) {
                        const auto pixel=(group[p]<<2)|((group[4]>>(p*2))&3);
                        sum+=pixel;
                        if(pixel>=1018) ++saturated[(y/8)*136+x/8];
                    }
                }
            }
            std::vector<std::uint16_t> tiles(sums.size());
            for(std::size_t i=0;i<sums.size();++i) tiles[i]=static_cast<std::uint16_t>((sums[i]+32)/64);
            write(static_cast<std::uint32_t>(frame.eye)); write(frame.sequence); write(frame.flags);
            write(static_cast<std::uint32_t>(tiles.size()));
            write(frame.receiver_timestamp_ns); write(frame.dequeue_timestamp_ns);
            stream_.write(reinterpret_cast<const char*>(tiles.data()),tiles.size()*sizeof(tiles[0]));
            stream_.write(reinterpret_cast<const char*>(saturated.data()),saturated.size());
            const auto count=++counts_[frame.eye];
            if(count==1 || count==45 || count==90) {
                const auto name="eye"+std::to_string(frame.eye)+"-"+std::to_string(count);
                std::ofstream raw(directory_/(name+".raw10"),std::ios::binary);
                raw.write(reinterpret_cast<const char*>(frame.packed_raw10.data()),frame.packed_raw10.size());
                std::ofstream info(directory_/(name+".json"));
                info<<"{\"sequence\":"<<frame.sequence<<",\"receiver_ns\":"<<frame.receiver_timestamp_ns
                    <<",\"dequeue_ns\":"<<frame.dequeue_timestamp_ns<<",\"stride\":"<<frame.stride
                    <<",\"width\":1088,\"height\":1280}\n";
                if(!raw || !info) failed_=true;
            }
            if(!stream_) failed_=true;
            return !failed_;
        } catch(...) { failed_=true; return false; }
    }
    bool good() const { return !failed_ && stream_.good() && counts_[0]>10 && counts_[1]>10; }
private:
    template<class T> void write(T value) { stream_.write(reinterpret_cast<const char*>(&value),sizeof(value)); }
    std::filesystem::path directory_;
    int seconds_{};
    std::ofstream stream_;
    std::array<unsigned,2> counts_{};
    std::int64_t start_{};
    bool failed_{};
};
void report(const Error& error) {
    std::cerr<<"error_code="<<static_cast<int>(error.code)<<" errno="<<error.system_errno
        <<" eye="<<error.eye<<" operation="<<error.operation<<'\n';
}
}
int main(int argc,char** argv) {
    static_assert(std::endian::native==std::endian::little);
    if(argc!=5) { std::cerr<<"usage: optical-raw-capture CAM0 CAM1 OUTPUT SECONDS\n"; return 2; }
    try {
        const int seconds=std::stoi(argv[4]);
        if(seconds<4 || seconds>180) return 2;
        std::filesystem::create_directories(argv[3]);
        Recorder recorder(argv[3],seconds);
        std::signal(SIGINT,stop); std::signal(SIGTERM,stop);
        auto result=RawOpticalCapture::open({argv[1],argv[2]},recorder);
        if(auto* error=std::get_if<Error>(&result)) { report(*error); return 1; }
        auto error=std::get<RawOpticalCapture>(result).run();
        if(error) { report(*error); return 1; }
        if(!recorder.good()) { std::cerr<<"error_code=1 errno=5 operation=record output\n"; return 1; }
        return 0;
    } catch(...) { std::cerr<<"error_code=1 errno=22 operation=configure output\n"; return 1; }
}
