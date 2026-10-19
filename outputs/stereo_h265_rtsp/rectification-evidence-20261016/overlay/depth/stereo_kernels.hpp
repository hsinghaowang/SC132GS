#pragma once
inline const char* stereo_kernels=R"CLC(
#define W 544
#define H 640
#define D 96
// Quantized maps match OpenCV INTER_LINEAR's 1/32 pixel interpolation table.
// Coordinates refer to the unmirrored full-resolution eye. Mirror restoration
// and half-size rectification are combined in this single inverse-map sample.
uint sample_raw(__global const uchar* raw,int x,int y,int offset) {
 if(x<0||x>=1088||y<0||y>=1280)return 0;
 return raw[y*2176+offset+1087-x];
}
__kernel void rectify_stereo(__global const uchar* raw,
 __global const int2* left_map,__global const int2* right_map,
 __global uchar* left,__global uchar* right) {
 int g=get_global_id(0);if(g>=2*W*H)return;
 int eye=g/(W*H),i=g%(W*H),offset=eye?0:1088;
 int2 xy=eye?right_map[i]:left_map[i];
 int x=xy.x>>5,y=xy.y>>5,fx=xy.x&31,fy=xy.y&31;
 uint a=sample_raw(raw,x,y,offset),b=sample_raw(raw,x+1,y,offset),
      c=sample_raw(raw,x,y+1,offset),d=sample_raw(raw,x+1,y+1,offset);
 uchar value=(uchar)((a*(32-fx)*(32-fy)+b*fx*(32-fy)+c*(32-fx)*fy+d*fx*fy+512)>>10);
 if(eye)right[i]=value;else left[i]=value;
}
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
