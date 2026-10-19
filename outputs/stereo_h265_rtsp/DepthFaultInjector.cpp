// Test-only LD_PRELOAD shim: fail a depth kernel after real frames have run.
// Does not intercept the stereo rectify10 kernel or alter the production binary.
#define CL_TARGET_OPENCL_VERSION 120
#include <CL/cl.h>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <dlfcn.h>
extern "C" cl_int clEnqueueNDRangeKernel(cl_command_queue queue,cl_kernel kernel,
    cl_uint dimensions,const size_t* offset,const size_t* global,const size_t* local,
    cl_uint count,const cl_event* wait,cl_event* event){
    using Function=decltype(&clEnqueueNDRangeKernel);
    static auto real=reinterpret_cast<Function>(dlsym(RTLD_NEXT,"clEnqueueNDRangeKernel"));
    static std::atomic<unsigned> depth_calls{};
    char name[80]{};clGetKernelInfo(kernel,CL_KERNEL_FUNCTION_NAME,sizeof(name),name,nullptr);
    if(!std::strcmp(name,"ring_cost")&&++depth_calls>=600){
        std::fprintf(stderr,"TEST_FAULT_INJECTED kernel=ring_cost code=CL_OUT_OF_RESOURCES\n");return CL_OUT_OF_RESOURCES;
    }
    return real?real(queue,kernel,dimensions,offset,global,local,count,wait,event):CL_INVALID_OPERATION;
}
