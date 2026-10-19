#include "ReplayPublisher.hpp"
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <sensor_msgs/msg/imu.hpp>
#include <opencv2/imgcodecs.hpp>
#include <algorithm>
#include <array>
#include <cerrno>
#include <cmath>
#include <csignal>
#include <condition_variable>
#include <deque>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <sys/resource.h>
#include <thread>
#include <time.h>
#include <vector>

namespace slam_benchmark {
namespace {
volatile std::sig_atomic_t stopping=0;
void stop_handler(int) { stopping=1; }
std::int64_t now_ns() {
  timespec t{};
  if(clock_gettime(CLOCK_MONOTONIC,&t)) throw std::runtime_error("monotonic clock failed");
  return std::int64_t(t.tv_sec)*1000000000LL+t.tv_nsec;
}
void sleep_until(std::int64_t due) {
  timespec t{due/1000000000LL,due%1000000000LL};
  int error;
  do { error=clock_nanosleep(CLOCK_MONOTONIC,TIMER_ABSTIME,&t,nullptr); }
  while(error==EINTR && !stopping);
  if(error && error!=EINTR) throw std::runtime_error("monotonic sleep failed");
}
void stamp(std_msgs::msg::Header& header,std::int64_t ns,const char* frame) {
  header.stamp.sec=ns/1000000000LL;header.stamp.nanosec=ns%1000000000LL;header.frame_id=frame;
}
std::vector<std::vector<std::string>> read_csv(const std::filesystem::path& path) {
  std::ifstream file(path);
  if(!file) throw std::invalid_argument("cannot open dataset CSV: "+path.string());
  std::vector<std::vector<std::string>> rows;
  std::string line;
  while(std::getline(file,line)) {
    if(line.empty() || line.front()=='#') continue;
    if(line.back()=='\r') line.pop_back();
    std::vector<std::string> row;std::stringstream stream(line);std::string cell;
    while(std::getline(stream,cell,',')) row.push_back(cell);
    rows.push_back(std::move(row));
  }
  return rows;
}
struct Pair { std::int64_t ns;std::array<std::string,2> names; };
struct Imu { std::int64_t ns;std::array<double,6> values; };
struct Event { std::int64_t ns;int kind;std::size_t index; };
struct PreparedPair {
  std::size_t index=0;
  std::array<cv::Mat,2> images;
  std::array<std::int64_t,2> begin{},end{};
};
PreparedPair prepare_pair(const std::filesystem::path& dataset,const Pair& pair,std::size_t index) {
  PreparedPair value;value.index=index;
  for(int eye=0;eye<2;++eye) {
    value.begin[eye]=now_ns();
    value.images[eye]=cv::imread((dataset/("cam"+std::to_string(eye))/"data"/pair.names[eye]).string(),cv::IMREAD_GRAYSCALE);
    value.end[eye]=now_ns();
    const auto& image=value.images[eye];
    if(image.rows!=480 || image.cols!=752 || image.type()!=CV_8UC1 || !image.isContinuous()) throw std::invalid_argument("invalid EuRoC grayscale image");
  }
  return value;
}
// Lower-level producer knows only dataset images and a bounded queue, never ROS.
// Its injected pair sequence outlives it; destructor always wakes and joins its worker.
class ImagePreparer final {
public:
  ImagePreparer(const std::vector<Pair>& pairs,std::filesystem::path dataset,std::size_t capacity)
    :pairs_(pairs),dataset_(std::move(dataset)),capacity_(capacity),worker_([this]{produce();}) {}
  ~ImagePreparer() {
    {std::lock_guard<std::mutex> lock(mutex_);closed_=true;}
    changed_.notify_all();if(worker_.joinable()) worker_.join();
  }
  ImagePreparer(const ImagePreparer&)=delete;
  ImagePreparer& operator=(const ImagePreparer&)=delete;
  ImagePreparer(ImagePreparer&&)=delete; // Worker binds this address; owner moves its PIMPL instead.
  ImagePreparer& operator=(ImagePreparer&&)=delete;
  void prime() {
    std::unique_lock<std::mutex> lock(mutex_);
    while(queue_.size()<std::min(capacity_,pairs_.size()) && !failure_ && !finished_) {
      if(stopping) throw PublishError{PublishErrorCode::Interrupted,"stopped during image preparation"};
      changed_.wait_for(lock,std::chrono::milliseconds(50));
    }
    if(failure_) std::rethrow_exception(failure_);
  }
  PreparedPair take(std::size_t expected) {
    std::unique_lock<std::mutex> lock(mutex_);
    while(queue_.empty() && !failure_ && !finished_) {
      if(stopping) throw PublishError{PublishErrorCode::Interrupted,"stopped waiting for prepared image"};
      changed_.wait_for(lock,std::chrono::milliseconds(50));
    }
    if(failure_) std::rethrow_exception(failure_);
    if(queue_.empty() || queue_.front().index!=expected) throw std::runtime_error("prepared image sequence mismatch");
    auto value=std::move(queue_.front());queue_.pop_front();lock.unlock();changed_.notify_all();return value;
  }
  std::size_t maximum_queue() {
    std::lock_guard<std::mutex> lock(mutex_);return maximum_;
  }
private:
  void produce() noexcept {
    try {
      for(std::size_t i=0;i<pairs_.size();++i) {
        {std::unique_lock<std::mutex> lock(mutex_);changed_.wait(lock,[this]{return closed_ || queue_.size()<capacity_;});if(closed_) return;}
        auto prepared=prepare_pair(dataset_,pairs_[i],i);
        {std::lock_guard<std::mutex> lock(mutex_);if(closed_) return;queue_.push_back(std::move(prepared));maximum_=std::max(maximum_,queue_.size());}
        changed_.notify_all();
      }
      {std::lock_guard<std::mutex> lock(mutex_);finished_=true;}changed_.notify_all();
    } catch(...) {
      {std::lock_guard<std::mutex> lock(mutex_);failure_=std::current_exception();}changed_.notify_all();
    }
  }
  const std::vector<Pair>& pairs_;
  const std::filesystem::path dataset_;
  const std::size_t capacity_;
  std::mutex mutex_;std::condition_variable changed_;
  std::deque<PreparedPair> queue_;
  std::exception_ptr failure_;
  bool closed_=false,finished_=false;
  std::size_t maximum_=0;
  std::thread worker_;
};
}
struct ReplayPublisher::Impl {
  explicit Impl(ReplayOptions value):options(std::move(value)) {}
  ReplayOptions options;
  std::shared_ptr<rclcpp::Node> node;
  std::array<rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr,2> images;
  rclcpp::Publisher<sensor_msgs::msg::Imu>::SharedPtr imu;
  PublishResult result;
  PublishResult run() {
    const auto wrapper_start=now_ns();std::int64_t start=0,origin=0;
    std::uint64_t pair_total=0,imu_total=0;
    std::size_t maximum_prepared_queue=0;
    try {
      const std::filesystem::path dataset(options.dataset),output(options.output);
      if(!std::filesystem::is_directory(output)) throw std::invalid_argument("output directory must exist");
      if(options.prefetch_pairs>32) throw std::invalid_argument("prefetch limit must be 0..32");
      if(std::filesystem::exists(output/"native-publisher-summary.json") || std::filesystem::exists(output/"publish-events.csv") || std::filesystem::exists(output/"publisher-stages.csv")) {
        result.error={PublishErrorCode::InvalidInput,"refuse to overwrite publisher evidence"};return result;
      }
      const auto a=read_csv(dataset/"cam0/data.csv"),b=read_csv(dataset/"cam1/data.csv"),c=read_csv(dataset/"imu0/data.csv");
      if(a.empty() || a.size()!=b.size()) throw std::invalid_argument("stereo CSV size mismatch");
      std::vector<Pair> pairs;std::vector<Imu> measurements;
      for(std::size_t i=0;i<a.size();++i) {
        if(a[i].size()!=2 || b[i].size()!=2 || a[i][0]!=b[i][0]) throw std::invalid_argument("stereo timestamp mismatch");
        if(options.maximum_frames && i>=options.maximum_frames) break;
        pairs.push_back({std::stoll(a[i][0]),{a[i][1],b[i][1]}});
      }
      for(const auto& row:c) {
        if(row.size()!=7) throw std::invalid_argument("invalid IMU row");
        Imu value{std::stoll(row[0]),{}};
        if(options.maximum_frames && value.ns>pairs.back().ns+20000000LL) break;
        for(int k=0;k<6;++k) {
          value.values[k]=std::stod(row[k+1]);
          if(!std::isfinite(value.values[k])) throw std::invalid_argument("nonfinite IMU value");
        }
        measurements.push_back(value);
      }
      pair_total=pairs.size();imu_total=measurements.size();origin=pairs.front().ns;
      std::vector<Event> schedule;
      for(std::size_t i=0;i<measurements.size();++i) schedule.push_back({measurements[i].ns,0,i});
      for(std::size_t i=0;i<pairs.size();++i) schedule.push_back({pairs[i].ns,1,i});
      std::sort(schedule.begin(),schedule.end(),[](const Event& x,const Event& y){return x.ns!=y.ns?x.ns<y.ns:x.kind!=y.kind?x.kind<y.kind:x.index<y.index;});
      cv::setNumThreads(1);
      node=std::make_shared<rclcpp::Node>("euroc_native_publisher");
      for(int eye=0;eye<2;++eye) images[eye]=node->create_publisher<sensor_msgs::msg::Image>("/cam"+std::to_string(eye)+"/image_raw",rclcpp::QoS(10).reliable());
      imu=node->create_publisher<sensor_msgs::msg::Imu>("/imu0",rclcpp::QoS(200).best_effort());
      const auto deadline=now_ns()+30000000000LL;
      while(!images[0]->get_subscription_count() || !images[1]->get_subscription_count() || !imu->get_subscription_count()) {
        if(stopping) throw PublishError{PublishErrorCode::Interrupted,"stopped during discovery"};
        if(now_ns()>deadline) throw PublishError{PublishErrorCode::DiscoveryTimeout,"input subscriber discovery timed out"};
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(500));
      const auto events_path=output/"publish-events.csv",stages_path=output/"publisher-stages.csv";
      if(std::filesystem::exists(events_path) || std::filesystem::exists(stages_path)) throw std::invalid_argument("refuse to overwrite publisher evidence");
      std::ofstream events(events_path),stages(stages_path);
      events.exceptions(std::ios::badbit|std::ios::failbit);stages.exceptions(std::ios::badbit|std::ios::failbit);
      events<<"event,index,sensor_timestamp_ns,scheduled_monotonic_ns,begin_monotonic_ns,end_monotonic_ns\n";
      stages<<"index,eye,sensor_timestamp_ns,load_begin_ns,load_end_ns,construction_begin_ns,message_ready_ns,publish_end_ns\n";
      // Declared after the pair sequence and files: joined before either can be destroyed.
      std::unique_ptr<ImagePreparer> preparer;
      if(options.prefetch_pairs) {
        preparer=std::make_unique<ImagePreparer>(pairs,dataset,options.prefetch_pairs);preparer->prime();
      }
      start=now_ns();std::cout<<"NATIVE_PUBLISHER_READY"<<std::endl;
      for(const auto& event:schedule) {
        const auto due=start+event.ns-origin;
        if(due>now_ns()) sleep_until(due);
        if(stopping) throw PublishError{PublishErrorCode::Interrupted,"stopped during replay"};
        const auto begin=now_ns();
        if(event.kind==0) {
          const auto& source=measurements[event.index];sensor_msgs::msg::Imu msg;stamp(msg.header,event.ns,"imu0");
          msg.angular_velocity.x=source.values[0];msg.angular_velocity.y=source.values[1];msg.angular_velocity.z=source.values[2];
          msg.linear_acceleration.x=source.values[3];msg.linear_acceleration.y=source.values[4];msg.linear_acceleration.z=source.values[5];
          imu->publish(msg);++result.imu;
        } else {
          auto prepared=preparer?preparer->take(event.index):prepare_pair(dataset,pairs[event.index],event.index);
          for(int eye=0;eye<2;++eye) {
            const auto& image=prepared.images[eye];const auto construction_begin=now_ns();
            sensor_msgs::msg::Image msg;stamp(msg.header,event.ns,eye?"cam1":"cam0");
            msg.height=image.rows;msg.width=image.cols;msg.encoding="mono8";msg.is_bigendian=0;msg.step=image.cols;
            msg.data.assign(image.data,image.data+image.total());
            const auto ready=now_ns();images[eye]->publish(msg);
            stages<<event.index<<','<<eye<<','<<event.ns<<','<<prepared.begin[eye]<<','<<prepared.end[eye]<<','<<construction_begin<<','<<ready<<','<<now_ns()<<'\n';
          }
          ++result.pairs;
        }
        events<<(event.kind?"pair":"imu")<<','<<event.index<<','<<event.ns<<','<<due<<','<<begin<<','<<now_ns()<<'\n';
        if(event.kind && event.index && event.index%400==0) std::cout<<"PUBLISH_PROGRESS pairs="<<event.index+1<<std::endl;
      }
      events.flush();stages.flush();
      if(preparer) {maximum_prepared_queue=preparer->maximum_queue();preparer.reset();}
      // Keep DDS writers alive while the final best-effort IMU/reliable images drain.
      std::this_thread::sleep_for(std::chrono::seconds(2));
    } catch(const PublishError& error) { result.error=error; }
      catch(const std::invalid_argument& error) { result.error={PublishErrorCode::InvalidInput,error.what()}; }
      catch(const std::exception& error) { result.error={PublishErrorCode::Runtime,error.what()}; }
    imu.reset();images={};node.reset();
    rusage usage{};getrusage(RUSAGE_SELF,&usage);
    const double cpu=usage.ru_utime.tv_sec+usage.ru_utime.tv_usec*1e-6+usage.ru_stime.tv_sec+usage.ru_stime.tv_usec*1e-6;
    std::ofstream summary(std::filesystem::path(options.output)/"native-publisher-summary.json");
    summary<<std::setprecision(17)<<"{\"sent\":{\"imu\":"<<result.imu<<",\"left\":"<<result.pairs<<",\"right\":"<<result.pairs<<"},\"dataset_stereo_pairs\":"<<pair_total<<",\"dataset_imu_samples\":"<<imu_total<<",\"origin_camera_timestamp_ns\":"<<origin<<",\"start_monotonic_ns\":"<<start<<",\"prefetch_pairs\":"<<options.prefetch_pairs<<",\"maximum_prepared_queue\":"<<maximum_prepared_queue<<",\"error_code\":"<<int(result.error.code)<<",\"cpu_seconds\":"<<cpu<<",\"peak_rss_mib\":"<<usage.ru_maxrss/1024.0<<",\"elapsed_s\":"<<(now_ns()-wrapper_start)*1e-9<<"}\n";
    return result;
  }
};
ReplayPublisher::ReplayPublisher(ReplayOptions options):impl_(std::make_unique<Impl>(std::move(options))) {}
ReplayPublisher::~ReplayPublisher()=default;
ReplayPublisher::ReplayPublisher(ReplayPublisher&&) noexcept=default;
ReplayPublisher& ReplayPublisher::operator=(ReplayPublisher&&) noexcept=default;
PublishResult ReplayPublisher::run() { return impl_->run(); }
}
int main(int argc,char** argv) {
  if(argc<3 || argc>5) {std::cerr<<"usage: native_replay_publisher dataset/mav0 output [maximum_frames] [prefetch_pairs]\n";return 2;}
  slam_benchmark::ReplayOptions options{argv[1],argv[2],0};
  try {
    if(argc>=4) options.maximum_frames=std::stoull(argv[3]);
    if(argc==5) {const auto depth=std::stoull(argv[4]);if(depth>32) throw std::invalid_argument("prefetch limit");options.prefetch_pairs=depth;}
  }
  catch(const std::exception&) {std::cerr<<"invalid maximum_frames\n";return 2;}
  rclcpp::init(argc,argv,rclcpp::InitOptions(),rclcpp::SignalHandlerOptions::None);
  std::signal(SIGINT,slam_benchmark::stop_handler);std::signal(SIGTERM,slam_benchmark::stop_handler);
  slam_benchmark::PublishResult result;
  {slam_benchmark::ReplayPublisher publisher(std::move(options));result=publisher.run();}
  rclcpp::shutdown();
  if(result.error.code!=slam_benchmark::PublishErrorCode::None) std::cerr<<"PUBLISHER_ERROR "<<int(result.error.code)<<": "<<result.error.detail<<'\n';
  return result.error.code==slam_benchmark::PublishErrorCode::None?0:1;
}
