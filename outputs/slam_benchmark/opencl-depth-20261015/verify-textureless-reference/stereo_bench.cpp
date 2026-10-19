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
 int lane=get_local_id(0),idx=get_global_id(1),x=idx%W,y=idx/W;
 if(idx>=W*H)return;
 if(y<6||y>=H-6||x<4||x>=W-4){if(lane==0)output[idx]=-1;return;}
 // A 32-lane workgroup cooperates on one pixel. Adjacent lanes read
 // adjacent disparities, avoiding the old 128-element stride across lanes.
 __local uint sums[D];__local uint minima[32];__local int indices[32];
 uint best=0xffffffffu;int bestd=-1;
 for(int d=lane;d<D;d+=32) {
  int target=x+direction*d;uint s=0xffffffffu;
  if(target>=4&&target<W-4){s=0;for(int j=-2;j<=2;++j)s+=cost[((y+j)*W+x)*D+d];}
  sums[d]=s;
  if(s<best){best=s;bestd=d;}
 }
 minima[lane]=best;indices[lane]=bestd;barrier(CLK_LOCAL_MEM_FENCE);
 for(int stride=16;stride;stride>>=1){
  if(lane<stride&&(minima[lane+stride]<minima[lane]||
    (minima[lane+stride]==minima[lane]&&indices[lane+stride]>=0&&
     (indices[lane]<0||indices[lane+stride]<indices[lane])))){
   minima[lane]=minima[lane+stride];indices[lane]=indices[lane+stride];
  }
  barrier(CLK_LOCAL_MEM_FENCE);
 }
 best=minima[0];bestd=indices[0];
 uint second=0xffffffffu;
 for(int d=lane;d<D;d+=32)if(abs(d-bestd)>1)second=min(second,sums[d]);
 barrier(CLK_LOCAL_MEM_FENCE);
 minima[lane]=second;barrier(CLK_LOCAL_MEM_FENCE);
 for(int stride=16;stride;stride>>=1){if(lane<stride)minima[lane]=min(minima[lane],minima[lane+stride]);barrier(CLK_LOCAL_MEM_FENCE);}
 if(lane==0)output[idx]=(bestd>0&&bestd<D-1&&(minima[0]==0xffffffffu||minima[0]*90u>best*100u))?(short)bestd:(short)-1;
}
__kernel void consistency(__global const short* left,__global const short* right,
                          __global float* disparity) {
 int idx=get_global_id(0);if(idx>=W*H)return;
 int x=idx%W,y=idx/W,d=left[idx],xr=x-d;
 disparity[idx]=NAN;
 if(d>0&&xr>=0&&xr<W&&right[y*W+xr]>0&&abs(d-right[y*W+xr])<=1)
  disparity[idx]=(float)d;
}
#define TX 4
#define RW (D+TX+3)
// Cache the entire census search strip for four neighboring output pixels.
// Aggregate and select disparity locally: no global 85 MiB cost volume.
__kernel void tiled(__global const uint* a,__global const uint* b,
                    __global short* output,int direction) {
 int lane=get_local_id(0),pixel=get_local_id(1),flat=pixel*32+lane;
 int bx=get_group_id(1)*TX,x=bx+pixel,y=get_group_id(2);
 if(y<6||y>=H-6){if(lane==0)output[y*W+x]=-1;return;}
 __local uint lpatch[5*(TX+4)],rpatch[5*RW];
 __local uint sums[TX*D],mins[TX*32];__local int ids[TX*32];
 int rb=bx-2+(direction<0?-(D-1):0);
 for(int i=flat;i<5*(TX+4);i+=TX*32)
  lpatch[i]=a[(y-2+i/(TX+4))*W+clamp(bx-2+i%(TX+4),0,W-1)];
 for(int i=flat;i<5*RW;i+=TX*32)
  rpatch[i]=b[(y-2+i/RW)*W+clamp(rb+i%RW,0,W-1)];
 barrier(CLK_LOCAL_MEM_FENCE);
 uint best=0xffffffffu;int bestd=-1;
 for(int d=lane;d<D;d+=32) {
  int target=x+direction*d;uint s=0xffffffffu;
  if(x>=4&&x<W-4&&target>=4&&target<W-4) {
   s=0;
   for(int j=0;j<5;++j)for(int i=-2;i<=2;++i)
    s+=popcount(lpatch[j*(TX+4)+pixel+2+i]^rpatch[j*RW+target-rb+i]);
  }
  sums[pixel*D+d]=s;if(s<best){best=s;bestd=d;}
 }
 mins[flat]=best;ids[flat]=bestd;barrier(CLK_LOCAL_MEM_FENCE);
 for(int step=16;step;step>>=1) {
  if(lane<step&&(mins[flat+step]<mins[flat]||
     (mins[flat+step]==mins[flat]&&ids[flat+step]>=0&&(ids[flat]<0||ids[flat+step]<ids[flat])))) {
   mins[flat]=mins[flat+step];ids[flat]=ids[flat+step];
  }
  barrier(CLK_LOCAL_MEM_FENCE);
 }
 best=mins[pixel*32];bestd=ids[pixel*32];uint second=0xffffffffu;
 for(int d=lane;d<D;d+=32)if(abs(d-bestd)>1)second=min(second,sums[pixel*D+d]);
 barrier(CLK_LOCAL_MEM_FENCE);
 mins[flat]=second;barrier(CLK_LOCAL_MEM_FENCE);
 for(int step=16;step;step>>=1){if(lane<step)mins[flat]=min(mins[flat],mins[flat+step]);barrier(CLK_LOCAL_MEM_FENCE);}
 if(lane==0)output[y*W+x]=(bestd>0&&bestd<D-1&&
  (mins[pixel*32]==0xffffffffu||mins[pixel*32]*90u>best*100u))?(short)bestd:(short)-1;
}
__kernel void sliding_cost(__global const uint* a,__global const uint* b,
                            __global ushort* cost,int direction) {
 int d=get_global_id(0),x=get_global_id(1),target=x+direction*d;
 if(d>=D||x>=W)return;
 uint sum=0;
 for(int j=-2;j<=2;++j){int row=clamp(j,0,H-1)*W;sum+=popcount(a[row+x]^b[row+clamp(target,0,W-1)]);}
 for(int y=0;y<H;++y) {
  cost[(y*W+x)*D+d]=(x>=2&&x<W-2&&target>=2&&target<W-2&&y>=4&&y<H-4)?(ushort)sum:(ushort)65535;
  int next=clamp(y+3,0,H-1)*W,prev=clamp(y-2,0,H-1)*W;
  sum+=popcount(a[next+x]^b[next+clamp(target,0,W-1)]);
  sum-=popcount(a[prev+x]^b[prev+clamp(target,0,W-1)]);
 }
}
__kernel void subgroup_winner(__global const ushort* cost,__global short* output,int direction) {
 int lane=get_local_id(0),idx=get_global_id(1),x=idx%W,y=idx/W;
 if(idx>=W*H)return;
 if(get_sub_group_size()!=32){if(lane==0)output[idx]=-2;return;}
 if(y<6||y>=H-6||x<4||x>=W-4){if(lane==0)output[idx]=-1;return;}
 uint values[4],best=0xffffffffu;
 for(int k=0;k<4;++k) {
  int d=lane+k*32,target=x+direction*d;uint s=0xffffffffu;
  if(target>=4&&target<W-4) {s=0;for(int i=-2;i<=2;++i)s+=cost[(y*W+x+i)*D+d];}
  values[k]=s;if(s!=0xffffffffu)best=min(best,s*D+d);
 }
 uint winner=sub_group_reduce_min(best);int bestd=winner%D;uint bestcost=winner/D,second=0xffffffffu;
 for(int k=0;k<4;++k)if(abs(lane+k*32-bestd)>1)second=min(second,values[k]);
 second=sub_group_reduce_min(second);
 if(lane==0)output[idx]=(winner!=0xffffffffu&&bestd>0&&bestd<D-1&&
   (second==0xffffffffu||second*90u>bestcost*100u))?(short)bestd:(short)-1;
}
// Spatially contiguous lanes; disparity-major volume makes each image row
// contiguous for both rolling writes and winner reads across neighboring pixels.
#ifdef PACKED
typedef uchar spatial_value;
#define INVALID_COST 255
#else
typedef ushort spatial_value;
#define INVALID_COST 65535
#endif
__kernel void spatial_cost(__global const uint* a,__global const uint* b,
                            __global spatial_value* cost,int direction) {
 int x=get_global_id(0),d=get_global_id(1),target=x+direction*d;
 if(x>=W||d>=D)return;
 uint sum=0;
 for(int j=-2;j<=2;++j){int row=clamp(j,0,H-1)*W;sum+=popcount(a[row+x]^b[row+clamp(target,0,W-1)]);}
 for(int y=0;y<H;++y) {
  cost[(d*H+y)*W+x]=(x>=2&&x<W-2&&target>=2&&target<W-2&&y>=4&&y<H-4)?(spatial_value)sum:(spatial_value)INVALID_COST;
  int next=clamp(y+3,0,H-1)*W,prev=clamp(y-2,0,H-1)*W;
  sum+=popcount(a[next+x]^b[next+clamp(target,0,W-1)]);
  sum-=popcount(a[prev+x]^b[prev+clamp(target,0,W-1)]);
 }
}
__kernel void spatial_winner(__global const spatial_value* cost,__global short* output,int direction) {
 int x=get_global_id(0),y=get_global_id(1);if(x>=W||y>=H)return;
 int idx=y*W+x;output[idx]=-1;if(y<6||y>=H-6||x<4||x>=W-4)return;
 uint v0=0xffffffffu,v1=0xffffffffu,v2=0xffffffffu,v3=0xffffffffu;
 for(int d=0;d<D;++d){
  int target=x+direction*d;if(target<4||target>=W-4)continue;
  uint s=0;for(int i=-2;i<=2;++i)s+=cost[(d*H+y)*W+x+i];
  uint v=s*D+d;
  if(v<v3){if(v<v0){v3=v2;v2=v1;v1=v0;v0=v;}
   else if(v<v1){v3=v2;v2=v1;v1=v;}else if(v<v2){v3=v2;v2=v;}else v3=v;}
 }
 int bestd=v0%D;uint best=v0/D,second=0xffffffffu;
 // At most three disparity indices are excluded: bestd and its two neighbors.
 // Therefore the four lowest (cost,index) candidates suffice for exact uniqueness.
 if(v1!=0xffffffffu&&abs((int)(v1%D)-bestd)>1)second=min(second,v1/D);
 if(v2!=0xffffffffu&&abs((int)(v2%D)-bestd)>1)second=min(second,v2/D);
 if(v3!=0xffffffffu&&abs((int)(v3%D)-bestd)>1)second=min(second,v3/D);
 if(v0!=0xffffffffu&&bestd>0&&bestd<D-1&&(second==0xffffffffu||second*90u>best*100u))output[idx]=(short)bestd;
}
#ifdef PACKED
uint4 load_patch4(__global const uint* a,int row,int x) {
 if(x>=0&&x<=W-4)return vload4(0,a+row+x);
 return (uint4)(a[row+clamp(x,0,W-1)],a[row+clamp(x+1,0,W-1)],
                a[row+clamp(x+2,0,W-1)],a[row+clamp(x+3,0,W-1)]);
}
__kernel void vector_cost(__global const uint* a,__global const uint* b,
                           __global uchar* cost,int direction) {
 int x=get_global_id(0)*4,d=get_global_id(1),begin=get_global_id(2)*80;
 if(x>=W||d>=D||begin>=H)return;
 int target=x+direction*d;uint4 sum=(uint4)(0);
 for(int j=-2;j<=2;++j){int row=clamp(begin+j,0,H-1)*W;sum+=popcount(vload4(0,a+row+x)^load_patch4(b,row,target));}
 int4 xv=(int4)(x,x+1,x+2,x+3),tv=xv+direction*d;
 int4 supported=(xv>=2)&(xv<W-2)&(tv>=2)&(tv<W-2);
 for(int y=begin;y<min(begin+80,H);++y) {
  vstore4(convert_uchar4(select((uint4)(255),sum,convert_uint4(supported&(int4)(y>=4&&y<H-4?-1:0)))),0,cost+(d*H+y)*W+x);
  int next=clamp(y+3,0,H-1)*W,prev=clamp(y-2,0,H-1)*W;
  sum+=popcount(vload4(0,a+next+x)^load_patch4(b,next,target));
  sum-=popcount(vload4(0,a+prev+x)^load_patch4(b,prev,target));
 }
}
uint4 row_hamming4(__global const uint* a,__global const uint* b,int y,int x,int target) {
 int row=clamp(y,0,H-1)*W;
 return popcount(vload4(0,a+row+x)^load_patch4(b,row,target));
}
__kernel void ring_cost(__global const uint* a,__global const uint* b,
                         __global uchar* cost,int direction) {
 int x=get_global_id(0)*4,d=get_global_id(1),begin=get_global_id(2)*80;
 if(x>=W||d>=D||begin>=H)return;
 int target=x+direction*d;
 uint4 h0=row_hamming4(a,b,begin-2,x,target),h1=row_hamming4(a,b,begin-1,x,target),
       h2=row_hamming4(a,b,begin,x,target),h3=row_hamming4(a,b,begin+1,x,target),h4=row_hamming4(a,b,begin+2,x,target);
 uint4 sum=h0+h1+h2+h3+h4;
 int4 xv=(int4)(x,x+1,x+2,x+3),tv=xv+direction*d;
 int4 supported=(xv>=2)&(xv<W-2)&(tv>=2)&(tv<W-2);
 // Five explicit registers avoid a dynamically indexed private array (spills).
#define EMIT(K) { int yy=y+K; \
 vstore4(convert_uchar4(select((uint4)(255),sum,convert_uint4(supported&(int4)(yy>=4&&yy<H-4?-1:0)))),0,cost+(d*H+yy)*W+x); \
 uint4 entering=row_hamming4(a,b,yy+3,x,target);sum+=entering-h##K;h##K=entering; }
 for(int y=begin;y<begin+80;y+=5){EMIT(0);EMIT(1);EMIT(2);EMIT(3);EMIT(4);}
#undef EMIT
}
__kernel void packed_winner(__global const uchar* cost,__global short* output,int direction) {
 int x=get_global_id(0)*4,y=get_global_id(1);if(x>=W||y>=H)return;
 int idx=y*W+x;
 if(y<6||y>=H-6||x<4||x>=W-4){vstore4((short4)(-1),0,output+idx);return;}
 uint4 v0=(uint4)(0xffffffffu),v1=v0,v2=v0,v3=v0;
 for(int d=0;d<D;++d){
  int offset=0;
#ifdef REUSE
  offset=direction>0?d:0;
  if(direction>0&&x+d>=W-4)continue;
#endif
  uchar8 a=vload8(0,cost+(d*H+y)*W+x+offset-2);
  uint4 s=convert_uint4(a.s0123)+convert_uint4(a.s1234)+convert_uint4(a.s2345)+convert_uint4(a.s3456)+convert_uint4(a.s4567);
  int4 target=(int4)(x,x+1,x+2,x+3)+direction*d;
  uint4 v=select((uint4)(0xffffffffu),s*D+d,convert_uint4((target>=4)&(target<W-4)));
  uint4 t=min(v,v0);v=max(v,v0);v0=t;t=min(v,v1);v=max(v,v1);v1=t;t=min(v,v2);v=max(v,v2);v2=t;v3=min(v,v3);
 }
 int4 bestd=convert_int4(v0%D);uint4 best=v0/D,second=(uint4)(0xffffffffu);
 second=min(second,select((uint4)(0xffffffffu),v1/D,convert_uint4((v1!=(uint4)(0xffffffffu))&(abs(convert_int4(v1%D)-bestd)>1))));
 second=min(second,select((uint4)(0xffffffffu),v2/D,convert_uint4((v2!=(uint4)(0xffffffffu))&(abs(convert_int4(v2%D)-bestd)>1))));
 second=min(second,select((uint4)(0xffffffffu),v3/D,convert_uint4((v3!=(uint4)(0xffffffffu))&(abs(convert_int4(v3%D)-bestd)>1))));
 int4 valid=(v0!=(uint4)(0xffffffffu))&(bestd>0)&(bestd<D-1)&((second==(uint4)(0xffffffffu))|(second*90u>best*100u));
 vstore4(convert_short4(select((int4)(-1),bestd,valid)),0,output+idx);
}
#endif
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

