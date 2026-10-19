#include "BayerLuma.hpp"
#include "sc132gs-hdr-ae-policy.hpp"
#include "sc132gs-linear-ae-policy.hpp"
#include <ctime>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <vector>

namespace {
double cpu_ns(){timespec time{};if(clock_gettime(CLOCK_THREAD_CPUTIME_ID,&time))std::abort();return time.tv_sec*1e9+time.tv_nsec;}
}
int main(int argc,char** argv){
    const int iterations=argc>1?std::atoi(argv[1]):60;
    if(iterations<1 || iterations>10000)return 2;
    constexpr int width=1088,height=1280,stride=width*5/4;
    std::vector<std::uint8_t> raw(static_cast<std::size_t>(stride)*height);
    std::uint32_t random=19810827;
    for(auto& b:raw){random^=random<<13;random^=random>>17;random^=random<<5;b=random&255;}
    stereo_rtsp::detail::BayerLuma converter(width,height);
    std::vector<std::uint16_t> gray(static_cast<std::size_t>(width)*height);
    double held=0,total=0;
    std::uint64_t digest=0;
    // Identical input/output, excluding allocations and startup in both paths.
    for(int iteration=-3;iteration<iterations;++iteration){
        const double begin=cpu_ns();
        sc132gs::hdr_ae::Statistics hdr;
        sc132gs::linear_ae::HighlightStatistics highlight;
        double release;
#if defined(STEREO_BASELINE)
        hdr=sc132gs::hdr_ae::measure_raw10(raw,width,height,stride);
        highlight=sc132gs::linear_ae::measure_packed_raw10(raw.data(),raw.size(),width,height,stride);
        converter.convert10(raw,stride,gray,1);
        hdr.luma_median=sc132gs::hdr_ae::median_luma10(gray,width,height);
        release=cpu_ns();
#else
        converter.unpack(raw,stride);
        release=cpu_ns();
        const auto meter=converter.statistics();
        hdr=sc132gs::hdr_ae::summarize(meter.histogram);
        highlight={meter.sample_count,meter.near_saturated_count,true};
        converter.render10(gray,1);
        hdr.luma_median=sc132gs::hdr_ae::median_luma10(gray,width,height);
#endif
        const double end=cpu_ns();
        if(iteration>=0){held+=release-begin;total+=end-begin;}
        digest+=highlight.near_saturated_count+hdr.shadow+hdr.luma_median+gray[123456];
    }
    std::cout<<std::fixed<<std::setprecision(6)
             <<"{\"iterations\":"<<iterations<<",\"width\":"<<width<<",\"height\":"<<height
             <<",\"mean_cpu_ms\":"<<total/iterations/1e6
             <<",\"mean_before_qbuf_work_cpu_ms\":"<<held/iterations/1e6
             <<",\"digest\":"<<digest
             <<",\"clock\":\"CLOCK_THREAD_CPUTIME_ID\",\"scope\":\"synthetic offline work, excludes ioctl and live scheduling\"}\n";
}
