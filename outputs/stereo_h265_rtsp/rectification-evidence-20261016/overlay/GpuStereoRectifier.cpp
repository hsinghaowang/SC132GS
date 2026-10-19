#define CL_TARGET_OPENCL_VERSION 120
#include "GpuStereoRectifier.hpp"
#include <CL/cl.h>
#include <array>
#include <cstring>
#include <fstream>
#include <iostream>
#include <utility>

namespace stereo_rtsp::detail {
namespace {
void check(cl_int e,RectificationCode stage){if(e)throw RectificationError{stage,e};}
template<class T,cl_int(*Release)(T)>struct Owned {
    T value{};
    Owned()=default;explicit Owned(T h):value(h){}
    ~Owned(){if(value)Release(value);}
    Owned(const Owned&)=delete;Owned& operator=(const Owned&)=delete;
    Owned(Owned&& r)noexcept:value(std::exchange(r.value,nullptr)){}
    Owned& operator=(Owned&& r)noexcept{if(this!=&r){if(value)Release(value);value=std::exchange(r.value,nullptr);}return *this;}
};
using Context=Owned<cl_context,clReleaseContext>;
using Queue=Owned<cl_command_queue,clReleaseCommandQueue>;
using Program=Owned<cl_program,clReleaseProgram>;
using Kernel=Owned<cl_kernel,clReleaseKernel>;
using Buffer=Owned<cl_mem,clReleaseMemObject>;
using Event=Owned<cl_event,clReleaseEvent>;
struct Drain {cl_command_queue queue;~Drain(){clFinish(queue);}};
std::uint32_t u32(const unsigned char* p){return std::uint32_t(p[0])|(std::uint32_t(p[1])<<8)|(std::uint32_t(p[2])<<16)|(std::uint32_t(p[3])<<24);}
constexpr std::size_t pixels=1088*1280;
const char* source=R"CL(
uint sample10(__global const ushort* input,int x,int y){
 if(x<0||x>=1088||y<0||y>=1280)return 0;return input[y*1088+x];
}
__kernel void rectify10(__global const ushort* cam0,__global const ushort* cam1,
 __global const int2* cam1_map,__global const int2* cam0_map,__global ushort* out){
 int g=get_global_id(0);if(g>=2*1088*1280)return;
 int eye=g/(1088*1280),i=g%(1088*1280);int2 p=eye?cam0_map[i]:cam1_map[i];
 __global const ushort* input=eye?cam0:cam1;
 int x=p.x>>5,y=p.y>>5,fx=p.x&31,fy=p.y&31;
 uint a=sample10(input,x,y),b=sample10(input,x+1,y),c=sample10(input,x,y+1),d=sample10(input,x+1,y+1);
 uint v=(a*(32-fx)*(32-fy)+b*fx*(32-fy)+c*(32-fx)*fy+d*fx*fy+512)>>10;
 out[(i/1088)*2176+eye*1088+i%1088]=(ushort)min(v,1023u);
}
)CL";
}
struct GpuStereoRectifier::Impl {
    Context context;Queue queue;Program program;Kernel kernel;
    Buffer cam0,cam1,map1,map0,output;
    explicit Impl(const std::string& path){
        std::ifstream file(path,std::ios::binary);std::array<unsigned char,76> header{};
        if(!file.read(reinterpret_cast<char*>(header.data()),header.size())||std::memcmp(header.data(),"S132RMAP",8))throw RectificationError{RectificationCode::map_file};
        const std::array<std::uint32_t,9> expected{1,1088,1280,1088,1280,1,0,32,10};
        for(std::size_t i=0;i<expected.size();++i)if(u32(header.data()+8+i*4)!=expected[i])throw RectificationError{RectificationCode::geometry};
        std::vector<std::int32_t> maps(pixels*4);
        if(!file.read(reinterpret_cast<char*>(maps.data()),maps.size()*sizeof(maps[0]))||file.peek()!=std::char_traits<char>::eof())throw RectificationError{RectificationCode::map_file};
        for(auto coordinate:maps)if(coordinate < -32768*32 || coordinate > 32767*32+31)throw RectificationError{RectificationCode::geometry};
        cl_platform_id platform{};cl_device_id device{};cl_int e{};
        check(clGetPlatformIDs(1,&platform,nullptr),RectificationCode::initialization);
        check(clGetDeviceIDs(platform,CL_DEVICE_TYPE_GPU,1,&device,nullptr),RectificationCode::initialization);
        context=Context(clCreateContext(nullptr,1,&device,nullptr,nullptr,&e));check(e,RectificationCode::initialization);
        queue=Queue(clCreateCommandQueue(context.value,device,CL_QUEUE_PROFILING_ENABLE,&e));check(e,RectificationCode::initialization);
        program=Program(clCreateProgramWithSource(context.value,1,&source,nullptr,&e));check(e,RectificationCode::initialization);
        check(clBuildProgram(program.value,1,&device,"-cl-std=CL1.2",nullptr,nullptr),RectificationCode::initialization);
        kernel=Kernel(clCreateKernel(program.value,"rectify10",&e));check(e,RectificationCode::initialization);
        auto buffer=[&](std::size_t bytes){auto h=clCreateBuffer(context.value,CL_MEM_READ_WRITE,bytes,nullptr,&e);check(e,RectificationCode::initialization);return Buffer(h);};
        cam0=buffer(pixels*2);cam1=buffer(pixels*2);map1=buffer(pixels*8);map0=buffer(pixels*8);output=buffer(pixels*4);
        check(clEnqueueWriteBuffer(queue.value,map1.value,CL_TRUE,0,pixels*8,maps.data(),0,nullptr,nullptr),RectificationCode::initialization);
        check(clEnqueueWriteBuffer(queue.value,map0.value,CL_TRUE,0,pixels*8,maps.data()+pixels*2,0,nullptr,nullptr),RectificationCode::initialization);
        cl_mem arguments[]={cam0.value,cam1.value,map1.value,map0.value,output.value};
        for(cl_uint i=0;i<5;++i)check(clSetKernelArg(kernel.value,i,sizeof(cl_mem),&arguments[i]),RectificationCode::initialization);
        char name[256]{};clGetDeviceInfo(device,CL_DEVICE_NAME,sizeof(name),name,nullptr);
        std::cerr<<"gpu_rectification device="<<name<<" width=2176 height=1280 bits=10 order=cam1_cam0 map="<<path<<'\n';
    }
    RectificationTiming process(const std::uint16_t* a,const std::uint16_t* b,std::size_t count,std::vector<std::uint16_t>& out){
        if(!a||!b||count!=pixels)throw RectificationError{RectificationCode::geometry};
        out.resize(pixels*2);Drain drain{queue.value};
        check(clEnqueueWriteBuffer(queue.value,cam0.value,CL_FALSE,0,pixels*2,a,0,nullptr,nullptr),RectificationCode::upload);
        check(clEnqueueWriteBuffer(queue.value,cam1.value,CL_FALSE,0,pixels*2,b,0,nullptr,nullptr),RectificationCode::upload);
        std::size_t global=pixels*2;cl_event event{};
        check(clEnqueueNDRangeKernel(queue.value,kernel.value,1,nullptr,&global,nullptr,0,nullptr,&event),RectificationCode::kernel);Event owned(event);
        check(clEnqueueReadBuffer(queue.value,output.value,CL_TRUE,0,pixels*4,out.data(),0,nullptr,nullptr),RectificationCode::download);
        cl_ulong begin{},end{};
        check(clGetEventProfilingInfo(event,CL_PROFILING_COMMAND_START,sizeof(begin),&begin,nullptr),RectificationCode::download);
        check(clGetEventProfilingInfo(event,CL_PROFILING_COMMAND_END,sizeof(end),&end,nullptr),RectificationCode::download);
        return {end-begin};
    }
};
GpuStereoRectifier::GpuStereoRectifier(const std::string& p):impl_(std::make_unique<Impl>(p)){}
GpuStereoRectifier::~GpuStereoRectifier()=default;
GpuStereoRectifier::GpuStereoRectifier(GpuStereoRectifier&&)noexcept=default;
GpuStereoRectifier& GpuStereoRectifier::operator=(GpuStereoRectifier&&)noexcept=default;
std::variant<RectificationTiming,RectificationError> GpuStereoRectifier::process(const std::uint16_t* a,const std::uint16_t* b,std::size_t n,std::vector<std::uint16_t>& out){
    try{return impl_->process(a,b,n,out);}catch(const RectificationError& e){return e;}
}
}
