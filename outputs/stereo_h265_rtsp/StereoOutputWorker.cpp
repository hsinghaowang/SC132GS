#include "StereoOutputWorker.hpp"
#include <algorithm>
#include "StereoCapture.hpp"
#include "Main10Encoder.hpp"
#include "GpuStereoRectifier.hpp"
#include <atomic>
#include <condition_variable>
#include <mutex>
#include <optional>
#include <thread>
#include <utility>
namespace stereo_rtsp::detail {
struct StereoOutputWorker::Impl {
    struct Encoded {Main10Encoder& encoder;Observer& observer;};
    struct Luma {Luma8Observer& observer;};
    struct Pending {FramePair frame;std::uint64_t pts_ns;};
    std::variant<Encoded,Luma> sink;GpuStereoRectifier& rectifier;
    VideoRange display_range{VideoRange::limited};
    VideoRange input_range{VideoRange::limited};
    std::mutex mutex;std::condition_variable condition;std::optional<Pending> pending;
    bool stopping{};std::atomic<bool> keyframe{},failed{};
    std::atomic<std::uint64_t> processed{},submitted{},dropped{},replaced{},gpu_ns{};
    std::thread thread;
    Impl(Main10Encoder& e,GpuStereoRectifier& r,Observer& o):sink(Encoded{e,o}),rectifier(r),thread([this]{run();}){}
    Impl(GpuStereoRectifier& r,Luma8Observer& o,VideoRange output,VideoRange input):sink(Luma{o}),rectifier(r),display_range(output),input_range(input),thread([this]{run();}){}
    ~Impl(){stop();}
    void deliver(Encoded& output){for(auto& frame:output.encoder.receive())output.observer.on_stereo_access_unit({frame.bytes.data(),frame.bytes.size(),std::uint64_t(frame.timestamp_ns),frame.keyframe});}
    void run()noexcept{
        try{
            std::vector<std::uint16_t> stereo10;std::vector<std::uint8_t> stereo8;std::optional<std::int64_t> first;
            for(;;){
                std::optional<Pending> item;
                {std::unique_lock lock(mutex);condition.wait(lock,[this]{return stopping||pending.has_value();});
                    if(!pending)break;item=std::move(pending);pending.reset();}
                auto* frame=&item->frame;
                if(auto* output=std::get_if<Encoded>(&sink)) {
                    auto result=rectifier.process(frame->left_luma10.data(),frame->right_luma10.data(),frame->left_luma10.size(),stereo10);
                    if(auto* e=std::get_if<RectificationError>(&result))throw StereoProcessingError{StereoProcessingStage::rectification,e->native_code};
                    gpu_ns+=std::get<RectificationTiming>(result).gpu_ns;++processed;
                    if(!first)first=frame->cam0_timestamp_ns;
                    if(keyframe.exchange(false))output->encoder.request_keyframe();deliver(*output);
                    if(output->encoder.submit(stereo10,frame->cam0_timestamp_ns-*first))++submitted;else ++dropped;
                    deliver(*output);
                } else {
                    if(frame->left_luma.size()!=frame->right_luma.size())
                        throw StereoProcessingError{StereoProcessingStage::rectification};
                    // Matching owns a copy already. Only the video transport may
                    // require range conversion; the full-range depth input stays intact.
                    if(input_range!=display_range){
                        for(auto* eye:{&frame->left_luma,&frame->right_luma})for(auto& y:*eye)
                            y=static_cast<std::uint8_t>(display_range==VideoRange::limited?
                                16+(219*unsigned(y)+127)/255:std::clamp(((int(y)-16)*255+109)/219,0,255));
                    }
                    auto result=rectifier.process8(frame->left_luma.data(),frame->right_luma.data(),frame->left_luma.size(),stereo8,display_range);
                    if(auto* e=std::get_if<RectificationError>(&result))throw StereoProcessingError{StereoProcessingStage::rectification,e->native_code};
                    gpu_ns+=std::get<RectificationTiming>(result).gpu_ns;++processed;
                    if(std::get<Luma>(sink).observer.on_stereo_luma8({stereo8.data(),stereo8.size(),item->pts_ns}))++submitted;
                    else ++dropped;
                }
            }
        }catch(const StereoProcessingError& e){failed=true;notify(e);}
        catch(const EncoderError& e){failed=true;notify({StereoProcessingStage::encoding,e.system_error});}
        catch(...){failed=true;notify({StereoProcessingStage::internal});}
    }
    void notify(StereoProcessingError error)noexcept{std::visit([&](auto& output){output.observer.on_stereo_processing_error(error);},sink);}
    void submit(FramePair&& frame,std::uint64_t pts=0){std::lock_guard lock(mutex);if(stopping||failed)return;if(pending)++replaced;pending.emplace(Pending{std::move(frame),pts});condition.notify_one();}
    void stop()noexcept{{std::lock_guard lock(mutex);stopping=true;}condition.notify_all();if(thread.joinable())thread.join();}
};
StereoOutputWorker::StereoOutputWorker(Main10Encoder& e,GpuStereoRectifier& r,Observer& o):impl_(std::make_unique<Impl>(e,r,o)){}
StereoOutputWorker::StereoOutputWorker(GpuStereoRectifier& r,Luma8Observer& o,VideoRange output,VideoRange input):impl_(std::make_unique<Impl>(r,o,output,input)){}
StereoOutputWorker::~StereoOutputWorker()=default;
StereoOutputWorker::StereoOutputWorker(StereoOutputWorker&&)noexcept=default;
StereoOutputWorker& StereoOutputWorker::operator=(StereoOutputWorker&&)noexcept=default;
void StereoOutputWorker::submit(FramePair&& f){impl_->submit(std::move(f));}
void StereoOutputWorker::submit8(FramePair&& f,std::uint64_t pts){impl_->submit(std::move(f),pts);}
void StereoOutputWorker::request_keyframe()noexcept{impl_->keyframe=true;}
void StereoOutputWorker::stop()noexcept{impl_->stop();}
StereoOutputStatistics StereoOutputWorker::statistics()const noexcept{return {impl_->processed,impl_->submitted,impl_->dropped,impl_->replaced,impl_->gpu_ns};}
}
