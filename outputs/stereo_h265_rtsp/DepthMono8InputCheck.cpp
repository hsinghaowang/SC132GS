#include "depth/GpuStereoDepth.hpp"
#include "depth/Mono8RectificationKernel.hpp"
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <type_traits>
#include <vector>

// Execute the production OpenCL kernel bodies on the CPU. Only the OpenCL
// address-space qualifiers and work-item lookup are replaced, not arithmetic.
namespace kernel_contract {
using uchar=std::uint8_t;
using uint=std::uint32_t;
std::size_t work_item{};
std::size_t get_global_id(unsigned){return work_item;}
#define __global
#define __kernel
#define STEREO_MONO8_SOURCE(...) __VA_ARGS__
#include "depth/Mono8Rectification.cl.inc"
#undef STEREO_MONO8_SOURCE
#undef __kernel
#undef __global
}

namespace {
constexpr std::size_t native=1088*1280,rectified=544*640;
bool require(bool condition,const char* message){
    if(!condition)std::cerr<<"FAIL "<<message<<'\n';
    return condition;
}
// Independent floating-point bilinear oracle, including zero border fill.
std::uint8_t reference(const std::vector<std::uint8_t>& image,int qx,int qy){
    const double x=qx/32.0,y=qy/32.0;
    const int ix=static_cast<int>(std::floor(x)),iy=static_cast<int>(std::floor(y));
    const double fx=x-ix,fy=y-iy;
    auto sample=[&](int xx,int yy)->double{
        return xx<0||xx>=1088||yy<0||yy>=1280?0:image[std::size_t(yy)*1088+xx];
    };
    return static_cast<std::uint8_t>(std::floor(
        sample(ix,iy)*(1-fx)*(1-fy)+sample(ix+1,iy)*fx*(1-fy)+
        sample(ix,iy+1)*(1-fx)*fy+sample(ix+1,iy+1)*fx*fy+0.5));
}
}

int main(){
    using stereo_rtsp::detail::depth_gpu::StereoView8;
    static_assert(std::is_same_v<decltype(StereoView8::cam0_right),const std::uint8_t*>);
    std::vector<std::uint8_t> cam0(native,235),cam1(native,16);
    // Every 8-bit code must survive constant-region remap, including codes
    // 16 and 235 from the shared video LUT, without another >>2 or OETF.
    for(unsigned code=0;code<256;++code){
        cam1[0]=cam1[1]=cam1[1088]=cam1[1089]=static_cast<std::uint8_t>(code);
        for(int fy=0;fy<32;++fy)for(int fx=0;fx<32;++fx)
            if(!require(kernel_contract::mono8_remap(cam1.data(),fx,fy)==code,"constant mono8 code changed"))return 1;
    }
    cam1[0]=16;cam1[1]=235;cam1[1088]=63;cam1[1089]=128;
    for(int fy=0;fy<32;++fy)for(int fx=0;fx<32;++fx)
        if(!require(kernel_contract::mono8_remap(cam1.data(),fx,fy)==reference(cam1,fx,fy),"fractional remap rounding"))return 1;
    for(int qy=-32;qy<=32;++qy)for(int qx=-32;qx<=32;++qx)
        if(!require(kernel_contract::mono8_remap(cam1.data(),qx,qy)==reference(cam1,qx,qy),"zero border interpolation"))return 1;
    for(int qy=1279*32;qy<=1280*32;++qy)for(int qx=1087*32;qx<=1088*32;++qx)
        if(!require(kernel_contract::mono8_remap(cam0.data(),qx,qy)==reference(cam0,qx,qy),"bottom right border interpolation"))return 1;

    std::vector<int> left_map(native*2),right_map(native*2);
    std::vector<std::uint8_t> left(rectified+1,77),right(rectified+1,77);
    cam1[0]=16;
    for(auto id:{std::size_t(0),rectified-1,rectified,2*rectified-1,2*rectified}){
        kernel_contract::work_item=id;
        kernel_contract::rectify_native8(cam0.data(),cam1.data(),left_map.data(),right_map.data(),left.data(),right.data());
    }
    if(!require(left[0]==16&&left[rectified-1]==16&&right[0]==235&&right[rectified-1]==235,"eye routing / byte range"))return 1;
    if(!require(left.back()==77&&right.back()==77,"rectified output bounds"))return 1;
    // Use distinct fractional coordinates per eye to catch switched maps.
    cam0[0]=235;cam0[1]=16;cam0[1088]=128;cam0[1089]=63;
    left_map[0]=7;left_map[1]=23;right_map[0]=11;right_map[1]=29;
    kernel_contract::work_item=0;
    kernel_contract::rectify_native8(cam0.data(),cam1.data(),left_map.data(),right_map.data(),left.data(),right.data());
    kernel_contract::work_item=rectified;
    kernel_contract::rectify_native8(cam0.data(),cam1.data(),left_map.data(),right_map.data(),left.data(),right.data());
    if(!require(left[0]==reference(cam1,7,23)&&right[0]==reference(cam0,11,29),"separate eye maps"))return 1;

    std::fill(left_map.begin(),left_map.end(),0);std::fill(right_map.begin(),right_map.end(),0);
    std::vector<std::uint8_t> gray(native*3+1,77);
    for(auto id:{std::size_t(0),native-1,native,2*native-1,2*native}){
        kernel_contract::work_item=id;
        kernel_contract::rectify_gray8(cam0.data(),cam1.data(),left_map.data(),right_map.data(),gray.data());
    }
    if(!require(gray[0]==16&&gray[1088]==235&&gray[2*native-1]==235,"gray output preserves mapped Y codes"))return 1;
    if(!require(gray[2*native]==128&&gray[3*native-1]==128&&gray.back()==77,"gray UV and output bounds"))return 1;
    std::cout<<"PASS actual mono8 kernels: all codes, fractional rounding, borders, eye maps, limited-range codes and bounds\n";
}
