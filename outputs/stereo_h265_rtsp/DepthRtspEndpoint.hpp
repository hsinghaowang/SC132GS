#pragma once
// Private RTSP adapter. The public server header exposes no GStreamer types.
#include "DepthPipeline.hpp"
#include <gst/app/gstappsrc.h>
#include <gst/rtsp-server/rtsp-server.h>
#include <atomic>
#include <chrono>
#include <iostream>
#include <memory>
#include <mutex>
namespace stereo_rtsp::detail {
class DepthRtspEndpoint final : public DepthPipeline::Observer {
    struct State {
        std::mutex mutex;GstAppSrc* source{};
        std::uint64_t base{};bool wait_key=true,failed=false,closing=false;
        std::atomic<bool> request_key{};std::atomic<std::uint64_t> encoded{};
        bool playing{};
        bool rebase=true,have_last=false;
        std::uint64_t last_pts{};
        std::chrono::steady_clock::time_point prepare_until{};
        ~State(){if(source)gst_object_unref(source);}
    };
    using Shared=std::shared_ptr<State>;
    Shared state_=std::make_shared<State>();GstRTSPMediaFactory* factory_{};
    static void destroy_shared(gpointer data,GClosure*){delete static_cast<Shared*>(data);}
    static void unprepared(GstRTSPMedia* media,gpointer data){
        auto s=*static_cast<Shared*>(data);std::lock_guard lock(s->mutex);
        if(s->source==g_object_get_data(G_OBJECT(media),"depth-source")){
            gst_object_unref(s->source);s->source=nullptr;
        }
    }
    static void configure(GstRTSPMediaFactory*,GstRTSPMedia* media,gpointer data){
        auto s=*static_cast<Shared*>(data);auto* element=gst_rtsp_media_get_element(media);
        auto* source=GST_APP_SRC(gst_bin_get_by_name_recurse_up(GST_BIN(element),"depth_source"));
        bool unavailable;
        {std::lock_guard lock(s->mutex);unavailable=s->failed||s->closing;
            if(!unavailable){if(s->source)gst_object_unref(s->source);s->source=GST_APP_SRC(gst_object_ref(source));s->base=0;s->rebase=true;s->have_last=false;s->wait_key=true;s->request_key=true;s->playing=false;s->prepare_until=std::chrono::steady_clock::now()+std::chrono::seconds(10);}}
        g_object_set_data_full(G_OBJECT(media),"depth-source",gst_object_ref(source),+[](gpointer p){gst_object_unref(p);});
        g_signal_connect_data(media,"unprepared",G_CALLBACK(unprepared),new Shared(s),destroy_shared,GConnectFlags(0));
        g_signal_connect_data(media,"new-state",G_CALLBACK(+[](GstRTSPMedia* m,gint state,gpointer p){
            auto s=*static_cast<Shared*>(p);std::lock_guard lock(s->mutex);
            if(s->source!=g_object_get_data(G_OBJECT(m),"depth-source"))return;
            if(state==GST_STATE_PLAYING && !s->playing){s->rebase=true;s->wait_key=true;s->request_key=true;}
            if(state==GST_STATE_PLAYING || s->playing)s->prepare_until={};
            s->playing=state==GST_STATE_PLAYING;
        }),new Shared(s),destroy_shared,GConnectFlags(0));
        if(unavailable)gst_app_src_end_of_stream(source);
        gst_object_unref(source);gst_object_unref(element);
    }
public:
    ~DepthRtspEndpoint(){
        {std::lock_guard lock(state_->mutex);state_->closing=true;if(state_->source){gst_object_unref(state_->source);state_->source=nullptr;}}
        if(factory_)gst_object_unref(factory_);
    }
    DepthRtspEndpoint()=default;DepthRtspEndpoint(const DepthRtspEndpoint&)=delete;
    DepthRtspEndpoint& operator=(const DepthRtspEndpoint&)=delete;
    void mount(GstRTSPMountPoints* mounts){
        factory_=gst_rtsp_media_factory_new();gst_rtsp_media_factory_set_shared(factory_,TRUE);
        gst_rtsp_media_factory_set_protocols(factory_,GST_RTSP_LOWER_TRANS_TCP);
        gst_rtsp_media_factory_set_launch(factory_,"( appsrc name=depth_source is-live=true block=false format=time max-buffers=3 max-bytes=0 max-time=0 leaky-type=downstream caps=video/x-h265,stream-format=byte-stream,alignment=au ! h265parse ! rtph265pay name=pay0 pt=96 config-interval=-1 )");
        g_signal_connect_data(factory_,"media-configure",G_CALLBACK(configure),new Shared(state_),destroy_shared,GConnectFlags(0));
        gst_rtsp_mount_points_add_factory(mounts,"/depth",GST_RTSP_MEDIA_FACTORY(gst_object_ref(factory_)));
    }
    bool take_keyframe_request()noexcept{return state_->request_key.exchange(false);}
    bool has_demand()const noexcept{
        std::lock_guard lock(state_->mutex);
        return state_->source && !state_->closing &&
            (state_->playing || std::chrono::steady_clock::now()<state_->prepare_until);
    }
    void begin_capture()noexcept{
        std::lock_guard lock(state_->mutex);state_->failed=false;state_->wait_key=true;state_->request_key=true;
    }
    std::uint64_t encoded()const noexcept{return state_->encoded;}
    void on_depth_access_unit(const DepthAccessUnit& unit)noexcept override {
        ++state_->encoded;GstAppSrc* target{};std::uint64_t base{};
        {std::lock_guard lock(state_->mutex);
            if(!state_->failed&&!state_->closing&&state_->source &&
                (state_->playing || std::chrono::steady_clock::now()<state_->prepare_until)){
                if(state_->wait_key&&unit.keyframe){
                    state_->wait_key=false;
                    if(state_->rebase){state_->base=unit.source_timestamp_ns-(state_->have_last?state_->last_pts+GST_SECOND/30:0);state_->rebase=false;}
                }
                if(!state_->wait_key&&unit.source_timestamp_ns>=state_->base){target=GST_APP_SRC(gst_object_ref(state_->source));base=state_->base;state_->last_pts=unit.source_timestamp_ns-base;state_->have_last=true;}
            }}
        if(!target)return;
        auto* buffer=gst_buffer_new_allocate(nullptr,unit.bytes,nullptr);
        if(buffer){gst_buffer_fill(buffer,0,unit.data,unit.bytes);GST_BUFFER_PTS(buffer)=unit.source_timestamp_ns-base;
            GST_BUFFER_DTS(buffer)=GST_CLOCK_TIME_NONE;GST_BUFFER_DURATION(buffer)=GST_SECOND/30;
            if(!unit.keyframe)GST_BUFFER_FLAG_SET(buffer,GST_BUFFER_FLAG_DELTA_UNIT);
            gst_app_src_push_buffer(target,buffer);}
        gst_object_unref(target);
    }
    void on_depth_error(DepthError error)noexcept override {
        std::cerr<<"depth_disabled stage="<<int(error.stage)<<" native="<<error.native_code<<" stereo_continues=1\n";
        GstAppSrc* target{};
        {std::lock_guard lock(state_->mutex);state_->failed=true;if(state_->source)target=GST_APP_SRC(gst_object_ref(state_->source));}
        if(target){gst_app_src_end_of_stream(target);gst_object_unref(target);}
    }
};
}
