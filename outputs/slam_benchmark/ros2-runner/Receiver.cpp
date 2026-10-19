#include "Receiver.hpp"
#include "core/VioManager.h"
#include "core/VioManagerOptions.h"
#include "state/State.h"
#include "ros/ROS2Visualizer.h"
#include <csignal>
#include <cmath>
#include <functional>
#include <iostream>
#include <condition_variable>
#include <variant>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <thread>
#include <time.h>

namespace slam_benchmark {
namespace {
volatile std::sig_atomic_t stop_requested = 0;
void stop_handler(int) { stop_requested = 1; }
std::int64_t monotonic_ns() {
  timespec t{}; clock_gettime(CLOCK_MONOTONIC, &t);
  return std::int64_t(t.tv_sec)*1000000000LL+t.tv_nsec;
}
double stamp_seconds(const builtin_interfaces::msg::Time& t) { return t.sec+t.nanosec*1e-9; }
builtin_interfaces::msg::Time stamp(double seconds) {
  const auto ns = std::int64_t(std::llround(seconds*1e9));
  builtin_interfaces::msg::Time t; t.sec=ns/1000000000LL; t.nanosec=ns%1000000000LL; return t;
}
}
struct Receiver::Impl {
  explicit Impl(ReceiverOptions value): options(std::move(value)) {}
  ReceiverOptions options;
  ReceiveResult result;
  std::shared_ptr<rclcpp::Node> node;
  std::shared_ptr<ov_msckf::VioManager> estimator;
  std::unique_ptr<ov_msckf::ROS2Visualizer> visualizer;
  rclcpp::Subscription<sensor_msgs::msg::Imu>::SharedPtr imu_sub;
  std::unique_ptr<message_filters::Subscriber<sensor_msgs::msg::Image>> left_sub, right_sub;
  using SyncPolicy=message_filters::sync_policies::ApproximateTime<sensor_msgs::msg::Image,sensor_msgs::msg::Image>;
  std::unique_ptr<message_filters::Synchronizer<SyncPolicy>> synchronizer;
  rclcpp::Publisher<geometry_msgs::msg::PoseStamped>::SharedPtr pose_pub;
  std::unique_ptr<rclcpp::executors::SingleThreadedExecutor> executor;
  std::ofstream events, trajectory;
  using Measurement=std::variant<ov_core::ImuData,ov_core::CameraData>;
  std::deque<Measurement> incoming;
  std::mutex queue_mutex, event_mutex;
  std::condition_variable queue_ready;
  std::thread worker;
  std::atomic<bool> worker_failed{false};
  bool stopping=false;
  std::size_t maximum_queue=0, abandoned_queue=0;
  double previous_state = -1;
  std::int64_t first_initialized_camera_ns = -1;
  ~Impl() { cleanup(); }
  void stop_worker() {
    { std::lock_guard<std::mutex> lock(queue_mutex); stopping=true; }
    queue_ready.notify_all();
    if(worker.joinable()) worker.join();
  }
  void cleanup() {
    if (executor && node) { executor->cancel(); executor->remove_node(node); }
    stop_worker();
    executor.reset(); synchronizer.reset(); left_sub.reset(); right_sub.reset(); imu_sub.reset();
    visualizer.reset(); pose_pub.reset(); estimator.reset(); node.reset();
  }
  void event(const char* type, double t, std::int64_t begin, std::int64_t end) {
    std::lock_guard<std::mutex> lock(event_mutex);
    events<<type<<','<<t<<','<<begin<<','<<end<<'\n';
  }
  template<class T> void enqueue(T measurement) {
    { std::lock_guard<std::mutex> lock(queue_mutex);
      if(incoming.size()>=4096) throw std::runtime_error("bounded measurement queue overflow");
      incoming.emplace_back(std::move(measurement));maximum_queue=std::max(maximum_queue,incoming.size());
    }
    queue_ready.notify_one();
  }
  void process_measurements() noexcept {
    std::deque<ov_core::CameraData> pending;
    double latest_imu=-1;
    try {
      for(;;) {
        Measurement measurement;
        { std::unique_lock<std::mutex> lock(queue_mutex);
          queue_ready.wait(lock,[this]{return stopping || !incoming.empty();});
          if(stopping) { abandoned_queue=incoming.size()+pending.size();incoming.clear();break; }
          measurement=std::move(incoming.front());incoming.pop_front();
        }
        if(auto* imu=std::get_if<ov_core::ImuData>(&measurement)) {
          const auto begin=monotonic_ns();estimator->feed_measurement_imu(*imu);latest_imu=imu->timestamp;
          event("imu_process",imu->timestamp,begin,monotonic_ns());
        } else {
          pending.push_back(std::move(std::get<ov_core::CameraData>(measurement)));
          std::sort(pending.begin(),pending.end());
        }
        while(!pending.empty() && pending.front().timestamp+estimator->get_state()->_calib_dt_CAMtoIMU->value()(0)<latest_imu) {
          const auto begin=monotonic_ns(); const auto timestamp=pending.front().timestamp;
          estimator->feed_measurement_camera(pending.front());visualizer->visualize();publish_pose();pending.pop_front();
          event("camera_process",timestamp,begin,monotonic_ns());
        }
      }
    } catch(const std::exception& error) { result.error={ErrorCode::Runtime,error.what()};worker_failed=true; }
  }
  void publish_pose() {
    const auto state=estimator->get_state();
    if (!estimator->initialized() || state->_timestamp<=previous_state) return;
    previous_state=state->_timestamp;
    const auto p=state->_imu->pos();
    const Eigen::Quaterniond q(state->_imu->Rot().transpose());
    if (!p.allFinite() || !q.coeffs().allFinite()) throw std::runtime_error("nonfinite pose");
    const auto end=monotonic_ns();
    if (first_initialized_camera_ns<0) first_initialized_camera_ns=std::llround(previous_state*1e9);
    trajectory<<previous_state+state->_calib_dt_CAMtoIMU->value()(0)<<','<<p.x()<<','<<p.y()<<','<<p.z()<<','<<q.w()<<','<<q.x()<<','<<q.y()<<','<<q.z()<<'\n';
    event("pose",previous_state,end,end);
    geometry_msgs::msg::PoseStamped msg;
    // Probe stamp identifies the source CAMERA frame; trajectory uses calibrated IMU time.
    msg.header.stamp=stamp(previous_state); msg.header.frame_id="global";
    msg.pose.position.x=p.x(); msg.pose.position.y=p.y(); msg.pose.position.z=p.z();
    msg.pose.orientation.w=q.w(); msg.pose.orientation.x=q.x(); msg.pose.orientation.y=q.y(); msg.pose.orientation.z=q.z();
    pose_pub->publish(msg); ++result.poses;
  }
  void on_pair(const sensor_msgs::msg::Image::ConstSharedPtr left,const sensor_msgs::msg::Image::ConstSharedPtr right) {
    const auto begin=monotonic_ns(); ++result.pairs;
    ov_core::CameraData camera;camera.timestamp=stamp_seconds(left->header.stamp);camera.sensor_ids={0,1};
    camera.images={cv_bridge::toCvShare(left,"mono8")->image.clone(),cv_bridge::toCvShare(right,"mono8")->image.clone()};
    camera.masks={cv::Mat::zeros(camera.images[0].size(),CV_8UC1),cv::Mat::zeros(camera.images[1].size(),CV_8UC1)};
    enqueue(std::move(camera));
    event("pair",stamp_seconds(left->header.stamp),begin,monotonic_ns());
  }
  ReceiveResult run() {
    if (options.config.empty() || options.output.empty()) return {{ErrorCode::InvalidInput,"config/output required"}};
    try {
      std::filesystem::create_directories(options.output);
      events.open(options.output+"/receiver-events.csv"); trajectory.open(options.output+"/trajectory.csv");
      if (!events || !trajectory) throw std::runtime_error("cannot open evidence files");
      events<<"event,sensor_timestamp,begin_monotonic_ns,end_monotonic_ns\n"<<std::setprecision(17);
      trajectory<<"# timestamp_imu,px,py,pz,qw,qx,qy,qz\n"<<std::setprecision(17);
      node=std::make_shared<rclcpp::Node>("slam_replay_receiver");
      auto parser=std::make_shared<ov_core::YamlParser>(options.config);
      ov_core::Printer::setPrintLevel("WARNING");
      ov_msckf::VioManagerOptions params; params.print_and_load(parser);
      if (!parser->successful()) return {{ErrorCode::Configuration,"YAML parsing failed"}};
      params.use_multi_threading_subs=false; params.use_multi_threading_pubs=false;
      params.record_timing_information=true; params.record_timing_filepath=options.output+"/internal-timing.csv";
      estimator=std::make_shared<ov_msckf::VioManager>(params);
      visualizer=std::make_unique<ov_msckf::ROS2Visualizer>(node,estimator);
      pose_pub=node->create_publisher<geometry_msgs::msg::PoseStamped>("/benchmark/pose_camera",rclcpp::QoS(100).reliable());
      auto imu_qos=rclcpp::SensorDataQoS(); imu_qos.keep_last(options.imu_queue_depth);
      imu_sub=node->create_subscription<sensor_msgs::msg::Imu>("/imu0",imu_qos,[this](sensor_msgs::msg::Imu::SharedPtr msg) {
        const auto begin=monotonic_ns(); ++result.imu;
        ov_core::ImuData imu;imu.timestamp=stamp_seconds(msg->header.stamp);
        imu.wm<<msg->angular_velocity.x,msg->angular_velocity.y,msg->angular_velocity.z;
        imu.am<<msg->linear_acceleration.x,msg->linear_acceleration.y,msg->linear_acceleration.z;
        enqueue(std::move(imu));event("imu",stamp_seconds(msg->header.stamp),begin,monotonic_ns());
      });
      left_sub=std::make_unique<message_filters::Subscriber<sensor_msgs::msg::Image>>(node,"/cam0/image_raw");
      right_sub=std::make_unique<message_filters::Subscriber<sensor_msgs::msg::Image>>(node,"/cam1/image_raw");
      left_sub->registerCallback([this](const sensor_msgs::msg::Image::ConstSharedPtr& msg){ ++result.left; const auto t=monotonic_ns(); event("left",stamp_seconds(msg->header.stamp),t,t); });
      right_sub->registerCallback([this](const sensor_msgs::msg::Image::ConstSharedPtr& msg){ ++result.right; const auto t=monotonic_ns(); event("right",stamp_seconds(msg->header.stamp),t,t); });
      synchronizer=std::make_unique<message_filters::Synchronizer<SyncPolicy>>(SyncPolicy(10),*left_sub,*right_sub);
      synchronizer->registerCallback(std::bind(&Impl::on_pair,this,std::placeholders::_1,std::placeholders::_2));
      executor=std::make_unique<rclcpp::executors::SingleThreadedExecutor>(); executor->add_node(node);
      worker=std::thread([this]{process_measurements();});
      std::cout<<"RECEIVER_READY"<<std::endl;
      while(!stop_requested && !worker_failed && rclcpp::ok()) executor->spin_once(std::chrono::milliseconds(10));
      stop_worker();visualizer->visualize_final(); cleanup(); events.flush(); trajectory.flush();
    } catch(const std::exception& error) { stop_worker(); result.error={ErrorCode::Runtime,error.what()}; cleanup(); }
    std::ofstream summary(options.output+"/receiver-summary.json");
    summary<<"{\"imu_received\":"<<result.imu<<",\"left_received\":"<<result.left<<",\"right_received\":"<<result.right<<",\"pairs_received\":"<<result.pairs<<",\"poses\":"<<result.poses<<",\"first_initialized_camera_ns\":"<<first_initialized_camera_ns<<",\"imu_queue_depth\":"<<options.imu_queue_depth<<",\"maximum_measurement_queue\":"<<maximum_queue<<",\"abandoned_measurements_at_stop\":"<<abandoned_queue<<",\"error_code\":"<<int(result.error.code)<<",\"owned_estimator_worker\":true,\"high_rate_imu_odometry\":false,\"publisher_threading\":false,\"executor\":\"SingleThreadedExecutor\",\"stock_subscriber_main\":false}\n";
    return result;
  }
};
Receiver::Receiver(ReceiverOptions options):impl_(std::make_unique<Impl>(std::move(options))) {}
Receiver::~Receiver()=default;
Receiver::Receiver(Receiver&&) noexcept=default;
Receiver& Receiver::operator=(Receiver&&) noexcept=default;
ReceiveResult Receiver::run() { return impl_->run(); }
}

int main(int argc,char** argv) {
  if(argc!=3) { std::cerr<<"usage: ros_replay_receiver config.yaml output\n"; return 2; }
  rclcpp::init(argc,argv,rclcpp::InitOptions(),rclcpp::SignalHandlerOptions::None);
  std::signal(SIGINT,slam_benchmark::stop_handler); std::signal(SIGTERM,slam_benchmark::stop_handler);
  slam_benchmark::ReceiveResult result;
  { slam_benchmark::Receiver receiver({argv[1],argv[2]}); result=receiver.run(); }
  rclcpp::shutdown();
  if(result.error.code!=slam_benchmark::ErrorCode::None) std::cerr<<"RECEIVER_ERROR "<<int(result.error.code)<<": "<<result.error.detail<<'\n';
  return result.error.code==slam_benchmark::ErrorCode::None?0:1;
}