int main(int argc, char** argv) {
try {
    const std::string mode=argc>1?argv[1]:"--wide";
    const bool wide=mode=="--wide";
    const bool ring=mode=="--ring"||wide;
    const bool reuse=mode=="--reuse"||ring;
    const bool vector_mode=mode=="--vector"||reuse;
    const bool packed=mode=="--packed"||vector_mode;
    const bool reference=mode=="--reference",sliding=mode=="--sliding",spatial=mode=="--spatial"||packed;
    const int iterations=argc>2?std::stoi(argv[2]):30;
    if(iterations<1||iterations>3000)throw std::runtime_error("Invalid iteration count");
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
    error=clBuildProgram(program.get(),1,&device,reuse?"-cl-std=CL2.0 -DPACKED=1 -DREUSE=1":packed?"-cl-std=CL2.0 -DPACKED=1":"-cl-std=CL2.0",nullptr,nullptr);
    if(error) {
        size_t count{};clGetProgramBuildInfo(program.get(),device,CL_PROGRAM_BUILD_LOG,0,nullptr,&count);
        std::vector<char> log(count);clGetProgramBuildInfo(program.get(),device,CL_PROGRAM_BUILD_LOG,count,log.data(),nullptr);
        std::cerr<<log.data()<<'\n';check(error,"build");
    }
    auto buffer=[&](size_t bytes) { Buffer b(clCreateBuffer(context.get(),CL_MEM_READ_WRITE,bytes,nullptr,&error));check(error,"buffer");return b; };
    auto kernel=[&](const char* key) { Kernel k(clCreateKernel(program.get(),key,&error));check(error,key);return k; };
    auto il=buffer(N),ir=buffer(N),cl=buffer(N*4),cr=buffer(N*4),cost=buffer((reference||sliding||spatial)?size_t(N)*D*(packed?1:2):2),
         dl=buffer(N*2),dr=buffer(N*2),out=buffer(N*4);
    auto census=kernel("census"),horizontal=kernel("horizontal"),winner=kernel("winner"),consistency=kernel("consistency");
    auto tiled=kernel("tiled");
    auto sliding_cost=kernel("sliding_cost"),subgroup_winner=kernel("subgroup_winner");
    auto spatial_cost=kernel("spatial_cost"),spatial_winner=kernel("spatial_winner");
    auto packed_winner=packed?kernel("packed_winner"):Kernel{};
    auto vector_cost=vector_mode?kernel(ring?"ring_cost":"vector_cost"):Kernel{};
    auto arg=[&](const Kernel& k,int index,const Buffer& b) { auto handle=b.get();check(clSetKernelArg(k.get(),index,sizeof(handle),&handle),"buffer arg"); };
    auto dir=[&](const Kernel& k,int index,int direction) { check(clSetKernelArg(k.get(),index,sizeof(direction),&direction),"direction"); };
    size_t image_size[]={W,H},volume_size[]={D,W,H},linear_size[]={N},winner_size[]={32,N},winner_local[]={32,1};
    size_t tile_size[]={32,W,H},tile_local[]={32,4,1};
    size_t cost_size[]={D,W};
    size_t spatial_size[]={576,H},spatial_cost_size[]={576,D},spatial_local[]={64,1};
    size_t packed_size[]={wide?192u:160u,H},packed_local[]={wide?64u:32u,1};
    size_t vector_cost_size[]={wide?192u:160u,D,8},vector_local[]={wide?64u:32u,1,1};
    std::vector<float> disparity(N);std::vector<short> gpu_left(N);std::vector<uint32_t> gpu_census(N);
    std::vector<double> wall,kernel_times;std::vector<std::vector<double>> stage_times(reuse?6:(reference||sliding||spatial)?7:5);
    for(int run=0;run<iterations+5;++run) {
        auto begin=std::chrono::steady_clock::now();std::vector<Event> events;
        auto launch=[&](const Kernel& k,int dims,const size_t* size,const size_t* local=nullptr) {
            cl_event event{};check(clEnqueueNDRangeKernel(queue.get(),k.get(),dims,nullptr,size,local,0,nullptr,&event),"enqueue");
            events.emplace_back(event);
        };
        check(clEnqueueWriteBuffer(queue.get(),il.get(),CL_FALSE,0,N,left.data(),0,nullptr,nullptr),"upload left");
        check(clEnqueueWriteBuffer(queue.get(),ir.get(),CL_FALSE,0,N,right.data(),0,nullptr,nullptr),"upload right");
        arg(census,0,il);arg(census,1,cl);launch(census,2,image_size);
        arg(census,0,ir);arg(census,1,cr);launch(census,2,image_size);
        for(int side=0;side<2;++side) {
          if(spatial) {
            if(!reuse||side==0) {
            auto& cost_kernel=vector_mode?vector_cost:spatial_cost;
            arg(cost_kernel,0,side?cr:cl);arg(cost_kernel,1,side?cl:cr);arg(cost_kernel,2,cost);dir(cost_kernel,3,side?1:-1);
            launch(cost_kernel,vector_mode?3:2,vector_mode?vector_cost_size:spatial_cost_size,vector_mode?vector_local:spatial_local);
            }
            auto& choose=packed?packed_winner:spatial_winner;
            arg(choose,0,cost);arg(choose,1,side?dr:dl);dir(choose,2,side?1:-1);
            launch(choose,2,packed?packed_size:spatial_size,packed?packed_local:spatial_local);
          } else if(sliding) {
            arg(sliding_cost,0,side?cr:cl);arg(sliding_cost,1,side?cl:cr);arg(sliding_cost,2,cost);dir(sliding_cost,3,side?1:-1);
            launch(sliding_cost,2,cost_size);
            arg(subgroup_winner,0,cost);arg(subgroup_winner,1,side?dr:dl);dir(subgroup_winner,2,side?1:-1);
            launch(subgroup_winner,2,winner_size,winner_local);
          } else if(reference) {
            arg(horizontal,0,side?cr:cl);arg(horizontal,1,side?cl:cr);arg(horizontal,2,cost);dir(horizontal,3,side?1:-1);
            launch(horizontal,3,volume_size);
            arg(winner,0,cost);arg(winner,1,side?dr:dl);dir(winner,2,side?1:-1);launch(winner,2,winner_size,winner_local);
          } else {
            arg(tiled,0,side?cr:cl);arg(tiled,1,side?cl:cr);arg(tiled,2,side?dr:dl);dir(tiled,3,side?1:-1);
            launch(tiled,3,tile_size,tile_local);
          }
        }
        arg(consistency,0,dl);arg(consistency,1,dr);arg(consistency,2,out);launch(consistency,1,linear_size);
        check(clEnqueueReadBuffer(queue.get(),out.get(),CL_TRUE,0,N*4,disparity.data(),0,nullptr,nullptr),"download");
        double elapsed=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count(),kernel_ms=0;
        size_t stage=0;
        for(auto& event:events) {
            cl_ulong start{},end{};check(clGetEventProfilingInfo(event.get(),CL_PROFILING_COMMAND_START,sizeof(start),&start,nullptr),"profile start");
            check(clGetEventProfilingInfo(event.get(),CL_PROFILING_COMMAND_END,sizeof(end),&end,nullptr),"profile end");kernel_ms+=(end-start)*1e-6;
            if(run>=5)stage_times[stage].push_back((end-start)*1e-6);
            ++stage;
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
        if(gpu_left[y*W+x]!=(unique?bestd:-1))throw std::runtime_error("CPU/GPU disparity mismatch x="+std::to_string(x)+" y="+std::to_string(y)+" gpu="+std::to_string(gpu_left[y*W+x])+" cpu="+std::to_string(unique?bestd:-1));
        ++samples;
    }
    std::ofstream file("disparity.f32",std::ios::binary);file.write(reinterpret_cast<const char*>(disparity.data()),N*4);
    if(!file)throw std::runtime_error("Output write failed");
    std::sort(wall.begin(),wall.end());std::sort(kernel_times.begin(),kernel_times.end());
    auto valid=std::count_if(disparity.begin(),disparity.end(),[](float x){return std::isfinite(x)&&x>0;});
    for(size_t i=0;i<stage_times.size();++i){auto& values=stage_times[i];std::sort(values.begin(),values.end());std::cout<<"stage_"<<i<<"_median_ms="<<values[values.size()/2]<<'\n';}
    std::cout<<"measured_iterations="<<wall.size()<<"\nwall_median_ms="<<wall[wall.size()/2]
             <<"\nwall_p95_ms="<<wall[size_t((wall.size()-1)*.95)]<<"\nkernel_median_ms="<<kernel_times[kernel_times.size()/2]
             <<"\nvalid_fraction="<<double(valid)/N<<"\ncensus_checked_pixels="<<N
             <<"\ndisparity_checked_samples="<<samples<<"\n";
    std::cout<<"cost_volume_bytes="<<((reference||sliding||spatial)?size_t(N)*D*(packed?1:2):0)<<"\nmode="<<mode<<'\n';
} catch(const Error& e) { std::cerr<<"OpenCL error="<<e.code<<" operation="<<e.operation<<'\n';return 1;
} catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
