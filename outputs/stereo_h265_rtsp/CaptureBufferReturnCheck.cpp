// Exercise the actual Device dequeue/requeue implementation, substituting
// only Linux syscalls. No real device is opened by this fixture.
#if defined(__GNUC__)
// This fixture includes the actual TU to reach its private Device; internal
// linkage is intentional here, unlike when linking the production TU normally.
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wsubobject-linkage"
#endif
#include "StereoCapture.cpp"
#if defined(__GNUC__)
#pragma GCC diagnostic pop
#endif
#include <cstdarg>
#include <iterator>

namespace {
constexpr int fixture_fd=903;
constexpr std::size_t raw_bytes=1088*1280*5/4;
struct Fixture {
    std::array<std::vector<std::uint8_t>,8> mappings;
    unsigned qbuf_calls{};
    bool streaming{},error_buffer{},short_buffer{},return_error{};
} fixture;
void require_fixture(bool condition){if(!condition)throw std::runtime_error("buffer return fixture failed");}
void fill_raw(std::vector<std::uint8_t>& raw){
    raw.resize(raw_bytes);
    for(std::size_t i=0;i<raw.size();i+=5){raw[i]=raw[i+1]=raw[i+2]=raw[i+3]=128;raw[i+4]=0;}
}
}
extern "C" int __real_open(const char*,int,...);
extern "C" int __real_close(int);
extern "C" int __real_ioctl(int,unsigned long,...);
extern "C" void* __real_mmap(void*,std::size_t,int,int,int,off_t);
extern "C" int __real_munmap(void*,std::size_t);
extern "C" int __wrap_open(const char* path,int flags,...){
    if(std::strcmp(path,"/fixture/camera")==0)return fixture_fd;
    if(flags&O_CREAT){va_list args;va_start(args,flags);const int mode=va_arg(args,int);va_end(args);return __real_open(path,flags,mode);}
    return __real_open(path,flags);
}
extern "C" int __wrap_close(int fd){return fd==fixture_fd?0:__real_close(fd);}
extern "C" void* __wrap_mmap(void* a,std::size_t n,int p,int f,int fd,off_t offset){
    if(fd!=fixture_fd)return __real_mmap(a,n,p,f,fd,offset);
    auto& raw=fixture.mappings.at(static_cast<std::size_t>(offset)/raw_bytes);fill_raw(raw);return raw.data();
}
extern "C" int __wrap_munmap(void* a,std::size_t n){
    for(auto& raw:fixture.mappings)if(raw.data()==a)return 0;
    return __real_munmap(a,n);
}
extern "C" int __wrap_ioctl(int fd,unsigned long request,...){
    va_list args;va_start(args,request);void* data=va_arg(args,void*);va_end(args);
    if(fd!=fixture_fd)return __real_ioctl(fd,request,data);
    if(request==VIDIOC_S_FMT){
        auto& f=static_cast<v4l2_format*>(data)->fmt.pix_mp;
        f.num_planes=1;f.plane_fmt[0].bytesperline=1088*5/4;f.plane_fmt[0].sizeimage=raw_bytes;return 0;
    }
    if(request==VIDIOC_REQBUFS){require_fixture(static_cast<v4l2_requestbuffers*>(data)->count==8);return 0;}
    if(request==VIDIOC_QUERYBUF){
        auto& b=*static_cast<v4l2_buffer*>(data);b.m.planes[0].length=raw_bytes;
        b.m.planes[0].m.mem_offset=static_cast<unsigned>(b.index*raw_bytes);return 0;
    }
    if(request==VIDIOC_STREAMON){fixture.streaming=true;return 0;}
    if(request==VIDIOC_STREAMOFF){fixture.streaming=false;return 0;}
    if(request==VIDIOC_DQBUF){
        auto& b=*static_cast<v4l2_buffer*>(data);b.index=0;b.sequence=11;
        b.flags=fixture.error_buffer?V4L2_BUF_FLAG_ERROR:0;
        b.timestamp.tv_sec=1;b.m.planes[0].bytesused=fixture.short_buffer?1:raw_bytes;
        fill_raw(fixture.mappings[0]);return 0;
    }
    if(request==VIDIOC_QBUF){
        ++fixture.qbuf_calls;
        if(fixture.streaming){
            if(fixture.return_error){errno=EIO;return -1;}
            // Detect all late RAW reads: DMA can overwrite as soon as QBUF returns.
            auto& raw=fixture.mappings[static_cast<v4l2_buffer*>(data)->index];
            std::fill(raw.begin(),raw.end(),0);
        }
        return 0;
    }
    errno=ENOTTY;return -1;
}
int main(){
    try {
        using namespace stereo_rtsp;
        detail::CaptureTrace trace;
        Device device("/fixture/camera",1,false,CaptureMode::external_trigger,true,trace,0);
        device.start();require_fixture(fixture.qbuf_calls==8);fixture.qbuf_calls=0;
        auto frame=device.dequeue();require_fixture(frame.has_value() && fixture.qbuf_calls==1);
        require_fixture(std::all_of(frame->luma10.begin(),frame->luma10.end(),[](auto v){return v==512;}));
        require_fixture(frame->hdr.luma_median==512 && frame->highlights.sample_count==1088*1280);
        require_fixture(std::all_of(fixture.mappings[0].begin(),fixture.mappings[0].end(),[](auto v){return v==0;}));
        for(bool error_flag:{false,true}){
            fixture.short_buffer=!error_flag;fixture.error_buffer=error_flag;fixture.qbuf_calls=0;
            bool threw=false;try{(void)device.dequeue();}catch(const std::exception&){threw=true;}
            require_fixture(threw && fixture.qbuf_calls==1);
        }
        fixture.short_buffer=false;fixture.error_buffer=false;fixture.return_error=true;fixture.qbuf_calls=0;
        bool threw=false;try{(void)device.dequeue();}catch(const std::exception&){threw=true;}
        require_fixture(threw && fixture.qbuf_calls==1); // No destructor double QBUF.
        const auto path="/tmp/capture-buffer-return-check-"+std::to_string(::getpid())+".jsonl";
        require_fixture(trace.dump(path));
        std::ifstream file(path);const std::string log((std::istreambuf_iterator<char>(file)),{});
        const auto dq=log.find("\"op\":\"dqbuf\"");
        const auto q=log.find("\"op\":\"qbuf\"",dq);
        const auto stats=log.find("\"op\":\"statistics\"",dq);
        const auto render=log.find("\"op\":\"render\"",dq);
        require_fixture(dq<q && q<stats && stats<render);
        std::cout<<"actual Device: 8 buffers, early QBUF, mapping overwrite, short/error buffer RAII, QBUF failure, event ordering passed\n";
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
