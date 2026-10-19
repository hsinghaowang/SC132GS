#include "sc132gs-hdr-ae-policy.hpp"
#include <vector>
using namespace sc132gs::hdr_ae;
int main() {
    sc132gs::HdrDisplay display;
    std::array<std::uint16_t,1024> ramp{};
    for(int i=0;i<1024;++i) ramp[i]=i;
    display.apply(ramp);
    if(ramp[0]!=0 || ramp[52]!=0 || ramp[1023]!=1023) return 24;
    for(int i=1;i<1024;++i) if(ramp[i]<ramp[i-1]) return 25;
    // Manual B maps to ~30% displayed shadow, not the legacy target * 80%.
    if(sc132gs::HdrDisplay::raw_target(30)!=139 || sc132gs::HdrDisplay::displayed_percent(139)!=30) return 26;
    auto preview=decide({30,500,true},{},{1492,1,21},{138,200},{140,400});
    if(preview.exposure.gain!=21 || preview.shadow_limited) return 27;
    preview=decide({30,500,true},{},{1492,1,10},{100,0},{100,0});
    if(preview.exposure.gain!=11) return 28;
    preview=decide({30,500,true},{},{1492,1,21},{145,600},{145,0});
    if(preview.exposure.gain!=20 || !preview.highlight_limited) return 29;
    // Calibrated low targets use a relative tolerance and proportional steps.
    auto tracking=decide({10,500,false},{},{1000,1,0},{90,0},{90,0});
    if(tracking.exposure.total_rows!=1133) return 40;
    tracking=decide({10,500,false},{},{1000,1,0},{110,0},{110,0});
    if(tracking.exposure.total_rows!=927) return 41;
    tracking=decide({10,500,false},{},{1000,1,0},{102,0},{102,0});
    if(tracking.exposure.total_rows!=1000) return 42;
    tracking=decide({20,500,false},{8,3629,128},{1492,1,14},{204,0},{204,0});
    if(tracking.exposure.total_rows!=1559 || tracking.exposure.gain!=12) return 43;
    tracking=decide({20,500,false},{8,1492,128},{1492,1,14},{204,0},{204,0});
    if(tracking.exposure.total_rows!=1492 || tracking.exposure.gain!=14) return 44;
    std::array<unsigned,1024> histogram{};
    histogram[100]=50; histogram[900]=45; histogram[1023]=5;
    auto s=summarize(histogram);
    if(s.shadow!=100 || s.saturation_bp!=2500) return 1;
    histogram={}; histogram[100]=30; histogram[200]=30;
    histogram[900]=35; histogram[1023]=5;
    if(summarize(histogram).shadow!=200) return 11; // Median of the darker 80%, whole-area P40.
    histogram={}; histogram[100]=40; histogram[200]=10; histogram[900]=45; histogram[1023]=5;
    if(summarize(histogram).shadow!=100) return 13;
    // Same histogram as Linear: P50 must include the entire metering ROI.
    histogram={}; histogram[100]=40; histogram[200]=10; histogram[900]=50;
    if(summarize(histogram).shadow!=100 || summarize(histogram,false).shadow!=200) return 33;
    if(summarize(histogram,false).saturation_bp!=summarize(histogram).saturation_bp) return 34;
    histogram={}; histogram[100]=99; histogram[1023]=1;
    if(summarize(histogram).saturation_bp!=500) return 14; // 1% of all samples = 5% of the brightest 20%.
    histogram={}; histogram[1023]=100;
    if(summarize(histogram).saturation_bp!=10000) return 17; // Clip count cannot exceed group size.
    histogram={}; histogram[100]=3; histogram[1023]=2;
    if(summarize(histogram).saturation_bp!=10000 || summarize(histogram).shadow!=100) return 18;
    auto scaled=decide({40,2000},{},{1492,93,16},{409,0},{409,0});
    if(scaled.exposure.gain!=16) return 15; // Direct RAW10 target: 40% = 409.
    scaled=decide({40,500},{},{1492,93,16},{409,0},{409,0});
    if(scaled.exposure.gain!=16) return 16; // Metering group size does not rescale the target.
    scaled=decide({40,500},{},{1492,93,16},{327,0},{327,0});
    if(scaled.exposure.gain!=17) return 30; // Legacy 32% must no longer satisfy 40%.
    scaled=decide({12,500},{},{1200,1,21},{123,0},{123,0});
    if(scaled.exposure.total_rows!=1254 || scaled.exposure.gain!=19) return 31; // Same target, less gain when photons fit.
    Hysteresis raw_history;
    scaled=decide({70,500},{},{1200,1,21},{123,480},{123,480},&raw_history);
    if(!scaled.highlight_limited || !scaled.shadow_limited) return 32;
    histogram={}; histogram[100]=19000; histogram[1023]=1001;
    if(summarize(histogram).saturation_bp!=2502) return 12; // Round clipping conservatively within the bright group.
    histogram={}; histogram[100]=94; histogram[1023]=6;
    if(summarize(histogram).saturation_bp!=3000) return 2;
    Exposure current{1492,93,16}; Limits limits;
    auto clipped=decide({},limits,current,{100,0},{100,600});
    if(clipped.exposure.second_ticks>=93 || clipped.exposure.gain!=16 || clipped.exposure.total_rows!=1492) return 3;
    auto dark=decide({},limits,current,{100,100},{100,100});
    if(dark.exposure.gain!=17 || dark.exposure.second_ticks!=93) return 4;
    current.total_rows=1000;
    dark=decide({},limits,current,{100,0},{100,0});
    if(dark.exposure.total_rows<=1000 || dark.exposure.gain!=16 || dark.exposure.second_ticks!=93) return 5;
    current={1492,1,128};
    clipped=decide({},limits,current,{100,600},{100,0});
    if(!clipped.highlight_limited || !clipped.shadow_limited || clipped.exposure.gain>=128) return 6;
    auto held=decide({},limits,{1492,1,16},{100,480},{100,480});
    if(!held.shadow_limited || !held.highlight_limited || held.exposure.gain!=16) return 7;
    auto satisfied=decide({},limits,{1492,93,16},{409,0},{409,100});
    if(satisfied.exposure.second_ticks!=93 || satisfied.exposure.gain!=16) return 8;
    auto black=decide({0,500},limits,{1492,93,16},{100,0},{100,0});
    if(black.exposure.total_rows!=8 || black.exposure.second_ticks!=1 || black.exposure.gain!=0) return 9;
    // Highlight constraint must not alternate between gain-up and gain-down.
    Hysteresis history;
    auto stable=decide({},limits,{1492,1,20},{100,510},{100,510},&history);
    if(!history.highlight_hold || stable.exposure.gain!=19) return 19;
    for(int i=0;i<40;++i) {
        stable=decide({},limits,stable.exposure,{100,470+(i%2)*20},{100,470},&history);
        if(stable.exposure.gain!=19 || !stable.highlight_limited) return 20;
    }
    // Hold also covers TOTAL, and releases only after sustained scene headroom.
    stable=decide({},limits,{1000,1,19},{100,470},{100,470},&history);
    if(stable.exposure.total_rows!=1000) return 21;
    for(int i=0;i<7;++i) {
        stable=decide({},limits,{1492,1,19},{100,200},{100,200},&history);
        if(stable.exposure.gain!=19) return 22;
    }
    stable=decide({},limits,{1492,1,19},{100,200},{100,200},&history);
    if(history.highlight_hold || stable.exposure.gain!=20) return 23;
    // Distinct low bits and each packed pixel position must survive sampling.
    for(int offset=0;offset<4;++offset) {
        const int width=40+offset*12,height=40,stride=width*5/4;
        std::vector<std::uint8_t> raw(stride*height);
        for(int y=0;y<height;++y) for(int x=0;x<width;++x) {
            auto group=y*stride+(x/4)*5;
            const int value=408+x%4;
            raw[group+x%4]=value>>2;
            raw[group+4]|=(value&3)<<(2*(x%4));
        }
        const auto measured=measure_raw10(raw,width,height,stride);
        const int phase=(width/10)%4;
        if(measured.shadow!=408+std::min(phase,(phase+1)%4) || measured.saturation_bp!=0) return 10;
    }
    // Each of R, Gr, Gb, B must independently trigger highlight protection.
    for(int phase=0;phase<4;++phase) {
        constexpr int width=40,height=40,stride=width*5/4;
        std::vector<std::uint8_t> raw(stride*height);
        for(int y=0;y<height;++y) for(int x=0;x<width;++x) {
            const int value=((y%2)*2+x%2)==phase ? 1023 : 100;
            const int group=y*stride+(x/4)*5;
            raw[group+x%4]=value>>2;
            raw[group+4]|=(value&3)<<(2*(x%4));
        }
        const auto measured=measure_raw10(raw,width,height,stride);
        if(measured.histogram[1023]!=16 || measured.saturation_bp!=10000) return 35+phase;
    }
}
