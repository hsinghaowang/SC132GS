#include "Main10Encoder.hpp"
#include <linux/videodev2.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <fcntl.h>
#include <unistd.h>
#include <cerrno>
#include <cstring>
#include <deque>
#include <string>

namespace stereo_rtsp::detail {
EncoderError::EncoderError(EncoderErrorCode value, const char* operation, int error)
    : std::runtime_error(std::string(operation)+": "+std::strerror(error)),
      code(value), system_error(error) {}
struct Main10Encoder::Impl {
    struct Buffer { void* memory; unsigned length; };
    int fd{-1}, width, height;
    unsigned stride{}, scanlines{}, used{};
    bool input_started{}, capture_started{};
    std::vector<Buffer> input, output;
    std::deque<unsigned> available;
    Impl(int w,int h,int fps,int bitrate):width(w),height(h) {
        try {
            fd=::open("/dev/video33",O_RDWR|O_NONBLOCK|O_CLOEXEC);
            if(fd<0) fail(EncoderErrorCode::device,"open encoder");
            format(V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,V4L2_PIX_FMT_HEVC);
            auto raw=format(V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE,V4L2_PIX_FMT_P010);
            stride=raw.fmt.pix_mp.plane_fmt[0].bytesperline;
            scanlines=raw.fmt.pix_mp.height;
            used=raw.fmt.pix_mp.plane_fmt[0].sizeimage;
            if(stride<static_cast<unsigned>(w*2) || scanlines<static_cast<unsigned>(h) ||
               used<stride*(scanlines+scanlines/2))
                throw EncoderError(EncoderErrorCode::configuration,"P010 layout",EINVAL);
            auto coded=format(V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,V4L2_PIX_FMT_HEVC);
            if(coded.fmt.pix_mp.width!=static_cast<unsigned>(w) || coded.fmt.pix_mp.height!=static_cast<unsigned>(h))
                throw EncoderError(EncoderErrorCode::configuration,"HEVC dimensions",EINVAL);
            control(V4L2_CID_MPEG_VIDEO_HEVC_PROFILE,V4L2_MPEG_VIDEO_HEVC_PROFILE_MAIN_10);
            control(V4L2_CID_MPEG_VIDEO_BITRATE,bitrate);
            control(V4L2_CID_MPEG_VIDEO_GOP_SIZE,fps);
            control(V4L2_CID_MPEG_VIDEO_B_FRAMES,0);
            control(V4L2_CID_MPEG_VIDEO_PREPEND_SPSPPS_TO_IDR,1);
            // Qualcomm VUI timing control, same control used by the legacy path.
            control(0x00992043,1);
            v4l2_streamparm p{}; p.type=V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
            p.parm.output.timeperframe.numerator=1; p.parm.output.timeperframe.denominator=fps;
            call(VIDIOC_S_PARM,&p,"encoder frame rate");
            // Qualcomm uses OUTPUT for operating rate and CAPTURE for coded FPS.
            p.type=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
            p.parm.capture.timeperframe.numerator=1;
            p.parm.capture.timeperframe.denominator=fps;
            call(VIDIOC_S_PARM,&p,"encoder coded frame rate");
            allocate(V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE,input);
            allocate(V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,output);
            for(unsigned i=0;i<input.size();++i) available.push_back(i);
            for(unsigned i=0;i<output.size();++i) queue(V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,i,output[i],0,0);
        } catch(...) { release(); throw; }
    }
    ~Impl(){release();}
    void release() noexcept {
        auto in=V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE,out=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        if(input_started) ::ioctl(fd,VIDIOC_STREAMOFF,&in);
        if(capture_started) ::ioctl(fd,VIDIOC_STREAMOFF,&out);
        for(auto b:input) ::munmap(b.memory,b.length);
        for(auto b:output) ::munmap(b.memory,b.length);
        input.clear();output.clear();
        if(fd>=0) ::close(fd);
        fd=-1;
    }
    [[noreturn]] void fail(EncoderErrorCode code,const char* operation){throw EncoderError(code,operation,errno);}
    int ioctl_retry(unsigned long request,void* argument) {
        int rc; do {rc=::ioctl(fd,request,argument);} while(rc<0 && errno==EINTR); return rc;
    }
    void call(unsigned long request,void* argument,const char* operation) {
        if(ioctl_retry(request,argument)<0) fail(EncoderErrorCode::streaming,operation);
    }
    void control(unsigned id,int value) {v4l2_control c{};c.id=id;c.value=value;call(VIDIOC_S_CTRL,&c,"encoder control");}
    v4l2_format format(v4l2_buf_type type,unsigned pixel) {
        v4l2_format f{};f.type=type;f.fmt.pix_mp.width=width;f.fmt.pix_mp.height=height;
        f.fmt.pix_mp.pixelformat=pixel;f.fmt.pix_mp.field=V4L2_FIELD_NONE;
        f.fmt.pix_mp.colorspace=V4L2_COLORSPACE_REC709;
        f.fmt.pix_mp.xfer_func=V4L2_XFER_FUNC_NONE;
        f.fmt.pix_mp.ycbcr_enc=V4L2_YCBCR_ENC_709;
        f.fmt.pix_mp.quantization=V4L2_QUANTIZATION_FULL_RANGE;
        call(VIDIOC_S_FMT,&f,"encoder format");
        if(f.fmt.pix_mp.pixelformat!=pixel || f.fmt.pix_mp.num_planes!=1)
            throw EncoderError(EncoderErrorCode::configuration,"encoder format rejected",EINVAL);
        return f;
    }
    void allocate(v4l2_buf_type type,std::vector<Buffer>& buffers) {
        v4l2_requestbuffers r{};r.type=type;r.memory=V4L2_MEMORY_MMAP;r.count=8;
        call(VIDIOC_REQBUFS,&r,"encoder buffers");
        if(r.count<4) throw EncoderError(EncoderErrorCode::buffer,"encoder buffer count",ENOMEM);
        for(unsigned i=0;i<r.count;++i){
            v4l2_plane plane{};v4l2_buffer b{};b.type=type;b.memory=V4L2_MEMORY_MMAP;
            b.index=i;b.length=1;b.m.planes=&plane;call(VIDIOC_QUERYBUF,&b,"encoder mapping");
            void* p=::mmap(nullptr,plane.length,PROT_READ|PROT_WRITE,MAP_SHARED,fd,plane.m.mem_offset);
            if(p==MAP_FAILED) fail(EncoderErrorCode::buffer,"encoder mmap");
            buffers.push_back({p,plane.length});
        }
    }
    void queue(v4l2_buf_type type,unsigned index,Buffer& mapping,unsigned bytes,std::int64_t pts) {
        v4l2_plane plane{};plane.length=mapping.length;plane.bytesused=bytes;
        v4l2_buffer b{};b.type=type;b.memory=V4L2_MEMORY_MMAP;b.index=index;b.length=1;b.m.planes=&plane;
        b.timestamp.tv_sec=pts/1'000'000'000;b.timestamp.tv_usec=(pts%1'000'000'000)/1000;
        call(VIDIOC_QBUF,&b,"encoder queue");
    }
    void recycle_input() {
        if(!input_started)return;
        for(;;){
            v4l2_plane p{};v4l2_buffer b{};b.type=V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
            b.memory=V4L2_MEMORY_MMAP;b.length=1;b.m.planes=&p;
            if(ioctl_retry(VIDIOC_DQBUF,&b)<0){if(errno==EAGAIN)return;fail(EncoderErrorCode::streaming,"encoder input dequeue");}
            if(b.index>=input.size())throw EncoderError(EncoderErrorCode::buffer,"encoder input index",EINVAL);
            available.push_back(b.index);
        }
    }
    bool submit(std::span<const std::uint16_t> luma,std::int64_t pts) {
        if(luma.size()!=static_cast<std::size_t>(width)*height || pts<0)
            throw EncoderError(EncoderErrorCode::configuration,"R16 frame",EINVAL);
        recycle_input();if(available.empty())return false;
        unsigned index=available.front();available.pop_front();auto& b=input[index];
        // Fill both padding and chroma, without rescaling luma or losing low bits.
        std::memset(b.memory,0,b.length);
        for(int y=0;y<height;++y){
            auto* row=reinterpret_cast<std::uint16_t*>(static_cast<char*>(b.memory)+y*stride);
            for(int x=0;x<width;++x)row[x]=luma[static_cast<std::size_t>(y)*width+x]<<6;
        }
        auto* chroma=static_cast<char*>(b.memory)+stride*scanlines;
        for(unsigned y=0;y<scanlines/2;++y){
            auto* row=reinterpret_cast<std::uint16_t*>(chroma+y*stride);
            for(unsigned x=0;x<stride/2;++x)row[x]=512<<6;
        }
        queue(V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE,index,b,used,pts);
        if(!capture_started){auto type=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;call(VIDIOC_STREAMON,&type,"capture STREAMON");capture_started=true;}
        if(!input_started){auto type=V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;call(VIDIOC_STREAMON,&type,"input STREAMON");input_started=true;}
        return true;
    }
    std::vector<EncodedFrame> receive(){
        std::vector<EncodedFrame> result;
        if(!input_started)return result;
        for(;;){
            v4l2_plane p{};v4l2_buffer b{};b.type=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
            b.memory=V4L2_MEMORY_MMAP;b.length=1;b.m.planes=&p;
            if(ioctl_retry(VIDIOC_DQBUF,&b)<0){if(errno==EAGAIN)break;fail(EncoderErrorCode::streaming,"encoder capture dequeue");}
            if(b.index>=output.size() || p.bytesused>output[b.index].length || p.data_offset>p.bytesused || (b.flags&V4L2_BUF_FLAG_ERROR))
                throw EncoderError(EncoderErrorCode::buffer,"encoded buffer",EIO);
            auto* bytes=static_cast<std::uint8_t*>(output[b.index].memory);
            if(p.bytesused>p.data_offset)result.push_back({{bytes+p.data_offset,bytes+p.bytesused},
                b.timestamp.tv_sec*1'000'000'000LL+b.timestamp.tv_usec*1000LL,
                (b.flags&V4L2_BUF_FLAG_KEYFRAME)!=0});
            queue(V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,b.index,output[b.index],0,0);
        }
        return result;
    }
};
Main10Encoder::Main10Encoder(int w,int h,int fps,int bitrate):impl_(std::make_unique<Impl>(w,h,fps,bitrate)){}
Main10Encoder::~Main10Encoder()=default;
Main10Encoder::Main10Encoder(Main10Encoder&&) noexcept=default;
Main10Encoder& Main10Encoder::operator=(Main10Encoder&&) noexcept=default;
bool Main10Encoder::submit(std::span<const std::uint16_t> luma,std::int64_t pts){return impl_->submit(luma,pts);}
std::vector<EncodedFrame> Main10Encoder::receive(){return impl_->receive();}
void Main10Encoder::request_keyframe(){impl_->control(V4L2_CID_MPEG_VIDEO_FORCE_KEY_FRAME,0);}
} // namespace stereo_rtsp::detail
