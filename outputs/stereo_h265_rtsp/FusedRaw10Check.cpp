#include "BayerLuma.hpp"
#include "sc132gs-hdr-ae-policy.hpp"
#include "sc132gs-linear-ae-policy.hpp"
#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {
void require(bool condition) { if (!condition) throw std::runtime_error("fused RAW10 mismatch"); }
unsigned reference(const std::vector<unsigned>& p, int w, int h, int x, int y, bool eight = false) {
    const int l=x?x-1:1, r=x==w-1?w-2:x+1, u=y?y-1:1, d=y==h-1?h-2:y+1;
    const auto at=[&](int xx,int yy){return p[static_cast<std::size_t>(yy)*w+xx];};
    const unsigned horizontal=(at(l,y)+at(r,y)+1)/2, vertical=(at(x,u)+at(x,d)+1)/2;
    const unsigned diagonal=(at(l,u)+at(r,u)+at(l,d)+at(r,d)+2)/4;
    const unsigned cross=(at(l,y)+at(r,y)+at(x,u)+at(x,d)+2)/4;
    unsigned red,green,blue;
    if((x&1)==(y&1)) {green=cross;red=(y&1)?diagonal:at(x,y);blue=(y&1)?at(x,y):diagonal;}
    else {green=at(x,y);red=(y&1)?vertical:horizontal;blue=(y&1)?horizontal:vertical;}
    const auto weighted=54*red+183*green+19*blue;
    return eight?std::min(255U,(weighted+512)/1024):(weighted+128)/256;
}
}
int main() {
    try {
        std::uint32_t random=0x19810827;
        std::uint64_t digest=1469598103934665603ULL;
        for(int width:{12,16,20,28,32,36,64,1088}) for(int padding:{0,7}) {
            const int height=width==1088?1280:24, stride=width*5/4+padding;
            std::vector<unsigned> pixels(static_cast<std::size_t>(width)*height);
            std::vector<std::uint8_t> raw(static_cast<std::size_t>(stride)*height,0xa5);
            for(int y=0;y<height;++y) for(int x=0;x<width;x+=4) {
                auto* group=raw.data()+static_cast<std::size_t>(y)*stride+x/4*5;group[4]=0;
                for(unsigned lane=0;lane<4;++lane) {
                    random^=random<<13;random^=random>>17;random^=random<<5;
                    const unsigned v=(x%16==0 && y%3==0)?1007+lane:(random&1023);
                    pixels[static_cast<std::size_t>(y)*width+x+lane]=v;
                    group[lane]=v>>2;group[4]|=(v&3)<<(2*lane);
                }
            }
            const auto expected_meter=sc132gs::hdr_ae::measure_raw10(raw,width,height,stride);
            const auto expected_highlights=sc132gs::linear_ae::measure_packed_raw10(raw.data(),raw.size(),width,height,stride);
            stereo_rtsp::detail::BayerLuma converter(width,height);
            converter.unpack(raw,stride);
            // Emulate DMA overwriting the returned mapping immediately at QBUF.
            std::fill(raw.begin(),raw.end(),0);
            const auto meter=converter.statistics();
            require(meter.histogram==expected_meter.histogram);
            require(meter.sample_count==expected_highlights.sample_count);
            require(meter.near_saturated_count==expected_highlights.near_saturated_count);
            for(int scale:{1,2,4}) {
                if(width%scale || height%scale)continue;
                const int ow=width/scale,oh=height/scale;
                std::vector<std::uint16_t> gray(static_cast<std::size_t>(ow)*oh);
                std::vector<std::uint8_t> gray8(gray.size());
                converter.render10(gray,scale);converter.render(gray8,scale);
                for(int y=0;y<oh;++y)for(int x=0;x<ow;++x) {
                    const auto expected=reference(pixels,width,height,x*scale,y*scale);
                    const auto i=static_cast<std::size_t>(y)*ow+x;
                    require(gray[i]==expected);
                    require(gray8[i]==reference(pixels,width,height,x*scale,y*scale,true));
                    digest=(digest^gray[i])*1099511628211ULL;
                }
            }
            bool rejected=false;
            try {converter.unpack(std::span<const std::uint8_t>(raw).first(1),stride);}
            catch(const std::invalid_argument&){rejected=true;}
            require(rejected);
            rejected=false;
            try {(void)converter.statistics();}catch(const std::logic_error&){rejected=true;}
            require(rejected);
        }
        std::cout<<"raw_digest="<<digest<<"; scalar reference, full RAW highlight denominator, HDR grid, padding, SIMD tails, scales, mapping overwrite passed\n";
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
