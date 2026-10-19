#include "StereoDetailMapper.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>

namespace stereo_rtsp {
namespace {
using Histogram=std::array<std::size_t,1024>;
using Curve=std::array<double,1024>;
using Lut=std::array<std::uint8_t,1024>;
bool valid(const StereoDetailMapper::Config& c) noexcept {
    return std::isfinite(c.strength)&&c.strength>=0&&c.strength<=1 &&
        std::isfinite(c.clip_limit)&&c.clip_limit>=1&&c.clip_limit<=8 &&
        std::isfinite(c.response_ms)&&c.response_ms>0 && c.minimum_span>0&&c.minimum_span<=1023;
}
unsigned percentile(const Histogram& h,std::size_t n,double fraction) noexcept {
    auto rank=std::max<std::size_t>(1,static_cast<std::size_t>(std::ceil(n*fraction)));
    std::size_t total=0;
    for(unsigned i=0;i<h.size();++i){total+=h[i];if(total>=rank)return i;}
    return 1023;
}
struct Range {std::uintptr_t a{},b{};};
bool range(const void* p,std::size_t n,Range& r) noexcept {
    r.a=reinterpret_cast<std::uintptr_t>(p);
    if(!p||n>std::numeric_limits<std::uintptr_t>::max()-r.a)return false;
    r.b=r.a+n;return true;
}
bool overlap(Range a,Range b) noexcept {return a.a<b.b&&b.a<a.b;}
}
struct StereoDetailMapper::Impl {
    Config config;Curve curve{};Lut lut{};
    std::uint64_t timestamp{},revision{};bool initialized{};
    explicit Impl(Config c):config(c){}
};
StereoDetailMapper::StereoDetailMapper():StereoDetailMapper(Config{}){}
StereoDetailMapper::StereoDetailMapper(Config c):impl_(std::make_unique<Impl>(c)){}
StereoDetailMapper::~StereoDetailMapper()=default;
StereoDetailMapper::StereoDetailMapper(StereoDetailMapper&&) noexcept=default;
StereoDetailMapper& StereoDetailMapper::operator=(StereoDetailMapper&&) noexcept=default;
void StereoDetailMapper::reset() noexcept {if(impl_)impl_->initialized=false;}
StereoDetailMapper::Result StereoDetailMapper::process(Input l,Input r,Output a,Output b,std::uint64_t ts) noexcept {
    if(!impl_)return {ErrorCode::moved_from,{}};
    auto& s=*impl_;const auto& c=s.config;
    if(!valid(c))return {ErrorCode::invalid_config,{}};
    if(!l.size||r.size!=l.size||a.size!=l.size||b.size!=l.size||l.size>std::numeric_limits<std::size_t>::max()/2)
        return {ErrorCode::invalid_buffer,{}};
    Range lr,rr,ar,br;
    if(!range(l.data,l.size*2,lr)||!range(r.data,r.size*2,rr)||!range(a.data,a.size,ar)||!range(b.data,b.size,br))
        return {ErrorCode::invalid_buffer,{}};
    if(overlap(ar,br)||overlap(ar,lr)||overlap(ar,rr)||overlap(br,lr)||overlap(br,rr))return {ErrorCode::overlapping_buffers,{}};
    if(s.initialized&&ts<s.timestamp)return {ErrorCode::timestamp_regressed,{}};
    Histogram hl{},hr{};
    for(std::size_t i=0;i<l.size;++i){
        if(l.data[i]>1023||r.data[i]>1023)return {ErrorCode::sample_out_of_range,{}};
        ++hl[l.data[i]];++hr[r.data[i]];
    }
    const auto high=std::max(percentile(hl,l.size,.99),percentile(hr,l.size,.99));
    const auto span=std::max(percentile(hl,l.size,.99)-percentile(hl,l.size,.01),percentile(hr,l.size,.99)-percentile(hr,l.size,.01));
    const bool fallback=high<c.minimum_span||span<c.minimum_span;
    Curve desired{};
    for(unsigned i=0;i<1024;++i)desired[i]=double(i)/1023;
    if(!fallback&&c.strength>0){
        Curve density{};
        for(unsigned i=0;i<1024;++i)density[i]=double(hl[i])+double(hr[i]);
        const double count=double(l.size)*2,cap=count*c.clip_limit/1024;
        double total=0;
        for(auto& d:density){d=std::min(d,cap);total+=d;}
        // Redistribute clipped mass only into bins still below the cap.
        // This bounds contrast and prevents a narrow/noisy peak using all codes.
        for(unsigned iteration=0;iteration<1024&&count-total>1e-7;++iteration){
            unsigned free=0;for(auto d:density)if(d<cap-1e-9)++free;
            if(!free)break;
            const double share=(count-total)/free;total=0;
            for(auto& d:density){d+=std::min(share,std::max(0.0,cap-d));total+=d;}
        }
        double cumulative=0;
        const double first=density[0]*.5,denominator=total-first-density[1023]*.5;
        for(unsigned i=0;i<1024;++i){
            cumulative+=density[i];
            desired[i]=(1-c.strength)*double(i)/1023+c.strength*(cumulative-density[i]*.5-first)/denominator;
        }
        desired[0]=0;desired[1023]=1;
    }
    Curve curve=desired;
    if(s.initialized){
        const double alpha=-std::expm1(-double(ts-s.timestamp)/1e6/c.response_ms);
        for(unsigned i=0;i<1024;++i)curve[i]=s.curve[i]+alpha*(desired[i]-s.curve[i]);
    }
    Lut lut{};
    for(unsigned i=0;i<1024;++i){
        lut[i]=static_cast<std::uint8_t>(std::clamp(std::lround(255*curve[i]),0L,255L));
    }
    const auto revision=s.revision+(!s.initialized||lut!=s.lut?1:0);
    for(std::size_t i=0;i<l.size;++i){a.data[i]=lut[l.data[i]];b.data[i]=lut[r.data[i]];}
    s.curve=curve;s.lut=lut;s.timestamp=ts;s.revision=revision;s.initialized=true;
    return {ErrorCode::none,{revision,fallback}};
}
}
