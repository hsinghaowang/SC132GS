#include "RawOpticalCapture.hpp"
#include <linux/videodev2.h>
#include <cerrno>
#include <fcntl.h>
#include <new>
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <utility>
#include <vector>

namespace stereo_rtsp::optical {
namespace {
constexpr auto type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
struct Fault { Error error; };
void check(int result, int eye, const char* operation) {
    if (result < 0) throw Fault{{ErrorCode::system, errno, eye, operation}};
}
void control(int fd, unsigned long request, void* value, int eye, const char* operation) {
    int result;
    do { result=::ioctl(fd,request,value); } while(result<0 && errno==EINTR);
    check(result,eye,operation);
}
std::int64_t monotonic_ns() {
    timespec value{};
    check(::clock_gettime(CLOCK_MONOTONIC,&value),-1,"clock_gettime");
    return value.tv_sec*1'000'000'000LL+value.tv_nsec;
}
class Device final {
public:
    Device(const std::string& path, int eye) : eye_(eye) {
        fd_=::open(path.c_str(),O_RDWR|O_NONBLOCK|O_CLOEXEC);
        check(fd_,eye_,"open camera");
        try {
            v4l2_format format{};
            format.type=type;
            format.fmt.pix_mp.width=1088; format.fmt.pix_mp.height=1280;
            format.fmt.pix_mp.pixelformat=v4l2_fourcc('p','R','A','A');
            format.fmt.pix_mp.field=V4L2_FIELD_NONE;
            control(fd_,VIDIOC_S_FMT,&format,eye_,"S_FMT");
            const auto& pix=format.fmt.pix_mp;
            if(pix.width!=1088 || pix.height!=1280 || pix.num_planes!=1 ||
                pix.pixelformat!=v4l2_fourcc('p','R','A','A') || pix.plane_fmt[0].bytesperline<1360)
                throw Fault{{ErrorCode::invalid_configuration,EINVAL,eye_,"RAW10 geometry"}};
            stride_=static_cast<int>(pix.plane_fmt[0].bytesperline);
            v4l2_requestbuffers request{};
            request.type=type; request.memory=V4L2_MEMORY_MMAP; request.count=8;
            control(fd_,VIDIOC_REQBUFS,&request,eye_,"REQBUFS");
            if(request.count<4) throw Fault{{ErrorCode::invalid_configuration,ENOMEM,eye_,"buffer count"}};
            maps_.reserve(request.count);
            for(std::uint32_t i=0;i<request.count;++i) {
                v4l2_buffer buffer{}; v4l2_plane plane{};
                buffer.type=type; buffer.memory=V4L2_MEMORY_MMAP; buffer.index=i;
                buffer.m.planes=&plane; buffer.length=1;
                control(fd_,VIDIOC_QUERYBUF,&buffer,eye_,"QUERYBUF");
                if(plane.length<static_cast<unsigned>(stride_*1280))
                    throw Fault{{ErrorCode::invalid_configuration,EPROTO,eye_,"RAW10 buffer size"}};
                void* address=::mmap(nullptr,plane.length,PROT_READ|PROT_WRITE,MAP_SHARED,fd_,plane.m.mem_offset);
                if(address==MAP_FAILED) throw Fault{{ErrorCode::system,errno,eye_,"mmap"}};
                maps_.push_back({address,plane.length});
                queue(i);
            }
            auto stream_type=type;
            control(fd_,VIDIOC_STREAMON,&stream_type,eye_,"STREAMON");
            streaming_=true;
        } catch (...) { close(); throw; }
    }
    ~Device() { close(); }
    Device(const Device&)=delete;
    Device& operator=(const Device&)=delete;
    int fd() const noexcept { return fd_; }
    bool dequeue(RawOpticalCapture::Observer& observer) {
        v4l2_buffer buffer{}; v4l2_plane plane{};
        buffer.type=type; buffer.memory=V4L2_MEMORY_MMAP;
        buffer.m.planes=&plane; buffer.length=1;
        int result;
        do { result=::ioctl(fd_,VIDIOC_DQBUF,&buffer); } while(result<0 && errno==EINTR);
        if(result<0 && errno==EAGAIN) return true;
        check(result,eye_,"DQBUF");
        if(buffer.index>=maps_.size() || plane.bytesused<static_cast<unsigned>(stride_*1280) ||
            plane.bytesused>maps_[buffer.index].length || (buffer.flags&V4L2_BUF_FLAG_ERROR))
            throw Fault{{ErrorCode::invalid_frame,EPROTO,eye_,"RAW10 frame"}};
        const FrameView frame{eye_,buffer.sequence,buffer.flags,
            buffer.timestamp.tv_sec*1'000'000'000LL+buffer.timestamp.tv_usec*1'000LL,
            monotonic_ns(),1088,1280,stride_,
            {static_cast<const std::uint8_t*>(maps_[buffer.index].address),plane.bytesused}};
        const bool keep=observer.on_frame(frame);
        queue(buffer.index);
        return keep;
    }
private:
    struct Mapping { void* address{}; std::size_t length{}; };
    void queue(std::uint32_t index) {
        v4l2_buffer buffer{}; v4l2_plane plane{};
        buffer.type=type; buffer.memory=V4L2_MEMORY_MMAP; buffer.index=index;
        buffer.m.planes=&plane; buffer.length=1;
        control(fd_,VIDIOC_QBUF,&buffer,eye_,"QBUF");
    }
    void close() noexcept {
        if(streaming_) { auto stream_type=type; (void)::ioctl(fd_,VIDIOC_STREAMOFF,&stream_type); }
        streaming_=false;
        for(const auto& map:maps_) (void)::munmap(map.address,map.length);
        maps_.clear();
        if(fd_>=0) { (void)::close(fd_); fd_=-1; }
    }
    int eye_{}, fd_{-1}, stride_{};
    bool streaming_{};
    std::vector<Mapping> maps_;
};
}
struct RawOpticalCapture::Impl {
    Impl(const CaptureOptions& options,Observer& observer)
        : observer(observer),first(options.first_device,0),second(options.second_device,1) {}
    Observer& observer;
    Device first,second;
};
RawOpticalCapture::RawOpticalCapture(std::unique_ptr<Impl> impl) noexcept : impl_(std::move(impl)) {}
RawOpticalCapture::~RawOpticalCapture()=default;
RawOpticalCapture::RawOpticalCapture(RawOpticalCapture&&) noexcept=default;
RawOpticalCapture& RawOpticalCapture::operator=(RawOpticalCapture&&) noexcept=default;
std::variant<RawOpticalCapture,Error> RawOpticalCapture::open(const CaptureOptions& options,Observer& observer) noexcept {
    try { return RawOpticalCapture(std::make_unique<Impl>(options,observer)); }
    catch(const Fault& fault) { return fault.error; }
    catch(...) { return Error{ErrorCode::system,ENOMEM,-1,"allocate capture"}; }
}
std::optional<Error> RawOpticalCapture::run() noexcept {
    if(!impl_) return Error{ErrorCode::invalid_configuration,EINVAL,-1,"moved capture"};
    try {
        while(true) {
            pollfd descriptors[]={{impl_->first.fd(),POLLIN,0},{impl_->second.fd(),POLLIN,0}};
            const int ready=::poll(descriptors,2,3000);
            if(ready<0 && errno==EINTR) continue;
            check(ready,-1,"poll");
            if(!ready) return Error{ErrorCode::timeout,ETIMEDOUT,-1,"camera frames"};
            for(int eye=0;eye<2;++eye) {
                if(descriptors[eye].revents&(POLLERR|POLLHUP|POLLNVAL))
                    return Error{ErrorCode::system,EIO,eye,"camera poll"};
                // Drain independently; no pairing window and no timestamp rewrite.
                if(descriptors[eye].revents&POLLIN)
                    if(!(eye?impl_->second:impl_->first).dequeue(impl_->observer)) return {};
            }
        }
    } catch(const Fault& fault) { return fault.error; }
    catch(...) { return Error{ErrorCode::system,EIO,-1,"capture"}; }
}
}
