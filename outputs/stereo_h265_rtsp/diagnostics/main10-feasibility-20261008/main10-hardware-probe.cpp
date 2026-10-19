#include <linux/videodev2.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <poll.h>
#include <fcntl.h>
#include <unistd.h>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <vector>
#include <chrono>

class Encoder final {
    struct Buffer { void* memory; unsigned length; };
    int fd_{-1};
    std::vector<Buffer> input_, output_;
    bool input_started_{}, output_started_{};
    unsigned width_{640}, height_{480};
    unsigned fps_{30};
    bool tenbit_{true};
    void call(unsigned long request, void* argument, const char* name) {
        int rc;
        do { rc = ioctl(fd_, request, argument); } while (rc < 0 && errno == EINTR);
        if (rc < 0) { std::fprintf(stderr, "%s: %s\n", name, std::strerror(errno)); throw std::runtime_error(name); }
    }
    v4l2_format format(v4l2_buf_type type, unsigned pixel) {
        v4l2_format f{}; f.type=type;
        f.fmt.pix_mp.width=width_; f.fmt.pix_mp.height=height_;
        f.fmt.pix_mp.pixelformat=pixel; f.fmt.pix_mp.field=V4L2_FIELD_NONE;
        f.fmt.pix_mp.colorspace=V4L2_COLORSPACE_REC709;
        f.fmt.pix_mp.xfer_func=V4L2_XFER_FUNC_709;
        f.fmt.pix_mp.ycbcr_enc=V4L2_YCBCR_ENC_709;
        f.fmt.pix_mp.quantization=V4L2_QUANTIZATION_LIM_RANGE;
        call(VIDIOC_S_FMT,&f,"S_FMT");
        std::printf("format type=%u size=%ux%u stride=%u bytes=%u planes=%u\n",type,
            f.fmt.pix_mp.width,f.fmt.pix_mp.height,f.fmt.pix_mp.plane_fmt[0].bytesperline,
            f.fmt.pix_mp.plane_fmt[0].sizeimage,f.fmt.pix_mp.num_planes);
        return f;
    }
    void allocate(v4l2_buf_type type, std::vector<Buffer>& buffers) {
        v4l2_requestbuffers r{}; r.type=type; r.memory=V4L2_MEMORY_MMAP; r.count=8;
        call(VIDIOC_REQBUFS,&r,"REQBUFS");
        for(unsigned i=0;i<r.count;i++) {
            v4l2_plane plane{}; v4l2_buffer b{};
            b.type=type; b.memory=V4L2_MEMORY_MMAP; b.index=i; b.length=1; b.m.planes=&plane;
            call(VIDIOC_QUERYBUF,&b,"QUERYBUF");
            void* p=mmap(nullptr,plane.length,PROT_READ|PROT_WRITE,MAP_SHARED,fd_,plane.m.mem_offset);
            if(p==MAP_FAILED) throw std::runtime_error("mmap");
            buffers.push_back({p,plane.length});
        }
    }
    void queue(v4l2_buf_type type,unsigned index,Buffer& buffer,unsigned used) {
        v4l2_plane plane{}; plane.length=buffer.length; plane.bytesused=used;
        v4l2_buffer b{}; b.type=type; b.memory=V4L2_MEMORY_MMAP; b.index=index;
        b.length=1; b.m.planes=&plane;
        b.timestamp.tv_sec=1; b.timestamp.tv_usec=index*1000000/fps_;
        call(VIDIOC_QBUF,&b,"QBUF");
    }
public:
    Encoder() { fd_=open("/dev/video33",O_RDWR|O_NONBLOCK); if(fd_<0) throw std::runtime_error("open"); }
    Encoder(const Encoder&)=delete;
    Encoder& operator=(const Encoder&)=delete;
    ~Encoder() {
        auto in=V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE, out=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        if(input_started_) ioctl(fd_,VIDIOC_STREAMOFF,&in);
        if(output_started_) ioctl(fd_,VIDIOC_STREAMOFF,&out);
        for(auto b:input_) munmap(b.memory,b.length);
        for(auto b:output_) munmap(b.memory,b.length);
        if(fd_>=0) close(fd_);
    }
    void run(const char* path, bool tenbit, int profile, unsigned width, unsigned height, bool capture_first, unsigned fps) {
        tenbit_=tenbit; width_=width; height_=height; fps_=fps;
        format(V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,V4L2_PIX_FMT_HEVC);
        auto raw=format(V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE,tenbit_?V4L2_PIX_FMT_P010:V4L2_PIX_FMT_NV12);
        format(V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,V4L2_PIX_FMT_HEVC);
        v4l2_control c{}; c.id=V4L2_CID_MPEG_VIDEO_HEVC_PROFILE; c.value=profile;
        if(profile>=0) call(VIDIOC_S_CTRL,&c,"profile S_CTRL");
        call(VIDIOC_G_CTRL,&c,"profile G_CTRL");
        std::printf("profile=%d\n",c.value);
        v4l2_streamparm p{}; p.type=V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
        p.parm.output.timeperframe.numerator=1; p.parm.output.timeperframe.denominator=fps_;
        call(VIDIOC_S_PARM,&p,"S_PARM");
        allocate(V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE,input_);
        allocate(V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,output_);
        for(unsigned i=0;i<output_.size();i++) queue(V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,i,output_[i],0);
        unsigned stride=raw.fmt.pix_mp.plane_fmt[0].bytesperline;
        unsigned scanlines=raw.fmt.pix_mp.height;
        for(unsigned i=0;i<8;i++) {
            auto& b=input_.at(i); std::memset(b.memory,0,b.length);
            for(unsigned y=0;y<scanlines;y++) {
                auto* row=reinterpret_cast<unsigned short*>(static_cast<char*>(b.memory)+y*stride);
                if(tenbit_) for(unsigned x=0;x<width_;x++) row[x]=static_cast<unsigned short>((64+(x*876/(width_-1)+i)%877)<<6);
                else for(unsigned x=0;x<width_;x++) reinterpret_cast<unsigned char*>(row)[x]=16+(x*219/(width_-1)+i)%220;
            }
            auto* chroma=static_cast<char*>(b.memory)+stride*scanlines;
            for(unsigned y=0;y<scanlines/2;y++) {
                auto* row=reinterpret_cast<unsigned short*>(chroma+y*stride);
                if(tenbit_) for(unsigned x=0;x<width_;x++) row[x]=512<<6;
                else std::memset(row,128,width_);
            }
            queue(V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE,i,b,raw.fmt.pix_mp.plane_fmt[0].sizeimage);
        }
        auto in=V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE, out=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        if(capture_first) { call(VIDIOC_STREAMON,&out,"capture STREAMON"); output_started_=true; }
        call(VIDIOC_STREAMON,&in,"input STREAMON"); input_started_=true;
        if(!capture_first) { call(VIDIOC_STREAMON,&out,"capture STREAMON"); output_started_=true; }
        FILE* file=std::fopen(path,"wb"); if(!file) throw std::runtime_error("file");
        unsigned frames=0;
        auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);
        while(frames<8 && std::chrono::steady_clock::now()<deadline) {
            pollfd item{fd_,POLLIN|POLLERR,0}; poll(&item,1,1000);
            v4l2_plane plane{}; v4l2_buffer b{}; b.type=out; b.memory=V4L2_MEMORY_MMAP; b.length=1; b.m.planes=&plane;
            if(ioctl(fd_,VIDIOC_DQBUF,&b)<0) {
                if(errno==EAGAIN) continue;
                std::fclose(file); throw std::runtime_error(std::strerror(errno));
            }
            std::printf("encoded index=%u bytes=%u flags=%x\n",b.index,plane.bytesused,b.flags);
            std::fwrite(output_.at(b.index).memory,1,plane.bytesused,file); ++frames;
        }
        std::fclose(file);
        if(frames!=8) throw std::runtime_error("encoded frame timeout");
    }
};
int main(int argc,char** argv) {
    try { Encoder encoder; encoder.run(argc>1?argv[1]:"/tmp/main10-native.hevc",
        argc<3 || std::strcmp(argv[2],"nv12")!=0, argc>3?std::stoi(argv[3]):2,
        argc>4?std::stoul(argv[4]):640,argc>5?std::stoul(argv[5]):480,
        argc>6 && std::strcmp(argv[6],"capture-first")==0,
        argc>7?std::stoul(argv[7]):30); }
    catch(const std::exception& e) { std::fprintf(stderr,"probe failed: %s\n",e.what()); return 1; }
}
