// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <span>
#include <stdexcept>
#include "sc132gs-ae-statistics.hpp"
#include "sc132gs-hdr-display.hpp"

namespace sc132gs::hdr_ae {
inline Statistics summarize(const std::array<unsigned,1024>& histogram, bool darker_group=true) {
    unsigned count=0, clipped=0;
    for (unsigned i=0;i<1024;++i) { count+=histogram[i]; if(i>=1020) clipped+=histogram[i]; }
    if(!count) throw std::invalid_argument("empty HDR histogram");
    const unsigned highlight_count=(count+4)/5; // Brightest 20%, rounded up.
    const unsigned shadow_count=darker_group ? count-highlight_count : count;
    const unsigned rank=(shadow_count+1)/2;
    unsigned cumulative=0; int median=0;
    for(int i=0;i<1024;++i) {
        cumulative+=histogram[i];
        if(rank && cumulative>=rank) { median=i; break; }
    }
    return {median, static_cast<int>((10000ULL*std::min(clipped,highlight_count)+highlight_count-1)/highlight_count),histogram};
}
inline Statistics measure_raw10(std::span<const std::uint8_t> raw,int width,int height,int stride) {
    if(width<10 || height<10 || width%4 || stride<width*5/4 ||
       raw.size()<static_cast<std::size_t>(stride)*height)
        throw std::invalid_argument("HDR RAW10 dimensions");
    std::array<unsigned,1024> histogram{};
    // Sample a complete CFA cell at each grid point. A stride of eight with
    // only one pixel always selects one Bayer phase and can miss clipping in
    // either green phase or blue, even when the displayed luma is saturated.
    for(int y=height/10;y+1<height*9/10;y+=8)
        for(int x=width/10;x+1<width*9/10;x+=8)
            for(int dy=0;dy<2;++dy) for(int dx=0;dx<2;++dx) {
                const int px=x+dx;
                const auto offset=static_cast<std::size_t>(y+dy)*stride+(px/4)*5;
                const auto value=(raw[offset+px%4]<<2)|((raw[offset+4]>>(2*(px%4)))&3);
                ++histogram[value];
            }
    return summarize(histogram);
}
inline int median_luma10(std::span<const std::uint16_t> pixels,int width,int height) {
    if(width<10 || height<10 || pixels.size()!=static_cast<std::size_t>(width)*height)
        throw std::invalid_argument("AE luma dimensions");
    std::array<unsigned,1024> histogram{};
    for(int y=height/10;y<height*9/10;y+=8)
        for(int x=width/10;x<width*9/10;x+=8) {
            const auto value=pixels[static_cast<std::size_t>(y)*width+x];
            if(value>1023) throw std::invalid_argument("AE luma range");
            ++histogram[value];
        }
    return summarize(histogram,false).shadow;
}
struct Settings {
    int target_percent{40};
    int saturation_limit_bp{500};
    bool preview_b{};
};
struct Exposure { int total_rows{}; int second_ticks{}; int gain{}; };
struct Limits { int minimum_rows{8}; int maximum_rows{1492}; int maximum_gain{128}; };
struct Decision { Exposure exposure; bool shadow_limited{}; bool highlight_limited{}; };
struct Hysteresis { bool highlight_hold{}; int release_count{}; };
inline Decision decide(Settings settings,Limits limits,Exposure current,Statistics left,Statistics right, Hysteresis* history=nullptr) {
    Decision result{current}; auto& next=result.exposure;
    const int clipped=std::max(left.saturation_bp,right.saturation_bp);
    const int shadow=(left.shadow+right.shadow)/2;
    const int target=settings.preview_b ? sc132gs::HdrDisplay::raw_target(settings.target_percent) :
        static_cast<int>((static_cast<std::int64_t>(settings.target_percent)*1023+50)/100);
    // Match Linear's approximately 5% relative meter tolerance. A fixed ten
    // codes allowed a 10% error at target10 and much larger low-target errors.
    const int deadband=settings.preview_b || settings.target_percent==100 ? 5 : std::max(2,(target+10)/20);
    if(history) {
        const int margin=std::max(100,settings.saturation_limit_bp/3);
        if(current.second_ticks==1 && clipped>=std::max(0,settings.saturation_limit_bp-50)) {
            history->highlight_hold=true; history->release_count=0;
        } else if(history->highlight_hold) {
            if(clipped<=std::max(0,settings.saturation_limit_bp-margin)) {
                if(++history->release_count>=8) *history={};
            } else history->release_count=0;
        }
    }
    if(!target) {
        next={limits.minimum_rows,1,0}; result.shadow_limited=shadow>5;
    } else if(clipped>settings.saturation_limit_bp) {
        if(next.second_ticks>1) next.second_ticks=std::max(1,static_cast<int>(next.second_ticks*0.8));
        else {
            result.highlight_limited=true; result.shadow_limited=shadow<target;
            if(next.gain>0) next.gain=std::max(0,next.gain-1);
            else if(next.total_rows>limits.minimum_rows)
                next.total_rows=std::max(limits.minimum_rows,static_cast<int>(next.total_rows*0.9));
        }
    } else if(shadow<target-deadband) {
        if(history && history->highlight_hold) {
            result.shadow_limited=true; result.highlight_limited=true;
        } else if(next.total_rows<limits.maximum_rows) {
            const double factor=settings.preview_b ? 1.15 : std::min(1.15,static_cast<double>(target)/std::max(1,shadow));
            next.total_rows=std::min(limits.maximum_rows,std::max(next.total_rows+1,static_cast<int>(std::lround(next.total_rows*factor))));
        }
        else if(next.gain<limits.maximum_gain && next.second_ticks==1 &&
                clipped>=std::max(0,settings.saturation_limit_bp-50))
            { result.shadow_limited=true; result.highlight_limited=true; } // No short-exposure headroom.
        else if(next.gain<limits.maximum_gain) ++next.gain;
        else result.shadow_limited=true;
    } else if(shadow>target+deadband) {
        if(next.gain>0) --next.gain;
        else {
            const double factor=settings.preview_b ? 0.9 : std::max(0.9,static_cast<double>(target)/std::max(1,shadow));
            next.total_rows=std::max(limits.minimum_rows,std::min(next.total_rows-1,static_cast<int>(std::lround(next.total_rows*factor))));
        }
    } else if(!settings.preview_b && next.gain>0 && next.total_rows<limits.maximum_rows &&
              clipped<settings.saturation_limit_bp/2 && (!history || !history->highlight_hold)) {
        // A lower FPS creates exposure headroom even when luma already matches.
        // Trade gain for photons instead of retaining a noisy high-FPS seed.
        int steps=std::min(2,next.gain);
        int total=next.total_rows;
        while(steps>0) {
            total=static_cast<int>(std::ceil(next.total_rows*std::exp2(steps/32.0)));
            if(total<=limits.maximum_rows) break;
            --steps;
        }
        if(steps>0) { next.total_rows=total; next.gain-=steps; }
    }
    next.second_ticks=std::clamp(next.second_ticks,1,std::min(65535,next.total_rows*16-1));
    return result;
}
} // namespace sc132gs::hdr_ae
