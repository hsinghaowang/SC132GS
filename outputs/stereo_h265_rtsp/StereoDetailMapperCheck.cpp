#include "StereoDetailMapper.hpp"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <type_traits>
#include <vector>
namespace {
using M=stereo_rtsp::StereoDetailMapper;
using Raw=std::vector<std::uint16_t>;using Bytes=std::vector<std::uint8_t>;
static_assert(!std::is_copy_constructible<M>::value&&std::is_nothrow_move_constructible<M>::value);
void require(bool x,const char* message){if(!x)throw std::runtime_error(message);}
auto map(M& m,const Raw& l,const Raw& r,Bytes& a,Bytes& b,std::uint64_t t){return m.process({l.data(),l.size()},{r.data(),r.size()},{a.data(),a.size()},{b.data(),b.size()},t);}
Raw ramp(unsigned maximum){Raw r(8192);for(unsigned i=0;i<r.size();++i)r[i]=i*maximum/(r.size()-1);return r;}
void invariants(){
    auto l=ramp(1023),r=ramp(350);const auto saved_l=l,saved_r=r;
    Bytes a(l.size()),b(l.size()),c(l.size()),d(l.size());
    M m,swapped;auto x=map(m,l,r,a,b,1);auto y=map(swapped,r,l,c,d,1);
    require(bool(x)&&bool(y)&&a==d&&b==c,"eye order changed LUT");
    require(l==saved_l&&r==saved_r,"modified AE/matching input");
    require(std::is_sorted(a.begin(),a.end())&&std::is_sorted(b.begin(),b.end()),"non-monotonic LUT");
    require(a.front()==0&&a.back()==255,"lost full-range anchors");
    M::Config off;off.strength=0;M reference(off);map(reference,l,r,c,d,1);
    for(unsigned i=0;i<l.size();++i){
        require(c[i]==std::lround(255.0*l[i]/1023),"disabled contrast differs from linear quantization");
    }
    // Low contrast textured body with a sparse lamp: retain every anchor,
    // increase useful body span, and never hard-clip at a scene percentile.
    for(unsigned i=0;i<l.size();++i)l[i]=40+i*100/(l.size()-1);
    l[0]=0;l[l.size()-4]=300;l[l.size()-3]=500;l[l.size()-2]=750;l.back()=1023;
    M enhanced;map(enhanced,l,l,a,b,1);M normal(off);map(normal,l,l,c,d,1);
    require(a[8000]-a[100]>c[8000]-c[100],"body contrast did not expand");
    require(a[l.size()-4]<a[l.size()-3]&&a[l.size()-3]<a[l.size()-2]&&a[l.size()-2]<a.back(),"sparse highlights collapsed");
    // A uniform/noisy black field must not stretch sensor noise across 220 codes.
    for(unsigned i=0;i<l.size();++i)l[i]=i%4;
    M noise;auto n=map(noise,l,l,a,b,1);
    require(n.frame.fallback&&*std::max_element(a.begin(),a.end())-*std::min_element(a.begin(),a.end())<=3,"near-black noise amplified");
}
void temporal_and_errors(){
    auto full=ramp(1023),dark=ramp(127);Bytes a(full.size()),b(full.size()),c(full.size()),d(full.size());
    M one,two;map(one,full,full,a,b,0);map(two,full,full,c,d,0);
    auto first=a;map(one,dark,dark,a,b,0);map(two,dark,dark,c,d,0);
    require(a==c,"equal timestamps changed curve");
    map(one,dark,dark,a,b,200000000);map(two,dark,dark,c,d,100000000);map(two,dark,dark,c,d,200000000);
    require(a==c,"temporal smoothing depends on frame count");
    auto saved=a;auto e=one.process({full.data(),full.size()},{full.data(),full.size()},{nullptr,a.size()},{b.data(),b.size()},300000000);
    require(e.error==M::ErrorCode::invalid_buffer&&a==saved,"null transaction modified output");
    e=one.process({full.data(),full.size()},{full.data(),full.size()},{a.data(),a.size()},{a.data(),a.size()},300000000);
    require(e.error==M::ErrorCode::overlapping_buffers,"alias accepted");
    full.back()=1024;e=map(one,full,full,a,b,300000000);
    require(e.error==M::ErrorCode::sample_out_of_range&&a==saved,"bad sample modified output");
    full.back()=1023;e=map(one,full,full,a,b,1);require(e.error==M::ErrorCode::timestamp_regressed,"backwards timestamp accepted");
    auto prior=map(one,dark,dark,a,b,200000000).frame.revision;one.reset();
    require(map(one,full,full,a,b,1).frame.revision>prior,"reset reused revision");
    M::Config cfg;cfg.clip_limit=std::numeric_limits<double>::quiet_NaN();M invalid(cfg);
    require(map(invalid,full,full,a,b,1).error==M::ErrorCode::invalid_config,"NaN accepted");
    M moved(std::move(one));require(map(one,full,full,a,b,2).error==M::ErrorCode::moved_from,"moved object accepted");
}
}
int main(){try{invariants();temporal_and_errors();std::cout<<"Shared display LUT: detail, stereo parity, highlight/noise bounds, time and errors passed\n";return 0;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
