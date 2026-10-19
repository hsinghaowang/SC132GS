#define CL_TARGET_OPENCL_VERSION 120
#include <CL/cl.h>
#include "GpuStereoDepth.hpp"
#include "stereo_kernels.hpp"
#include "Mono8RectificationKernel.hpp"
#include <algorithm>
#include <string>
#include <iostream>
#include <utility>

namespace stereo_rtsp::detail::depth_gpu {
namespace {
void check(cl_int code,Stage stage){if(code)throw Error{stage,code};}
template<class T,cl_int(*Release)(T)> class Owned {
public:
    explicit Owned(T h=nullptr):handle_(h){}
    ~Owned(){if(handle_)Release(handle_);}
    Owned(const Owned&)=delete;Owned& operator=(const Owned&)=delete;
    Owned(Owned&& rhs)noexcept:handle_(std::exchange(rhs.handle_,nullptr)){}
    Owned& operator=(Owned&& rhs)noexcept{if(this!=&rhs){if(handle_)Release(handle_);handle_=std::exchange(rhs.handle_,nullptr);}return *this;}
    T get()const{return handle_;}
private:T handle_;
};
using Context=Owned<cl_context,clReleaseContext>;
using Queue=Owned<cl_command_queue,clReleaseCommandQueue>;
using Program=Owned<cl_program,clReleaseProgram>;
using Kernel=Owned<cl_kernel,clReleaseKernel>;
using Buffer=Owned<cl_mem,clReleaseMemObject>;
using Event=Owned<cl_event,clReleaseEvent>;
struct QueueDrain {
    cl_command_queue queue;bool complete{};
    ~QueueDrain(){if(!complete)clFinish(queue);}
};
constexpr size_t N=544*640,Native=1088*1280,Disparities=96;
const char* native_kernels=R"CL(
uint native_sample(__global const ushort* eye,int x,int y){if(x<0||x>=1088||y<0||y>=1280)return 0;return eye[y*1088+x];}
__kernel void rectify_native(__global const ushort* cam0,__global const ushort* cam1,
 __global const int2* lm,__global const int2* rm,__global matching_pixel* left,__global matching_pixel* right){
 int g=get_global_id(0);if(g>=2*544*640)return;
 int eye=g/(544*640),i=g%(544*640);int2 p=eye?rm[i]:lm[i];
 int x=p.x>>5,y=p.y>>5,fx=p.x&31,fy=p.y&31;
 __global const ushort* src=eye?cam0:cam1;
 uint a=native_sample(src,x,y),b=native_sample(src,x+1,y),c=native_sample(src,x,y+1),d=native_sample(src,x+1,y+1);
 // Preserve the original fused 8-bit rounding; the 10-bit path rounds the
 // same bilinear sample to mono10 without reducing its intensity precision.
 uint sum=a*(32-fx)*(32-fy)+b*fx*(32-fy)+c*(32-fx)*fy+d*fx*fy;
#if MATCHING_BITS == 10
 matching_pixel v=(ushort)min((sum+512)>>10,1023u);
#else
 matching_pixel v=convert_uchar_sat((sum+2048)>>12);
#endif
 if(eye)right[i]=v;else left[i]=v;
}
__kernel void depth_metric(__global const short* left,__global const short* right,
 __global const uchar* lm,__global const uchar* rm,__global float* out,float fb){
 int i=get_global_id(0);if(i>=544*640)return;int x=i%544,y=i/544,d=left[i],xr=x-d;
 float z=NAN;
 if(lm[i]&&d>0&&xr>=0&&xr<544&&rm[y*544+xr]&&right[y*544+xr]>0&&abs(d-right[y*544+xr])<=1)z=fb/d;
 out[i]=z;
}
__kernel void rectify_gray(__global const ushort* cam0,__global const ushort* cam1,
 __global const int2* lm,__global const int2* rm,__global uchar* out){
 int g=get_global_id(0);if(g>=2*1088*1280)return;
 int eye=g/(1088*1280),i=g%(1088*1280);int2 p=eye?rm[i]:lm[i];
 int x=p.x>>5,y=p.y>>5,fx=p.x&31,fy=p.y&31;
 __global const ushort* src=eye?cam0:cam1;
 uint a=native_sample(src,x,y),b=native_sample(src,x+1,y),c=native_sample(src,x,y+1),d=native_sample(src,x+1,y+1);
 out[(i/1088)*2176+eye*1088+i%1088]=convert_uchar_sat((a*(32-fx)*(32-fy)+b*fx*(32-fy)+c*(32-fx)*fy+d*fx*fy+2048)>>12);
 // Neutral chroma; each work item owns one byte in the UV plane.
 if(g<1088*1280)out[2*1088*1280+g]=128;
}
__kernel void color_depth(__global const float* z,__global const uchar4* palette,__global uchar* out){
 int x=get_global_id(0)*2,y=get_global_id(1)*2;if(x>=544||y>=640)return;
 uint u=0,v=0;
 for(int dy=0;dy<2;++dy)for(int dx=0;dx<2;++dx){
  int i=(y+dy)*544+x+dx;float d=z[i];uchar4 c=(uchar4)(16,128,128,0);
  if(isfinite(d)&&d>0)c=palette[convert_int_sat_rte(clamp((d-0.2f)/2.8f,0.0f,1.0f)*255.0f)];
  out[i]=c.x;u+=c.y;v+=c.z;
 }
 int uv=544*640+(y/2)*544+x;out[uv]=(u+2)/4;out[uv+1]=(v+2)/4;
}
)CL";
}
struct GpuStereoDepth::Impl {
    Context context;Queue queue;Program program;
    Buffer raw0,raw1,ml,mr,vl,vr,left,right,cl,cr,cost,dl,dr,depth,fml,fmr,palette,gray,color;
    Kernel rectify,rectify8,census,cost_kernel,winner,metric,full_rectify,full_rectify8,colorize;
    DepthFrame reusable;
    bool emit_gray,ten_bits;
    explicit Impl(const Calibration& c):emit_gray(c.emit_gray),ten_bits(c.matching_precision==MatchingPrecision::ten_bits){
        if(c.matching_precision!=MatchingPrecision::eight_bits && !ten_bits)throw Error{Stage::geometry};
        if(c.left_map.size()!=N*2||c.right_map.size()!=N*2||c.left_valid.size()!=N||c.right_valid.size()!=N||(emit_gray&&(c.full_left_map.size()!=Native*2||c.full_right_map.size()!=Native*2))||c.yuv_palette.size()!=1024||c.focal_times_baseline_m_px<=0)
            throw Error{Stage::geometry};
        cl_platform_id platform{};cl_device_id device{};cl_int e{};
        check(clGetPlatformIDs(1,&platform,nullptr),Stage::initialization);
        check(clGetDeviceIDs(platform,CL_DEVICE_TYPE_GPU,1,&device,nullptr),Stage::initialization);
        context=Context(clCreateContext(nullptr,1,&device,nullptr,nullptr,&e));check(e,Stage::initialization);
        queue=Queue(clCreateCommandQueue(context.get(),device,CL_QUEUE_PROFILING_ENABLE,&e));check(e,Stage::initialization);
        const char* sources[]={stereo_kernels,native_kernels,mono8_rectification_kernels};
        program=Program(clCreateProgramWithSource(context.get(),3,sources,nullptr,&e));check(e,Stage::initialization);
        const char* options=ten_bits?"-cl-std=CL2.0 -DPACKED=1 -DREUSE=1 -DMATCHING_BITS=10":"-cl-std=CL2.0 -DPACKED=1 -DREUSE=1 -DMATCHING_BITS=8";
        e=clBuildProgram(program.get(),1,&device,options,nullptr,nullptr);
        if(e){size_t n{};clGetProgramBuildInfo(program.get(),device,CL_PROGRAM_BUILD_LOG,0,nullptr,&n);std::string log(n,' ');clGetProgramBuildInfo(program.get(),device,CL_PROGRAM_BUILD_LOG,n,log.data(),nullptr);std::cerr<<log;check(e,Stage::initialization);}
        auto buf=[&](size_t size){Buffer b(clCreateBuffer(context.get(),CL_MEM_READ_WRITE,size,nullptr,&e));check(e,Stage::initialization);return b;};
        raw0=buf(Native*2);raw1=buf(Native*2);ml=buf(N*8);mr=buf(N*8);vl=buf(N);vr=buf(N);
        left=buf(N*(ten_bits?2:1));right=buf(N*(ten_bits?2:1));cl=buf(N*4);cr=buf(N*4);cost=buf(N*Disparities);dl=buf(N*2);dr=buf(N*2);depth=buf(N*4);
        if(emit_gray){fml=buf(Native*8);fmr=buf(Native*8);gray=buf(Native*3);}
        palette=buf(1024);color=buf(N*3/2);
        auto kern=[&](const char* name){Kernel k(clCreateKernel(program.get(),name,&e));check(e,Stage::initialization);return k;};
        rectify=kern("rectify_native");census=kern("census");cost_kernel=kern("ring_cost");winner=kern("packed_winner");metric=kern("depth_metric");
        if(!ten_bits)rectify8=kern("rectify_native8");
        if(emit_gray)full_rectify=kern("rectify_gray");colorize=kern("color_depth");
        if(emit_gray&&!ten_bits)full_rectify8=kern("rectify_gray8");
        upload(ml,c.left_map.data(),N*8,true);upload(mr,c.right_map.data(),N*8,true);
        upload(vl,c.left_valid.data(),N,true);upload(vr,c.right_valid.data(),N,true);
        if(emit_gray){upload(fml,c.full_left_map.data(),Native*8,true);upload(fmr,c.full_right_map.data(),Native*8,true);}upload(palette,c.yuv_palette.data(),1024,true);
        arg(rectify,0,raw0);arg(rectify,1,raw1);arg(rectify,2,ml);arg(rectify,3,mr);arg(rectify,4,left);arg(rectify,5,right);
        if(!ten_bits){arg(rectify8,0,raw0);arg(rectify8,1,raw1);arg(rectify8,2,ml);arg(rectify8,3,mr);arg(rectify8,4,left);arg(rectify8,5,right);}
        arg(metric,0,dl);arg(metric,1,dr);arg(metric,2,vl);arg(metric,3,vr);arg(metric,4,depth);
        check(clSetKernelArg(metric.get(),5,sizeof(float),&c.focal_times_baseline_m_px),Stage::initialization);
        if(emit_gray){arg(full_rectify,0,raw0);arg(full_rectify,1,raw1);arg(full_rectify,2,fml);arg(full_rectify,3,fmr);arg(full_rectify,4,gray);}
        if(emit_gray&&!ten_bits){arg(full_rectify8,0,raw0);arg(full_rectify8,1,raw1);arg(full_rectify8,2,fml);arg(full_rectify8,3,fmr);arg(full_rectify8,4,gray);}
        arg(colorize,0,depth);arg(colorize,1,palette);arg(colorize,2,color);
    }
    void arg(const Kernel& k,int i,const Buffer& b){auto h=b.get();check(clSetKernelArg(k.get(),i,sizeof(h),&h),Stage::kernel);}
    void direction(const Kernel& k,int i,int value){check(clSetKernelArg(k.get(),i,sizeof(value),&value),Stage::kernel);}
    void upload(const Buffer& b,const void* p,size_t n,bool blocking=false){check(clEnqueueWriteBuffer(queue.get(),b.get(),blocking?CL_TRUE:CL_FALSE,0,n,p,0,nullptr,nullptr),Stage::upload);}
    DepthFrame process(StereoView view,Preview preview){
        if(view.pixels_per_eye!=Native||!view.cam0_right||!view.cam1_left)throw Error{Stage::geometry};
        return process_pixels(view.cam0_right,view.cam1_left,Native*2,rectify,full_rectify,preview);
    }
    DepthFrame process8(StereoView8 view,Preview preview){
        if(ten_bits||view.pixels_per_eye!=Native||!view.cam0_right||!view.cam1_left)throw Error{Stage::geometry};
        return process_pixels(view.cam0_right,view.cam1_left,Native,rectify8,full_rectify8,preview);
    }
    DepthFrame process_pixels(const void* cam0,const void* cam1,std::size_t bytes,
        const Kernel& remap,const Kernel& gray_remap,Preview preview){
        // Drain queued transfers before borrowed input or owning output dies,
        // including errors after a nonblocking upload/read has been submitted.
        DepthFrame out=std::move(reusable);out.gpu_ms=out.rectify_ms=0;
        QueueDrain drain{queue.get()};
        upload(raw0,cam0,bytes);upload(raw1,cam1,bytes);
        std::vector<Event> events;
        auto launch=[&](const Kernel& k,int dims,const size_t* size,const size_t* local=nullptr){
            cl_event e{};check(clEnqueueNDRangeKernel(queue.get(),k.get(),dims,nullptr,size,local,0,nullptr,&e),Stage::kernel);events.emplace_back(e);
        };
        size_t both[]={2*N},image[]={544,640},volume[]={192,Disparities,8},volume_local[]={64,1,1},choose[]={192,640},choose_local[]={64,1},linear[]={N};
        launch(remap,1,both);
        arg(census,0,left);arg(census,1,cl);launch(census,2,image);
        arg(census,0,right);arg(census,1,cr);launch(census,2,image);
        arg(cost_kernel,0,cl);arg(cost_kernel,1,cr);arg(cost_kernel,2,cost);direction(cost_kernel,3,-1);launch(cost_kernel,3,volume,volume_local);
        for(int eye=0;eye<2;++eye){arg(winner,0,cost);arg(winner,1,eye?dr:dl);direction(winner,2,eye?1:-1);launch(winner,2,choose,choose_local);}
        launch(metric,1,linear);
        size_t full[]={2*Native},tiles[]={272,320};if(emit_gray)launch(gray_remap,1,full);launch(colorize,2,tiles);
        out.meters.resize(N);
        check(clEnqueueReadBuffer(queue.get(),depth.get(),CL_FALSE,0,N*4,out.meters.data(),0,nullptr,nullptr),Stage::download);
        if(emit_gray){out.gray_nv12.resize(Native*3);check(clEnqueueReadBuffer(queue.get(),gray.get(),CL_FALSE,0,Native*3,out.gray_nv12.data(),0,nullptr,nullptr),Stage::download);}out.depth_nv12.resize(N*3/2);
        check(clEnqueueReadBuffer(queue.get(),color.get(),CL_FALSE,0,N*3/2,out.depth_nv12.data(),0,nullptr,nullptr),Stage::download);
        if(preview==Preview::left_luma){
            out.left_luma.resize(N);
            if(ten_bits){
                // The optional display preview stays 8-bit; matching is done.
                std::vector<std::uint16_t> mono10(N);
                check(clEnqueueReadBuffer(queue.get(),left.get(),CL_TRUE,0,N*2,mono10.data(),0,nullptr,nullptr),Stage::download);
                for(size_t i=0;i<N;++i)out.left_luma[i]=static_cast<std::uint8_t>(std::min(255u,(unsigned(mono10[i])+2)>>2));
            }else check(clEnqueueReadBuffer(queue.get(),left.get(),CL_FALSE,0,N,out.left_luma.data(),0,nullptr,nullptr),Stage::download);
        }
        check(clFinish(queue.get()),Stage::download);
        drain.complete=true;
        for(size_t i=0;i<events.size();++i){cl_ulong a{},b{};
            check(clGetEventProfilingInfo(events[i].get(),CL_PROFILING_COMMAND_START,sizeof(a),&a,nullptr),Stage::download);
            check(clGetEventProfilingInfo(events[i].get(),CL_PROFILING_COMMAND_END,sizeof(b),&b,nullptr),Stage::download);
            out.gpu_ms+=(b-a)*1e-6;if(!i)out.rectify_ms=(b-a)*1e-6;
        }
        return out;
    }
};
GpuStereoDepth::GpuStereoDepth(std::unique_ptr<Impl> impl)noexcept:impl_(std::move(impl)){}
GpuStereoDepth::~GpuStereoDepth()=default;
GpuStereoDepth::GpuStereoDepth(GpuStereoDepth&&)noexcept=default;
GpuStereoDepth& GpuStereoDepth::operator=(GpuStereoDepth&&)noexcept=default;
Result<GpuStereoDepth> GpuStereoDepth::open(const Calibration& c){try{return GpuStereoDepth(std::make_unique<Impl>(c));}catch(const Error& e){return e;}catch(...){return Error{Stage::initialization,-1};}}
Result<DepthFrame> GpuStereoDepth::process(StereoView v,Preview p){try{return impl_->process(v,p);}catch(const Error& e){return e;}catch(...){return Error{Stage::kernel,-1};}}
Result<DepthFrame> GpuStereoDepth::process8(StereoView8 v,Preview p){try{return impl_->process8(v,p);}catch(const Error& e){return e;}catch(...){return Error{Stage::kernel,-1};}}
void GpuStereoDepth::recycle(DepthFrame&& f){impl_->reusable=std::move(f);}
}
