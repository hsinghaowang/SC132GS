#include "DepthPipeline.hpp"
#include "depth/GpuStereoDepth.hpp"
#include <gst/app/gstappsrc.h>
#include <gst/app/gstappsink.h>
#include <gst/video/video-event.h>
#include <atomic>
#include <condition_variable>
#include <cstring>
#include <fstream>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <type_traits>
#include <utility>

namespace stereo_rtsp::detail {
namespace {
constexpr std::size_t native=1088*1280;
template<class T>std::vector<T> read(const std::string& path,std::size_t count){
    std::vector<T> values(count);std::ifstream file(path,std::ios::binary);
    if(!file.read(reinterpret_cast<char*>(values.data()),count*sizeof(T)))throw std::runtime_error("depth calibration file");
    return values;
}
// Resident color encoder; no RTSP server, camera, AE, or parent error ownership.
class ColorEncoder {
    DepthPipeline::Observer& observer;
    GstElement* pipeline{};GstAppSrc* input{};GstAppSink* output{};GstBufferPool* pool{};
    std::uint64_t origin{};
public:
    explicit ColorEncoder(DepthPipeline::Observer& o):observer(o){
        try{
            GError* error{};
            pipeline=gst_parse_launch("appsrc name=input is-live=true block=false format=time max-buffers=2 max-bytes=0 max-time=0 leaky-type=downstream caps=video/x-raw,format=NV12,width=544,height=640,framerate=30/1,interlace-mode=progressive,colorimetry=bt709 ! queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 leaky=downstream ! v4l2h265enc output-io-mode=mmap capture-io-mode=mmap extra-controls=\"controls,vui_timing_info=1,prepend_sps_and_pps_to_idr=1,video_bitrate=6000000,video_gop_size=30\" ! h265parse config-interval=-1 ! video/x-h265,stream-format=byte-stream,alignment=au ! appsink name=output enable-last-sample=false emit-signals=true sync=false max-buffers=3 drop=true",&error);
            if(error){g_error_free(error);throw DepthError{DepthStage::encoding};}
            if(!pipeline)throw DepthError{DepthStage::encoding};
            input=GST_APP_SRC(gst_bin_get_by_name(GST_BIN(pipeline),"input"));output=GST_APP_SINK(gst_bin_get_by_name(GST_BIN(pipeline),"output"));
            pool=gst_buffer_pool_new();auto* config=gst_buffer_pool_get_config(pool);gst_buffer_pool_config_set_params(config,nullptr,544*640*3/2,3,8);
            if(!gst_buffer_pool_set_config(pool,config)||!gst_buffer_pool_set_active(pool,TRUE))throw DepthError{DepthStage::encoding};
            g_signal_connect(output,"new-sample",G_CALLBACK(sample),this);
            if(gst_element_set_state(pipeline,GST_STATE_PLAYING)==GST_STATE_CHANGE_FAILURE)throw DepthError{DepthStage::encoding};
        }catch(...){close();throw;}
    }
    ~ColorEncoder(){close();}
    static GstFlowReturn sample(GstAppSink* sink,gpointer data){
        auto& self=*static_cast<ColorEncoder*>(data);auto* sample=gst_app_sink_pull_sample(sink);if(!sample)return GST_FLOW_EOS;
        auto* buffer=gst_sample_get_buffer(sample);GstMapInfo map{};
        if(gst_buffer_map(buffer,&map,GST_MAP_READ)){
            self.observer.on_depth_access_unit({map.data,map.size,self.origin+GST_BUFFER_PTS(buffer),!GST_BUFFER_FLAG_IS_SET(buffer,GST_BUFFER_FLAG_DELTA_UNIT)});
            gst_buffer_unmap(buffer,&map);
        }
        gst_sample_unref(sample);return GST_FLOW_OK;
    }
    void push(const std::vector<std::uint8_t>& bytes,std::uint64_t stamp,bool keyframe){
        auto* bus=gst_element_get_bus(pipeline);auto* error=gst_bus_pop_filtered(bus,GST_MESSAGE_ERROR);gst_object_unref(bus);
        if(error){gst_message_unref(error);throw DepthError{DepthStage::encoding};}
        if(bytes.size()!=544*640*3/2)throw DepthError{DepthStage::encoding};
        if(keyframe)gst_element_send_event(GST_ELEMENT(output),gst_video_event_new_upstream_force_key_unit(GST_CLOCK_TIME_NONE,TRUE,0));
        GstBuffer* buffer{};GstBufferPoolAcquireParams params{};params.flags=GST_BUFFER_POOL_ACQUIRE_FLAG_DONTWAIT;
        auto result=gst_buffer_pool_acquire_buffer(pool,&buffer,&params);if(result!=GST_FLOW_OK)throw DepthError{DepthStage::encoding,int(result)};
        GstMapInfo map{};if(!gst_buffer_map(buffer,&map,GST_MAP_WRITE)){gst_buffer_unref(buffer);throw DepthError{DepthStage::encoding};}
        std::memcpy(map.data,bytes.data(),bytes.size());gst_buffer_unmap(buffer,&map);
        if(!origin)origin=stamp;GST_BUFFER_PTS(buffer)=stamp-origin;GST_BUFFER_DURATION(buffer)=GST_SECOND/30;
        result=gst_app_src_push_buffer(input,buffer);if(result!=GST_FLOW_OK)throw DepthError{DepthStage::encoding,int(result)};
    }
    void close()noexcept{
        if(pipeline){
            gst_element_set_state(pipeline,GST_STATE_NULL);
            gst_element_get_state(pipeline,nullptr,nullptr,5*GST_SECOND);
            auto* bus=gst_element_get_bus(pipeline);gst_bus_set_flushing(bus,TRUE);gst_object_unref(bus);
        }
        if(input){gst_object_unref(input);input=nullptr;}if(output){gst_object_unref(output);output=nullptr;}
        if(pipeline){gst_object_unref(pipeline);pipeline=nullptr;}
        if(pool){gst_buffer_pool_set_active(pool,FALSE);gst_object_unref(pool);pool=nullptr;}
    }
};
}
struct DepthPipeline::Impl {
    enum class Encoding { raw10, mono8 };
    Observer& observer;std::string directory;
    std::mutex mutex;std::condition_variable condition;
    std::vector<std::uint16_t> cam0,cam1;std::uint64_t timestamp{};bool pending{},ready{};
    std::vector<std::uint8_t> cam0_8,cam1_8;Encoding encoding{Encoding::raw10};
    std::atomic<bool> stopping{},failed{},keyframe{};
    std::atomic<std::uint64_t> submitted{},processed{},replaced{},busy{};
    std::thread worker;
    Impl(std::string path,Observer& o):observer(o),directory(std::move(path)),cam0(native),cam1(native),cam0_8(native),cam1_8(native),worker([this]{run();}){
        // Complete GPU compilation before the parent starts camera DMA. A
        // cold depth context must not starve the cameras' hardware buffers.
        std::unique_lock lock(mutex);condition.wait(lock,[this]{return ready||failed;});
    }
    ~Impl(){stop();}
    void fail(DepthError e)noexcept{
        bool first;{std::lock_guard lock(mutex);first=!failed.exchange(true);}
        condition.notify_all();if(first)observer.on_depth_error(e);
    }
    void run()noexcept{
        try{
            depth_gpu::Calibration c;c.emit_gray=false;
            c.left_map=read<std::int32_t>(directory+"/left-map.i32",544*640*2);c.right_map=read<std::int32_t>(directory+"/right-map.i32",544*640*2);
            c.left_valid=read<std::uint8_t>(directory+"/left-valid.u8",544*640);c.right_valid=read<std::uint8_t>(directory+"/right-valid.u8",544*640);
            c.yuv_palette=read<std::uint8_t>(directory+"/palette.u8",1024);
            {std::ifstream f(directory+"/focal-baseline.txt");if(!(f>>c.focal_times_baseline_m_px))throw DepthError{DepthStage::initialization};}
            auto opened=depth_gpu::GpuStereoDepth::open(c);
            if(auto* e=std::get_if<depth_gpu::Error>(&opened))throw DepthError{DepthStage::initialization,e->native_code};
            auto gpu=std::get<depth_gpu::GpuStereoDepth>(std::move(opened));ColorEncoder encoder(observer);
            std::vector<std::uint16_t> a(native),b(native);
            std::vector<std::uint8_t> a8(native),b8(native);
            // Warm both supported inputs before camera DMA starts; no
            // synthetic image is encoded/published.
            auto warm=gpu.process({a.data(),b.data(),native});
            if(auto* e=std::get_if<depth_gpu::Error>(&warm))throw DepthError{DepthStage::initialization,e->native_code};
            gpu.recycle(std::get<depth_gpu::DepthFrame>(std::move(warm)));
            warm=gpu.process8({a8.data(),b8.data(),native});
            if(auto* e=std::get_if<depth_gpu::Error>(&warm))throw DepthError{DepthStage::initialization,e->native_code};
            gpu.recycle(std::get<depth_gpu::DepthFrame>(std::move(warm)));
            {std::lock_guard lock(mutex);ready=true;}condition.notify_all();
            while(!stopping){
                std::uint64_t stamp;Encoding format;
                {std::unique_lock lock(mutex);condition.wait(lock,[this]{return stopping||pending;});if(stopping)break;
                    format=encoding;stamp=timestamp;
                    if(format==Encoding::mono8){a8.swap(cam0_8);b8.swap(cam1_8);}
                    else{a.swap(cam0);b.swap(cam1);}
                    pending=false;}
                auto result=format==Encoding::mono8?gpu.process8({a8.data(),b8.data(),native}):gpu.process({a.data(),b.data(),native});
                if(auto* e=std::get_if<depth_gpu::Error>(&result))throw DepthError{DepthStage::matching,e->native_code};
                auto& image=std::get<depth_gpu::DepthFrame>(result);encoder.push(image.depth_nv12,stamp,keyframe.exchange(false));
                ++processed;gpu.recycle(std::move(image));
            }
        }catch(const DepthError& e){fail(e);}
        catch(const std::exception&){fail({DepthStage::initialization});}
        catch(...){fail({DepthStage::internal});}
    }
    template<class Pixel>DepthSubmission submit(const Pixel* a,const Pixel* b,std::size_t n,std::uint64_t stamp)noexcept{
        if(failed||stopping)return DepthSubmission::disabled;
        if(!a||!b||n!=native||!stamp)return DepthSubmission::geometry;
        try{
            std::unique_lock lock(mutex,std::try_to_lock);if(!lock.owns_lock()){++busy;return DepthSubmission::busy;}
            if(failed||stopping)return DepthSubmission::disabled;
            const bool replace=pending;
            if constexpr(std::is_same_v<Pixel,std::uint8_t>){
                std::memcpy(cam0_8.data(),a,n);std::memcpy(cam1_8.data(),b,n);encoding=Encoding::mono8;
            }else{
                static_assert(std::is_same_v<Pixel,std::uint16_t>);
                std::memcpy(cam0.data(),a,n*sizeof(Pixel));std::memcpy(cam1.data(),b,n*sizeof(Pixel));encoding=Encoding::raw10;
            }
            timestamp=stamp;pending=true;++submitted;
            if(replace)++replaced;condition.notify_one();return replace?DepthSubmission::replaced:DepthSubmission::accepted;
        }catch(...){fail({DepthStage::input});return DepthSubmission::disabled;}
    }
    void stop()noexcept{{std::lock_guard lock(mutex);stopping=true;}condition.notify_all();if(worker.joinable())worker.join();}
};
DepthPipeline::DepthPipeline(std::string d,Observer& o):impl_(std::make_unique<Impl>(std::move(d),o)){}
DepthPipeline::~DepthPipeline()=default;
DepthPipeline::DepthPipeline(DepthPipeline&&)noexcept=default;
DepthPipeline& DepthPipeline::operator=(DepthPipeline&&)noexcept=default;
DepthSubmission DepthPipeline::submit(const std::uint16_t* a,const std::uint16_t* b,std::size_t n,std::uint64_t t)noexcept{return impl_->submit(a,b,n,t);}
DepthSubmission DepthPipeline::submit8(const std::uint8_t* a,const std::uint8_t* b,std::size_t n,std::uint64_t t)noexcept{return impl_->submit(a,b,n,t);}
void DepthPipeline::request_keyframe()noexcept{impl_->keyframe=true;}
void DepthPipeline::stop()noexcept{impl_->stop();}
DepthStatistics DepthPipeline::statistics()const noexcept{return {impl_->submitted,impl_->processed,impl_->replaced,impl_->busy,impl_->failed};}
}
