// Internal diagnostic reuses the existing capture adapter without RTSP.
#include "RawOpticalCapture.hpp"
#include "KernelSyncStatus.hpp"
#include <array>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

class Recorder final : public stereo_rtsp::optical::RawOpticalCapture::Observer {
public:
    Recorder(const std::filesystem::path& output, int seconds, const char* first, const char* second)
        : directory_(output), end_(std::chrono::steady_clock::now()+std::chrono::seconds(seconds)),
          stream_(output/"buffers.csv") {
        if (!stream_) throw std::runtime_error("open buffer log");
        stream_ << "eye,sequence,timestamp_ns,dequeue_ns,flags,bytes\n";
        paths_={std::filesystem::canonical(first).string(),std::filesystem::canonical(second).string()};
        auto reader=stereo_rtsp::sync::StatusReader::open("/sys/bus/platform/devices/acb3000.camss/fsync_control");
        if (auto* source=std::get_if<stereo_rtsp::sync::StatusReader>(&reader)) {
            auto state=source->read();
            if (auto* status=std::get_if<stereo_rtsp::sync::Status>(&state)) session_=status->session;
        }
    }
    stereo_rtsp::optical::InvalidBufferAction on_invalid_buffer(
        const stereo_rtsp::optical::InvalidBuffer& f) noexcept override {
        try {
            using namespace stereo_rtsp::sync;
            auto reader=StatusReader::open("/sys/bus/platform/devices/acb3000.camss/fsync_control");
            if (auto* source=std::get_if<StatusReader>(&reader)) {
                auto state=source->read();
                if (auto* status=std::get_if<Status>(&state); status && status->mode==2 &&
                    status->running && !status->driver_error && status->session==session_ && counts_[f.eye]==0) {
                    for (unsigned eye=0; eye<2; ++eye) {
                        if (paths_[f.eye]!="/dev/video"+std::to_string(status->video_nodes[eye]) ||
                            !status->is_startup_buffer(status->video_nodes[eye], f.sequence, session_)) continue;
                        std::ofstream log(directory_/"startup-invalid.csv",std::ios::app);
                        log<<f.eye<<','<<f.sequence<<','<<f.flags<<'\n';
                        if (log) return stereo_rtsp::optical::InvalidBufferAction::discard;
                    }
                }
            }
        } catch (...) {}
        return stereo_rtsp::optical::InvalidBufferAction::abort;
    }
    bool on_frame(const stereo_rtsp::optical::FrameView& f) noexcept override {
        try {
            stream_ << f.eye << ',' << f.sequence << ',' << f.receiver_timestamp_ns << ','
                    << f.dequeue_timestamp_ns << ',' << f.flags << ',' << f.packed_raw10.size() << '\n';
            if (++counts_[f.eye] == 30) {
                std::ofstream raw(directory_/("eye"+std::to_string(f.eye)+".raw10"),std::ios::binary);
                raw.write(reinterpret_cast<const char*>(f.packed_raw10.data()),f.packed_raw10.size());
                if (!raw) { failed_=true; return false; }
            }
            if (!preview_saved_ && counts_[f.eye]>=30) {
                preview_timestamp_[f.eye]=f.receiver_timestamp_ns;
                preview_[f.eye].assign(f.packed_raw10.begin(),f.packed_raw10.end());
                if (preview_timestamp_[0]==preview_timestamp_[1]) {
                    for(int eye=0;eye<2;++eye) {
                        std::ofstream raw(directory_/("pair-eye"+std::to_string(eye)+".raw10"),std::ios::binary);
                        raw.write(reinterpret_cast<const char*>(preview_[eye].data()),preview_[eye].size());
                        if(!raw) { failed_=true; return false; }
                    }
                    std::ofstream stamp(directory_/"pair-timestamp.txt");
                    stamp<<f.receiver_timestamp_ns<<'\n';
                    if(!stamp) { failed_=true; return false; }
                    preview_saved_=true;
                }
            }
            if (!stream_) { failed_=true; return false; }
            return std::chrono::steady_clock::now()<end_;
        } catch (...) { failed_=true; return false; }
    }
    bool failed() const noexcept { return failed_; }
private:
    std::filesystem::path directory_;
    std::chrono::steady_clock::time_point end_;
    std::ofstream stream_;
    std::array<unsigned,2> counts_{};
    std::array<std::string,2> paths_;
    std::uint64_t session_{};
    bool failed_{};
    bool preview_saved_{};
    std::array<std::int64_t,2> preview_timestamp_{{-1,-2}};
    std::array<std::vector<std::uint8_t>,2> preview_;
};
int main(int argc, char** argv) {
    try {
        if(argc!=5) throw std::runtime_error("cam0 cam1 output seconds required");
        std::filesystem::path directory(argv[3]);
        if(!std::filesystem::create_directory(directory)) throw std::runtime_error("output exists");
        Recorder recorder(directory,std::stoi(argv[4]),argv[1],argv[2]);
        auto capture=stereo_rtsp::optical::RawOpticalCapture::open({argv[1],argv[2]},recorder);
        if(auto* e=std::get_if<stereo_rtsp::optical::Error>(&capture)) {
            std::cerr<<"open error="<<static_cast<int>(e->code)<<" errno="<<e->system_errno<<" eye="<<e->eye<<'\n';
            return 1;
        }
        auto error=std::get<stereo_rtsp::optical::RawOpticalCapture>(capture).run();
        if(error) {
            std::cerr<<"capture error="<<static_cast<int>(error->code)<<" errno="<<error->system_errno
                     <<" eye="<<error->eye<<" operation="<<error->operation<<'\n';
            return 1;
        }
        return recorder.failed()?1:0;
    } catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
}
