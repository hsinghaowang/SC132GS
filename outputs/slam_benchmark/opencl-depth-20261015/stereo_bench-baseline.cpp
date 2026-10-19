#define CL_TARGET_OPENCL_VERSION 120
#include <CL/cl.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {
struct Error { cl_int code; const char* operation; };
void check(cl_int code, const char* operation) { if (code != CL_SUCCESS) throw Error{code, operation}; }
template<class T, cl_int (*Release)(T)> class Owned {
public:
    explicit Owned(T value = nullptr) : value_(value) {}
    ~Owned() { if (value_) Release(value_); }
    Owned(const Owned&) = delete;
    Owned& operator=(const Owned&) = delete;
    Owned(Owned&& other) noexcept : value_(std::exchange(other.value_, nullptr)) {}
    Owned& operator=(Owned&& other) noexcept {
        if (this != &other) { if (value_) Release(value_); value_ = std::exchange(other.value_, nullptr); }
        return *this;
    }
    T get() const { return value_; }
private:
    T value_;
};
using Context = Owned<cl_context, clReleaseContext>;
using Queue = Owned<cl_command_queue, clReleaseCommandQueue>;
using Program = Owned<cl_program, clReleaseProgram>;
using Kernel = Owned<cl_kernel, clReleaseKernel>;
using Buffer = Owned<cl_mem, clReleaseMemObject>;
using Event = Owned<cl_event, clReleaseEvent>;
constexpr int W=544, H=640, D=128, N=W*H;
const char* source = R"CLC(
#define W 544
#define H 640
#define D 128
__kernel void census(__global const uchar* input, __global uint* output) {
 int x=get_global_id(0),y=get_global_id(1); if(x>=W||y>=H)return;
 uint value=0; uchar center=input[y*W+x];
 for(int j=-2;j<=2;++j)for(int i=-2;i<=2;++i) {
  if(i==0&&j==0)continue;
  value=(value<<1)|(uint)(input[clamp(y+j,0,H-1)*W+clamp(x+i,0,W-1)]<center);
 }
 output[y*W+x]=value;
}
// Parallel over image positions AND disparity hypotheses; horizontal box cost.
__kernel void horizontal(__global const uint* a,__global const uint* b,
                         __global ushort* cost,int direction) {
 int d=get_global_id(0),x=get_global_id(1),y=get_global_id(2);
 if(d>=D||x>=W||y>=H)return;
 int target=x+direction*d; uint value=65535;
 if(x>=4&&x<W-4&&target>=4&&target<W-4&&y>=4&&y<H-4) {
  value=0;
  for(int i=-2;i<=2;++i)value+=popcount(a[y*W+x+i]^b[y*W+target+i]);
 }
 cost[(y*W+x)*D+d]=(ushort)value;
}
// Vertical box aggregation + winner/uniqueness. Census BM, NOT SGM/SGBM.
__kernel void winner(__global const ushort* cost,__global short* output,int direction) {
 int x=get_global_id(0),y=get_global_id(1);if(x>=W||y>=H)return;
 int idx=y*W+x;output[idx]=-1;
 if(y<6||y>=H-6||x<4||x>=W-4)return;
 uint best=0xffffffffu;int bestd=-1;
 for(int d=0;d<D;++d) {
  int target=x+direction*d;if(target<4||target>=W-4)continue;
  uint s=0;for(int j=-2;j<=2;++j)s+=cost[((y+j)*W+x)*D+d];
  if(s<best){best=s;bestd=d;}
 }
 if(bestd<=0||bestd>=D-1)return;
 for(int d=0;d<D;++d) {
  if(abs(d-bestd)<=1)continue;
  int target=x+direction*d;if(target<4||target>=W-4)continue;
  uint s=0;for(int j=-2;j<=2;++j)s+=cost[((y+j)*W+x)*D+d];
  if(s*90u<=best*100u)return;
 }
 output[idx]=(short)bestd;
}
__kernel void consistency(__global const short* left,__global const short* right,
                          __global float* disparity) {
 int idx=get_global_id(0);if(idx>=W*H)return;
 int x=idx%W,y=idx/W,d=left[idx],xr=x-d;
 disparity[idx]=NAN;
 if(d>0&&xr>=0&&xr<W&&right[y*W+xr]>0&&abs(d-right[y*W+xr])<=1)
  disparity[idx]=(float)d;
}
)CLC";

