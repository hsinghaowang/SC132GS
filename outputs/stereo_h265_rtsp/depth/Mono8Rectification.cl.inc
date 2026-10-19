// This one source is stringified for OpenCL and compiled by the CPU contract
// check. The test substitutes only OpenCL qualifiers and get_global_id().
STEREO_MONO8_SOURCE(
uint mono8_native_sample(__global const uchar* eye,int x,int y){
    if(x<0||x>=1088||y<0||y>=1280)return 0;
    return eye[y*1088+x];
}
uchar mono8_remap(__global const uchar* src,int qx,int qy){
    int x=qx>>5,y=qy>>5,fx=qx&31,fy=qy&31;
    uint a=mono8_native_sample(src,x,y),b=mono8_native_sample(src,x+1,y);
    uint c=mono8_native_sample(src,x,y+1),d=mono8_native_sample(src,x+1,y+1);
    return (uchar)((a*(32-fx)*(32-fy)+b*fx*(32-fy)+c*(32-fx)*fy+d*fx*fy+512)>>10);
}
__kernel void rectify_native8(__global const uchar* cam0,__global const uchar* cam1,
    __global const int* lm,__global const int* rm,__global uchar* left,__global uchar* right){
    int g=(int)get_global_id(0);if(g>=2*544*640)return;
    int eye=g/(544*640),i=g%(544*640);
    __global const int* map=eye?rm:lm;
    uchar value=mono8_remap(eye?cam0:cam1,map[2*i],map[2*i+1]);
    if(eye)right[i]=value;else left[i]=value;
}
__kernel void rectify_gray8(__global const uchar* cam0,__global const uchar* cam1,
    __global const int* lm,__global const int* rm,__global uchar* out){
    int g=(int)get_global_id(0);if(g>=2*1088*1280)return;
    int eye=g/(1088*1280),i=g%(1088*1280);
    __global const int* map=eye?rm:lm;
    out[(i/1088)*2176+eye*1088+i%1088]=mono8_remap(eye?cam0:cam1,map[2*i],map[2*i+1]);
    if(g<1088*1280)out[2*1088*1280+g]=128;
}
)
