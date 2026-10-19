#include "StereoOutputWorker.hpp"
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
    Main10Encoder& encoder;GpuStereoRectifier& rectifier;Observer& observer;
    std::mutex mutex;std::condition_variable condition;std::optional<FramePair> pending;
    bool stopping{};std::atomic<bool> keyframe{},failed{};
    std::atomic<std::uint64_t> processed{},submitted{},dropped{},replaced{},gpu_ns{};
    std::thread thread;
    Impl(Main10Encoder& e,GpuStereoRectifier& r,Observer& o):encoder(e),rectifier(r),observer(o),thread([this]{run();}){}
    ~Impl(){stop();}
    void deliver(){for(auto& frame:encoder.receive())observer.on_stereo_access_unit({frame.bytes.data(),frame.bytes.size(),std::uint64_t(frame.timestamp_ns),frame.keyframe});}
    void run()noexcept{
        try{
            std::vector<std::uint16_t> stereo10;std::optional<std::int64_t> first;
            for(;;){
                std::optional<FramePair> frame;
                {std::unique_lock lock(mutex);condition.wait(lock,[this]{return stopping||pending.has_value();});
                    if(!pending)break;frame=std::move(pending);pending.reset();}
                auto result=rectifier.process(frame->left_luma10.data(),frame->right_luma10.data(),frame->left_luma10.size(),stereo10);
                if(auto* e=std::get_if<RectificationError>(&result))throw StereoProcessingError{StereoProcessingStage::rectification,e->native_code};
                gpu_ns+=std::get<RectificationTiming>(result).gpu_ns;++processed;
                if(!first)first=frame->cam0_timestamp_ns;
                if(keyframe.exchange(false))encoder.request_keyframe();deliver();
                if(encoder.submit(stereo10,frame->cam0_timestamp_ns-*first))++submitted;else ++dropped;
                deliver();
            }
        }catch(const StereoProcessingError& e){failed=true;observer.on_stereo_processing_error(e);}
        catch(const EncoderError& e){failed=true;observer.on_stereo_processing_error({StereoProcessingStage::encoding,e.system_error});}
        catch(...){failed=true;observer.on_stereo_processing_error({StereoProcessingStage::internal});}
    }
    void submit(FramePair&& frame){std::lock_guard lock(mutex);if(stopping||failed)return;if(pending)++replaced;pending.emplace(std::move(frame));condition.notify_one();}
    void stop()noexcept{{std::lock_guard lock(mutex);stopping=true;}condition.notify_all();if(thread.joinable())thread.join();}
};
StereoOutputWorker::StereoOutputWorker(Main10Encoder& e,GpuStereoRectifier& r,Observer& o):impl_(std::make_unique<Impl>(e,r,o)){}
StereoOutputWorker::~StereoOutputWorker()=default;
StereoOutputWorker::StereoOutputWorker(StereoOutputWorker&&)noexcept=default;
StereoOutputWorker& StereoOutputWorker::operator=(StereoOutputWorker&&)noexcept=default;
void StereoOutputWorker::submit(FramePair&& f){impl_->submit(std::move(f));}
void StereoOutputWorker::request_keyframe()noexcept{impl_->keyframe=true;}
void StereoOutputWorker::stop()noexcept{impl_->stop();}
StereoOutputStatistics StereoOutputWorker::statistics()const noexcept{return {impl_->processed,impl_->submitted,impl_->dropped,impl_->replaced,impl_->gpu_ns};}
}