std::vector<unsigned char> read(const char* path) {
    std::ifstream file(path, std::ios::binary);
    std::vector<unsigned char> result(N);
    if (!file.read(reinterpret_cast<char*>(result.data()), N)) throw std::runtime_error("Invalid input size");
    return result;
}
uint32_t census_cpu(const std::vector<unsigned char>& image,int x,int y) {
    uint32_t v=0;auto center=image[y*W+x];
    for(int j=-2;j<=2;++j)for(int i=-2;i<=2;++i)if(i||j)
        v=(v<<1)|(image[std::clamp(y+j,0,H-1)*W+std::clamp(x+i,0,W-1)]<center);
    return v;
}
}

int main() {
try {
    auto left=read("left.u8"),right=read("right.u8");
    cl_platform_id platform{};cl_device_id device{};
    check(clGetPlatformIDs(1,&platform,nullptr),"platform");
    check(clGetDeviceIDs(platform,CL_DEVICE_TYPE_GPU,1,&device,nullptr),"GPU device");
    char name[256]{};check(clGetDeviceInfo(device,CL_DEVICE_NAME,sizeof(name),name,nullptr),"device name");
    std::cout<<"device="<<name<<'\n';
    cl_int error{};
    Context context(clCreateContext(nullptr,1,&device,nullptr,nullptr,&error));check(error,"context");
    Queue queue(clCreateCommandQueue(context.get(),device,CL_QUEUE_PROFILING_ENABLE,&error));check(error,"queue");
    Program program(clCreateProgramWithSource(context.get(),1,&source,nullptr,&error));check(error,"program");
    error=clBuildProgram(program.get(),1,&device,"-cl-std=CL1.2",nullptr,nullptr);
    if(error) {
        size_t count{};clGetProgramBuildInfo(program.get(),device,CL_PROGRAM_BUILD_LOG,0,nullptr,&count);
        std::vector<char> log(count);clGetProgramBuildInfo(program.get(),device,CL_PROGRAM_BUILD_LOG,count,log.data(),nullptr);
        std::cerr<<log.data()<<'\n';check(error,"build");
    }
    auto buffer=[&](size_t bytes) { Buffer b(clCreateBuffer(context.get(),CL_MEM_READ_WRITE,bytes,nullptr,&error));check(error,"buffer");return b; };
    auto kernel=[&](const char* key) { Kernel k(clCreateKernel(program.get(),key,&error));check(error,key);return k; };
    auto il=buffer(N),ir=buffer(N),cl=buffer(N*4),cr=buffer(N*4),cost=buffer(size_t(N)*D*2),
         dl=buffer(N*2),dr=buffer(N*2),out=buffer(N*4);
    auto census=kernel("census"),horizontal=kernel("horizontal"),winner=kernel("winner"),consistency=kernel("consistency");
    auto arg=[&](const Kernel& k,int index,const Buffer& b) { auto handle=b.get();check(clSetKernelArg(k.get(),index,sizeof(handle),&handle),"buffer arg"); };
    auto dir=[&](const Kernel& k,int index,int direction) { check(clSetKernelArg(k.get(),index,sizeof(direction),&direction),"direction"); };
    size_t image_size[]={W,H},volume_size[]={D,W,H},linear_size[]={N};
    std::vector<float> disparity(N);std::vector<short> gpu_left(N);std::vector<uint32_t> gpu_census(N);
    std::vector<double> wall,kernel_times;
    for(int run=0;run<35;++run) {
        auto begin=std::chrono::steady_clock::now();std::vector<Event> events;
        auto launch=[&](const Kernel& k,int dims,const size_t* size) {
            cl_event event{};check(clEnqueueNDRangeKernel(queue.get(),k.get(),dims,nullptr,size,nullptr,0,nullptr,&event),"enqueue");
            events.emplace_back(event);
        };
        check(clEnqueueWriteBuffer(queue.get(),il.get(),CL_FALSE,0,N,left.data(),0,nullptr,nullptr),"upload left");
        check(clEnqueueWriteBuffer(queue.get(),ir.get(),CL_FALSE,0,N,right.data(),0,nullptr,nullptr),"upload right");
        arg(census,0,il);arg(census,1,cl);launch(census,2,image_size);
        arg(census,0,ir);arg(census,1,cr);launch(census,2,image_size);
        for(int side=0;side<2;++side) {
            arg(horizontal,0,side?cr:cl);arg(horizontal,1,side?cl:cr);arg(horizontal,2,cost);dir(horizontal,3,side?1:-1);
            launch(horizontal,3,volume_size);
            arg(winner,0,cost);arg(winner,1,side?dr:dl);dir(winner,2,side?1:-1);launch(winner,2,image_size);
        }
        arg(consistency,0,dl);arg(consistency,1,dr);arg(consistency,2,out);launch(consistency,1,linear_size);
        check(clEnqueueReadBuffer(queue.get(),out.get(),CL_TRUE,0,N*4,disparity.data(),0,nullptr,nullptr),"download");
        double elapsed=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count(),kernel_ms=0;
        for(auto& event:events) {
            cl_ulong start{},end{};check(clGetEventProfilingInfo(event.get(),CL_PROFILING_COMMAND_START,sizeof(start),&start,nullptr),"profile start");
            check(clGetEventProfilingInfo(event.get(),CL_PROFILING_COMMAND_END,sizeof(end),&end,nullptr),"profile end");kernel_ms+=(end-start)*1e-6;
        }
        if(run>=5){wall.push_back(elapsed);kernel_times.push_back(kernel_ms);}
    }
    check(clEnqueueReadBuffer(queue.get(),cl.get(),CL_TRUE,0,N*4,gpu_census.data(),0,nullptr,nullptr),"read census");
    check(clEnqueueReadBuffer(queue.get(),dl.get(),CL_TRUE,0,N*2,gpu_left.data(),0,nullptr,nullptr),"read winner");
    for(int y=0;y<H;++y)for(int x=0;x<W;++x)
        if(gpu_census[y*W+x]!=census_cpu(left,x,y))throw std::runtime_error("CPU/GPU census mismatch");
    // Independent scalar reference across deterministic spatial samples, all hypotheses.
    int samples=0;
    for(int y=10;y<H-10;y+=47)for(int x=10;x<W-10;x+=43) {
        std::vector<uint32_t> costs(D,UINT32_MAX);uint32_t best=UINT32_MAX;int bestd=-1;
        for(int d=0;d<D;++d)if(x-d>=4&&x-d<W-4) {
            uint32_t s=0;for(int j=-2;j<=2;++j)for(int i=-2;i<=2;++i)
                s+=__builtin_popcount(census_cpu(left,x+i,y+j)^census_cpu(right,x-d+i,y+j));
            costs[d]=s;if(s<best){best=s;bestd=d;}
        }
        bool unique=bestd>0&&bestd<D-1;
        for(int d=0;d<D;++d)if(costs[d]!=UINT32_MAX&&std::abs(d-bestd)>1&&costs[d]*90u<=best*100u)unique=false;
        if(gpu_left[y*W+x]!=(unique?bestd:-1))throw std::runtime_error("CPU/GPU disparity mismatch");
        ++samples;
    }
    std::ofstream file("disparity.f32",std::ios::binary);file.write(reinterpret_cast<const char*>(disparity.data()),N*4);
    if(!file)throw std::runtime_error("Output write failed");
    std::sort(wall.begin(),wall.end());std::sort(kernel_times.begin(),kernel_times.end());
    auto valid=std::count_if(disparity.begin(),disparity.end(),[](float x){return std::isfinite(x)&&x>0;});
    std::cout<<"measured_iterations="<<wall.size()<<"\nwall_median_ms="<<wall[wall.size()/2]
             <<"\nwall_p95_ms="<<wall[size_t((wall.size()-1)*.95)]<<"\nkernel_median_ms="<<kernel_times[kernel_times.size()/2]
             <<"\nvalid_fraction="<<double(valid)/N<<"\ncensus_checked_pixels="<<N
             <<"\ndisparity_checked_samples="<<samples<<"\n";
} catch(const Error& e) { std::cerr<<"OpenCL error="<<e.code<<" operation="<<e.operation<<'\n';return 1;
} catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
