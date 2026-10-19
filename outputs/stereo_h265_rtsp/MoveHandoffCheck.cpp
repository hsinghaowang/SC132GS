#include "MoveHandoff.hpp"
#include "CaptureTrace.hpp"
#include <future>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>

namespace {
struct Frame {
    explicit Frame(unsigned n):pixels(64,n){}
    Frame(Frame&&)=default;Frame& operator=(Frame&&)=default;
    Frame(const Frame&)=delete;Frame& operator=(const Frame&)=delete;
    std::vector<unsigned> pixels;
};
void require(bool condition){if(!condition)throw std::runtime_error("handoff check failed");}
}
int main(){
    try{
        stereo_rtsp::detail::MoveHandoff<Frame> channel;
        std::promise<const unsigned*> identity;
        std::thread producer([&]{
            Frame first(42);identity.set_value(first.pixels.data());
            require(channel.put(std::move(first)));
            for(unsigned i=0;i<200;++i)require(channel.put(Frame(i)));
        });
        auto address=identity.get_future().get();
        auto first=channel.take();require(first && first->pixels.data()==address);
        for(unsigned i=0;i<200;++i){auto frame=channel.take();require(frame && frame->pixels.front()==i);}
        producer.join();
        require(channel.put(Frame(7)));
        auto blocked=std::async(std::launch::async,[&]{return channel.put(Frame(8));});
        channel.close();require(!blocked.get());require(!channel.take());
        stereo_rtsp::detail::MoveHandoff<Frame> failed;
        require(failed.put(Frame(1)));
        failed.fail(std::make_exception_ptr(std::runtime_error("fault")));
        bool threw=false;try{(void)failed.take();}catch(const std::runtime_error&){threw=true;}require(threw);
        stereo_rtsp::detail::MoveHandoff<Frame> empty;
        auto waiting=std::async(std::launch::async,[&]{return empty.take();});
        empty.close();require(!waiting.get());
        std::cout<<"move-only address identity, ordered delivery, blocked producer/consumer cancellation and fail-closed passed\n";
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
