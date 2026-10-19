#include "DepthPipeline.hpp"
#include <atomic>
#include <chrono>
#include <iostream>
#include <thread>
using namespace stereo_rtsp::detail;
struct Sink final:DepthPipeline::Observer {
    std::atomic<unsigned> errors{},units{};
    void on_depth_error(DepthError)noexcept override{++errors;}
    void on_depth_access_unit(const DepthAccessUnit&)noexcept override{++units;}
};
int main(){
    Sink sink;DepthPipeline pipeline("/nonexistent/depth-fixture",sink);
    auto until=std::chrono::steady_clock::now()+std::chrono::seconds(3);
    while(!pipeline.statistics().failed&&std::chrono::steady_clock::now()<until)std::this_thread::yield();
    pipeline.stop();
    if(!pipeline.statistics().failed||sink.errors!=1||sink.units!=0||pipeline.submit(nullptr,nullptr,0,1)!=DepthSubmission::disabled||pipeline.submit8(nullptr,nullptr,0,1)!=DepthSubmission::disabled)return 1;
    std::cout<<"PASS depth initialization error reported once; parent survives; worker joins\n";
}
