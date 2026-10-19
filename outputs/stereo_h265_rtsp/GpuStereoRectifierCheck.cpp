#include "GpuStereoRectifier.hpp"
#include <algorithm>
#include <fstream>
#include <iostream>
#include <stdexcept>
using namespace stereo_rtsp::detail;
template<class T>std::vector<T> load(const std::string& p,std::size_t n){std::vector<T> a(n);std::ifstream f(p,std::ios::binary);if(!f.read(reinterpret_cast<char*>(a.data()),n*sizeof(T)))throw std::runtime_error("fixture");return a;}
int main(int argc,char** argv){
    if(argc!=2)return 2;
    try{
        std::string p=argv[1];auto a=load<std::uint16_t>(p+"/cam0.u16",1088*1280),b=load<std::uint16_t>(p+"/cam1.u16",1088*1280);
        for(const auto& name:{"identity","calibration"}){
            auto expected=load<std::uint16_t>(p+"/"+name+"-expected.u16",2176*1280);
            GpuStereoRectifier rectifier(p+"/"+name+".map");std::vector<std::uint16_t> out;
            const auto invalid=rectifier.process(a.data(),b.data(),a.size()-1,out);
            if(!std::holds_alternative<RectificationError>(invalid))throw std::runtime_error("invalid geometry accepted");
            auto result=rectifier.process(a.data(),b.data(),a.size(),out);
            if(std::holds_alternative<RectificationError>(result)||out.size()!=expected.size())throw std::runtime_error("GPU process");
            unsigned max_error=0;std::size_t low_bits=0;
            for(std::size_t i=0;i<out.size();++i){max_error=std::max(max_error,unsigned(std::abs(int(out[i])-int(expected[i]))));low_bits+=(out[i]&3)!=0;if(out[i]>1023)throw std::runtime_error("not mono10");}
            const unsigned tolerance=std::string(name)=="identity"?0:1; // OpenCV CV_16U halfway rounding can differ by one.
            if(max_error>tolerance||!low_bits)throw std::runtime_error("remap/eye order/10-bit mismatch");
            std::cout<<name<<" max_difference="<<max_error<<" nonzero_low_bits="<<low_bits<<" gpu_ns="<<std::get<RectificationTiming>(result).gpu_ns<<'\n';
            auto a8=load<std::uint8_t>(p+"/cam0.u8",1088*1280),b8=load<std::uint8_t>(p+"/cam1.u8",1088*1280);
            auto expected8=load<std::uint8_t>(p+"/"+name+"-expected.u8",2176*1280);
            std::vector<std::uint8_t> out8;
            if(!std::holds_alternative<RectificationError>(rectifier.process8(a8.data(),b8.data(),a8.size()-1,out8)))
                throw std::runtime_error("invalid 8-bit geometry accepted");
            const auto result8=rectifier.process8(a8.data(),b8.data(),a8.size(),out8);
            if(std::holds_alternative<RectificationError>(result8)||out8.size()!=expected8.size())throw std::runtime_error("GPU process8");
            unsigned error8=0;
            for(std::size_t i=0;i<out8.size();++i) {
                error8=std::max(error8,unsigned(std::abs(int(out8[i])-int(expected8[i]))));
                if(out8[i]<16||out8[i]>235)throw std::runtime_error("8-bit legal range/border");
            }
            if(error8>tolerance)throw std::runtime_error("8-bit OpenCV remap/eye order mismatch");
            std::cout<<name<<" bits=8 max_difference="<<error8<<" gpu_ns="<<std::get<RectificationTiming>(result8).gpu_ns<<'\n';
            auto fa=load<std::uint8_t>(p+"/cam0-full.u8",1088*1280),fb=load<std::uint8_t>(p+"/cam1-full.u8",1088*1280);
            auto fe=load<std::uint8_t>(p+"/"+name+"-expected-full.u8",2176*1280);
            const auto full=rectifier.process8(fa.data(),fb.data(),fa.size(),out8,stereo_rtsp::VideoRange::full);
            if(std::holds_alternative<RectificationError>(full))throw std::runtime_error("full-range remap failed");
            unsigned full_error=0;for(std::size_t i=0;i<out8.size();++i)full_error=std::max(full_error,unsigned(std::abs(int(out8[i])-int(fe[i]))));
            if(full_error>tolerance)throw std::runtime_error("full-range border/remap mismatch");
            std::cout<<name<<" bits=8 range=full max_difference="<<full_error<<'\n';
        }
        bool rejected=false;try{GpuStereoRectifier invalid(p+"/invalid.map");}catch(const RectificationError&){rejected=true;}
        if(!rejected)throw std::runtime_error("invalid map accepted");
        std::cout<<"PASS mono10 and limited Y8 remap, eye order, fractional/border sampling, malformed map, geometry\n";
    }catch(const RectificationError& e){std::cerr<<"rectification_error="<<int(e.code)<<" native="<<e.native_code<<'\n';return 1;}
    catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
