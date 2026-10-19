#include "VideoStream.hpp"
#include <gst/app/gstappsrc.h>
#include <gst/app/gstappsink.h>
#include <gst/rtsp-server/rtsp-server.h>
#include <gst/video/video-event.h>
#include <algorithm>
#include <atomic>
#include <cstring>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <map>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <time.h>

namespace board_depth {
namespace {std::uint64_t clock_ns(){timespec t{};clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec*1000000000ull+t.tv_nsec;}}
struct VideoStream::Impl {
    int width,height;bool marker;
    GstElement* pipeline{};GstAppSrc* input{};GstAppSink* sink{};GstBufferPool* pool{};
    GMainContext* context{};GMainLoop* loop{};GstRTSPServer* server{};guint source_id{};std::thread thread;
    mutable std::mutex mutex;GstAppSrc* destination{};GstClockTime media_base=GST_CLOCK_TIME_NONE;
    bool wait_key=true;std::uint64_t origin{};std::map<std::uint64_t,std::uint64_t> pending;
    std::atomic<std::uint64_t> submitted{},encoded{},max_queue{},missing{};std::atomic<bool> failed{};
    std::string csv_path;std::ofstream csv;
    Impl(int w,int h,int port,const std::string& mount,const std::string& path,bool timing):width(w),height(h),marker(timing),csv_path(path),csv(path){
        if(!csv)throw std::runtime_error("encoder CSV open");
        csv<<"source_stamp_ns,depth_ready_ns,encoded_ready_ns,bytes,keyframe\n";
        try{
            gst_init(nullptr,nullptr);
            std::string description="appsrc name=input is-live=true block=false format=time max-buffers=2 max-bytes=0 max-time=0 leaky-type=downstream caps=video/x-raw,format=NV12,width="+
                std::to_string(w)+",height="+std::to_string(h)+",framerate=30/1,interlace-mode=progressive,colorimetry=bt709 ! queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 leaky=downstream ! v4l2h265enc output-io-mode=mmap capture-io-mode=mmap extra-controls=\"controls,vui_timing_info=1,prepend_sps_and_pps_to_idr=1,video_bitrate=6000000,video_gop_size=30\" ! h265parse config-interval=-1 ! video/x-h265,stream-format=byte-stream,alignment=au ! appsink name=encoded emit-signals=true sync=false max-buffers=3 drop=true";
            GError* error{};pipeline=gst_parse_launch(description.c_str(),&error);
            if(error){std::string message=error->message;g_error_free(error);throw std::runtime_error(message);}
            if(!pipeline)throw std::runtime_error("encoder pipeline");
            input=GST_APP_SRC(gst_bin_get_by_name(GST_BIN(pipeline),"input"));sink=GST_APP_SINK(gst_bin_get_by_name(GST_BIN(pipeline),"encoded"));
            pool=gst_buffer_pool_new();auto* configuration=gst_buffer_pool_get_config(pool);
            gst_buffer_pool_config_set_params(configuration,nullptr,std::size_t(w)*h*3/2,3,8);
            if(!gst_buffer_pool_set_config(pool,configuration)||!gst_buffer_pool_set_active(pool,TRUE))throw std::runtime_error("encoder buffer pool");
            g_signal_connect(sink,"new-sample",G_CALLBACK(sample),this);
            if(gst_element_set_state(pipeline,GST_STATE_PLAYING)==GST_STATE_CHANGE_FAILURE)throw std::runtime_error("encoder PLAYING");
            context=g_main_context_new();loop=g_main_loop_new(context,FALSE);server=gst_rtsp_server_new();
            gst_rtsp_server_set_address(server,"192.168.137.226");gst_rtsp_server_set_service(server,std::to_string(port).c_str());
            auto* factory=gst_rtsp_media_factory_new();
            gst_rtsp_media_factory_set_shared(factory,TRUE);gst_rtsp_media_factory_set_stop_on_disconnect(factory,TRUE);
            gst_rtsp_media_factory_set_protocols(factory,GST_RTSP_LOWER_TRANS_TCP);
            gst_rtsp_media_factory_set_launch(factory,"( appsrc name=source is-live=true block=false format=time max-buffers=3 max-bytes=0 max-time=0 leaky-type=downstream caps=video/x-h265,stream-format=byte-stream,alignment=au ! h265parse ! rtph265pay name=pay0 pt=96 config-interval=-1 )");
            g_signal_connect(factory,"media-configure",G_CALLBACK(configure),this);
            auto* mounts=gst_rtsp_server_get_mount_points(server);gst_rtsp_mount_points_add_factory(mounts,mount.c_str(),factory);g_object_unref(mounts);
            source_id=gst_rtsp_server_attach(server,context);if(!source_id)throw std::runtime_error("RTSP bind");
            thread=std::thread([this]{g_main_loop_run(loop);});
            std::cout<<"rtsp=rtsp://192.168.137.226:"<<port<<mount<<" width="<<w<<" height="<<h<<'\n'<<std::flush;
        }catch(...){close();throw;}
    }
    ~Impl(){close();}
    static GstFlowReturn sample(GstAppSink* appsink,gpointer p){
        auto& self=*static_cast<Impl*>(p);GstSample* sample=gst_app_sink_pull_sample(appsink);if(!sample)return GST_FLOW_EOS;
        GstBuffer* buffer=gst_sample_get_buffer(sample);auto pts=GST_BUFFER_PTS(buffer);const auto finished=clock_ns();
        GstAppSrc* target{};GstClockTime base{};
        {
            std::lock_guard<std::mutex> lock(self.mutex);
            ++self.encoded;
            auto found=self.pending.find(pts);std::uint64_t ready=0;
            if(found!=self.pending.end()){ready=found->second;self.pending.erase(found);}else ++self.missing;
            self.csv<<self.origin+pts<<','<<ready<<','<<finished<<','<<gst_buffer_get_size(buffer)<<','<<(!GST_BUFFER_FLAG_IS_SET(buffer,GST_BUFFER_FLAG_DELTA_UNIT))<<'\n';
            if(self.csv.tellp()>8*1024*1024){
                self.csv.close();std::error_code ec;std::filesystem::remove(self.csv_path+".previous",ec);
                std::filesystem::rename(self.csv_path,self.csv_path+".previous",ec);self.csv.open(self.csv_path);
                self.csv<<"source_stamp_ns,depth_ready_ns,encoded_ready_ns,bytes,keyframe\n";
                if(!self.csv)self.failed=true;
            }
            if(self.destination){
                if(self.wait_key&&!GST_BUFFER_FLAG_IS_SET(buffer,GST_BUFFER_FLAG_DELTA_UNIT)){self.wait_key=false;self.media_base=pts;}
                if(!self.wait_key&&GST_CLOCK_TIME_IS_VALID(pts)&&pts>=self.media_base){target=GST_APP_SRC(gst_object_ref(self.destination));base=self.media_base;}
            }
        }
        if(target){auto* copy=gst_buffer_copy(buffer);GST_BUFFER_PTS(copy)=pts-base;GST_BUFFER_DTS(copy)=GST_CLOCK_TIME_NONE;gst_app_src_push_buffer(target,copy);gst_object_unref(target);}
        gst_sample_unref(sample);return GST_FLOW_OK;
    }
    static void configure(GstRTSPMediaFactory*,GstRTSPMedia* media,gpointer p){
        auto& self=*static_cast<Impl*>(p);auto* element=gst_rtsp_media_get_element(media);
        auto* source=GST_APP_SRC(gst_bin_get_by_name_recurse_up(GST_BIN(element),"source"));
        {std::lock_guard<std::mutex> lock(self.mutex);if(self.destination)gst_object_unref(self.destination);self.destination=source;self.media_base=GST_CLOCK_TIME_NONE;self.wait_key=true;}
        g_object_set_data(G_OBJECT(media),"depth-source",source);
        g_signal_connect(media,"unprepared",G_CALLBACK(+[](GstRTSPMedia* m,gpointer p){
            auto& self=*static_cast<Impl*>(p);std::lock_guard<std::mutex> lock(self.mutex);
            if(self.destination==g_object_get_data(G_OBJECT(m),"depth-source")){gst_object_unref(self.destination);self.destination=nullptr;}
        }),p);
        gst_object_unref(element);gst_element_send_event(GST_ELEMENT(self.sink),gst_video_event_new_upstream_force_key_unit(GST_CLOCK_TIME_NONE,TRUE,0));
    }
    bool push(const std::vector<std::uint8_t>& bytes,std::uint64_t stamp,std::uint64_t ready){
        if(failed)return false;
        if(bytes.size()!=std::size_t(width)*height*3/2)return false;
        auto* bus=gst_element_get_bus(pipeline);auto* error=gst_bus_pop_filtered(bus,GST_MESSAGE_ERROR);gst_object_unref(bus);
        if(error){GError* detail{};gchar* debug{};gst_message_parse_error(error,&detail,&debug);std::cerr<<"encoder_error="<<(detail?detail->message:"")<<" detail="<<(debug?debug:"")<<'\n';if(detail)g_error_free(detail);g_free(debug);gst_message_unref(error);failed=true;return false;}
        GstBuffer* buffer{};GstBufferPoolAcquireParams acquire{};acquire.flags=GST_BUFFER_POOL_ACQUIRE_FLAG_DONTWAIT;
        if(gst_buffer_pool_acquire_buffer(pool,&buffer,&acquire)!=GST_FLOW_OK){failed=true;return false;}
        GstMapInfo map{};if(!gst_buffer_map(buffer,&map,GST_MAP_WRITE)){gst_buffer_unref(buffer);return false;}
        std::memcpy(map.data,bytes.data(),bytes.size());
        if(marker){for(int bit=0;bit<64;++bit)for(int y=0;y<16;++y)for(int x=0;x<8;++x){bool one=((stamp>>bit)&1)!=0;if(y>=8)one=!one;map.data[(height-16+y)*width+16+bit*8+x]=one?235:16;}}
        gst_buffer_unmap(buffer,&map);
        {std::lock_guard<std::mutex> lock(mutex);if(!origin)origin=stamp;GST_BUFFER_PTS(buffer)=stamp-origin;pending[stamp-origin]=ready;while(pending.size()>120)pending.erase(pending.begin());}
        GST_BUFFER_DURATION(buffer)=GST_SECOND/30;
        auto level=gst_app_src_get_current_level_buffers(input);auto previous=max_queue.load();while(level>previous&&!max_queue.compare_exchange_weak(previous,level)){}
        auto result=gst_app_src_push_buffer(input,buffer);if(result!=GST_FLOW_OK){failed=true;return false;}++submitted;return true;
    }
    void close(){
        if(server){
            auto* clients=gst_rtsp_server_client_filter(server,nullptr,nullptr);
            for(auto* item=clients;item;item=item->next){gst_rtsp_client_close(GST_RTSP_CLIENT(item->data));gst_object_unref(item->data);}
            g_list_free(clients);
        }
        if(input)gst_app_src_end_of_stream(input);
        if(pipeline){auto* bus=gst_element_get_bus(pipeline);auto* end=gst_bus_timed_pop_filtered(bus,2*GST_SECOND,GstMessageType(GST_MESSAGE_EOS|GST_MESSAGE_ERROR));if(end)gst_message_unref(end);gst_object_unref(bus);}
        if(pipeline)gst_element_set_state(pipeline,GST_STATE_NULL);
        if(source_id&&context){if(auto* source=g_main_context_find_source_by_id(context,source_id))g_source_destroy(source);source_id=0;}
        if(loop)g_main_loop_quit(loop);
        if(thread.joinable())thread.join();
        {std::lock_guard<std::mutex> lock(mutex);if(destination){gst_object_unref(destination);destination=nullptr;}}
        if(input){gst_object_unref(input);input=nullptr;}if(sink){gst_object_unref(sink);sink=nullptr;}
        if(pipeline){gst_object_unref(pipeline);pipeline=nullptr;}if(server){g_object_unref(server);server=nullptr;}
        if(pool){gst_buffer_pool_set_active(pool,FALSE);gst_object_unref(pool);pool=nullptr;}
        if(loop){g_main_loop_unref(loop);loop=nullptr;}if(context){g_main_context_unref(context);context=nullptr;}
    }
};
VideoStream::VideoStream(int w,int h,int port,std::string mount,std::string csv,bool timing):impl_(std::make_unique<Impl>(w,h,port,mount,csv,timing)){}
VideoStream::~VideoStream()=default;VideoStream::VideoStream(VideoStream&&)noexcept=default;VideoStream& VideoStream::operator=(VideoStream&&)noexcept=default;
bool VideoStream::push(const std::vector<std::uint8_t>& b,std::uint64_t s,std::uint64_t r){return impl_->push(b,s,r);}
StreamStatistics VideoStream::statistics()const{return {impl_->submitted,impl_->encoded,impl_->max_queue,impl_->missing,impl_->failed};}
void VideoStream::close(){impl_->close();}
}
