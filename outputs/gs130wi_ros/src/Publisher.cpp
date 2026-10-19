#include "gs130wi/Capture.hpp"
#include "gs130wi_ros/msg/imu_batch.hpp"
#include "gs130wi_ros/msg/stereo_metadata.hpp"
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <atomic>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <time.h>

namespace {
std::int64_t clock_ns(clockid_t id) {
    timespec t{};
    if(clock_gettime(id,&t))throw std::runtime_error("clock_gettime failed");
    return std::int64_t(t.tv_sec)*1000000000+t.tv_nsec;
}
// Maps camera host-monotonic reference into ROS system time only. It does not
// map the IMU clock. Fail on a system-clock discontinuity rather than clamp.
class ClockBridge {
    std::int64_t offset_{};
public:
    ClockBridge() {
        const auto before=clock_ns(CLOCK_MONOTONIC);
        const auto realtime=clock_ns(CLOCK_REALTIME);
        const auto after=clock_ns(CLOCK_MONOTONIC);
        if(after-before>1000000)throw std::runtime_error("clock anchor bracket too wide");
        offset_=realtime-(before+(after-before)/2);
    }
    builtin_interfaces::msg::Time stamp(std::uint64_t mono) const {
        const auto before=clock_ns(CLOCK_MONOTONIC);
        const auto realtime=clock_ns(CLOCK_REALTIME);
        const auto after=clock_ns(CLOCK_MONOTONIC);
        if(after-before>1000000 ||
           std::abs(realtime-(before+(after-before)/2)-offset_)>5000000)
            throw std::runtime_error("system clock changed; restart acquisition");
        if(mono>std::uint64_t(INT64_MAX) || offset_<0 ||
           mono>std::uint64_t(INT64_MAX-offset_))throw std::runtime_error("timestamp overflow");
        return rclcpp::Time(std::int64_t(mono)+offset_,RCL_SYSTEM_TIME);
    }
};
class Publisher final : public rclcpp::Node, public gs130wi::Capture::Observer {
    rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr left_,right_;
    rclcpp::Publisher<gs130wi_ros::msg::ImuBatch>::SharedPtr imu_;
    rclcpp::Publisher<gs130wi_ros::msg::StereoMetadata>::SharedPtr metadata_;
    ClockBridge clock_;
    std::string left_id_,right_id_,imu_id_;
    std::uint64_t acquisition_id_{};
public:
    std::atomic<std::uint64_t> samples{},markers{};
    std::atomic<bool> observer_failed{};
    gs130wi::Options options;
    std::uint64_t maximum_frames{};
    Publisher() : Node("gs130wi_publisher") {
        if(get_parameter("use_sim_time").as_bool())throw std::runtime_error("live capture requires system ROS time");
        options.left_device=declare_parameter("left_device",options.left_device);
        options.right_device=declare_parameter("right_device",options.right_device);
        options.imu_device=declare_parameter("imu_device",options.imu_device);
        options.imu_gpiochip=declare_parameter("imu_gpiochip",options.imu_gpiochip);
        const auto line=declare_parameter("imu_line",24);
        if(line<0)throw std::runtime_error("invalid GPIO line");
        options.imu_line=unsigned(line);
        options.downscale=declare_parameter("downscale",1);
        options.ten_bit=declare_parameter("ten_bit",false);
        const auto limit=declare_parameter("maximum_frames",0);
        if(limit<0)throw std::runtime_error("negative frame limit");
        maximum_frames=std::uint64_t(limit);
        left_id_=declare_parameter("left_frame_id",std::string("left_camera_optical_frame"));
        right_id_=declare_parameter("right_frame_id",std::string("right_camera_optical_frame"));
        imu_id_=declare_parameter("imu_frame_id",std::string("imu_link"));
        acquisition_id_=std::uint64_t(clock_ns(CLOCK_REALTIME));
        left_=create_publisher<sensor_msgs::msg::Image>("stereo/left/image_mono",rclcpp::SensorDataQoS());
        right_=create_publisher<sensor_msgs::msg::Image>("stereo/right/image_mono",rclcpp::SensorDataQoS());
        imu_=create_publisher<gs130wi_ros::msg::ImuBatch>("gs130wi/imu_samples",rclcpp::SensorDataQoS().keep_last(64));
        metadata_=create_publisher<gs130wi_ros::msg::StereoMetadata>("stereo/metadata",rclcpp::SensorDataQoS().keep_last(64));
    }
    bool on_imu_batch(const gs130wi::ImuBatch& batch) noexcept override {
        try {
            gs130wi_ros::msg::ImuBatch message;
            message.frame_id=imu_id_;
            message.acquisition_id=acquisition_id_;
            message.host_read_begin_ns=batch.host_read_begin_ns;
            message.host_read_end_ns=batch.host_read_end_ns;
            message.interrupt_time_valid=batch.host_interrupt_ns.has_value();
            message.host_interrupt_ns=batch.host_interrupt_ns.value_or(0);
            message.host_sample_time_validated=false;
            message.frame_association_validated=false;
            message.samples.reserve(batch.samples.size());
            for(const auto& value:batch.samples) {
                gs130wi_ros::msg::ImuSample sample;
                sample.sample_index=value.index;
                sample.valid=value.valid;
                sample.fifo_header=value.fifo_header;
                sample.timestamp_raw=value.timestamp_raw;
                sample.sensor_time_valid=value.sensor_elapsed_ns.has_value();
                sample.sensor_elapsed_ns=value.sensor_elapsed_ns.value_or(0);
                sample.fsync_valid=value.fsync_offset_ns.has_value();
                sample.fsync_offset_ns=value.fsync_offset_ns.value_or(0);
                sample.linear_acceleration.x=value.acceleration_m_s2[0];
                sample.linear_acceleration.y=value.acceleration_m_s2[1];
                sample.linear_acceleration.z=value.acceleration_m_s2[2];
                sample.angular_velocity.x=value.angular_velocity_rad_s[0];
                sample.angular_velocity.y=value.angular_velocity_rad_s[1];
                sample.angular_velocity.z=value.angular_velocity_rad_s[2];
                ++samples;
                if(sample.fsync_valid)++markers;
                message.samples.push_back(sample);
            }
            imu_->publish(message);
            return rclcpp::ok();
        } catch(...) { observer_failed=true; return false; }
    }
    void publish(const gs130wi::StereoFrame& frame) {
        if(get_parameter("use_sim_time").as_bool())throw std::runtime_error("ROS clock mode changed");
        const auto stamp=clock_.stamp(frame.images[0].monotonic_timestamp_ns);
        for(unsigned eye=0;eye<2;++eye) {
            const auto& image=frame.images[eye];
            sensor_msgs::msg::Image message;
            message.header.stamp=stamp;
            message.header.frame_id=eye?right_id_:left_id_;
            message.width=image.width; message.height=image.height;
            message.encoding=image.mono10.empty()?"mono8":"mono16";
            const std::uint16_t endian_probe=1;
            message.is_bigendian=*reinterpret_cast<const std::uint8_t*>(&endian_probe)==0;
            message.step=image.width*(image.mono10.empty()?1:2);
            message.data.resize(std::size_t(message.step)*message.height);
            if(image.mono10.empty())std::memcpy(message.data.data(),image.mono8.data(),message.data.size());
            else std::memcpy(message.data.data(),image.mono10.data(),message.data.size());
            (eye?right_:left_)->publish(message);
        }
        gs130wi_ros::msg::StereoMetadata message;
        message.header.stamp=stamp; message.header.frame_id=left_id_;
        message.acquisition_id=acquisition_id_;
        message.camera_session=frame.synchronization.camera_session;
        message.left_sequence=frame.images[0].sequence; message.right_sequence=frame.images[1].sequence;
        message.monotonic_timestamp_ns=frame.images[0].monotonic_timestamp_ns;
        message.timestamp_source=std::uint8_t(frame.synchronization.source);
        message.timestamp_offset_ns=frame.synchronization.timestamp_offset_ns;
        message.imu_association_validated=false;
        metadata_->publish(message);
    }
};
}
int main(int argc,char** argv) {
    rclcpp::init(argc,argv);
    try {
        auto node=std::make_shared<Publisher>();
        auto opened=gs130wi::Capture::open(node->options,node.get());
        if(const auto* e=std::get_if<gs130wi::Error>(&opened)) {
            RCLCPP_ERROR(node->get_logger(),"capture open failed: code=%d errno=%d device_code=%d",int(e->code),e->system_errno,e->device_code);
            rclcpp::shutdown(); return 1;
        }
        auto capture=std::get<gs130wi::Capture>(std::move(opened));
        std::uint64_t frames=0;
        bool passed=true;
        try {
            while(rclcpp::ok() && (!node->maximum_frames || frames<node->maximum_frames)) {
                auto result=capture.next_frame();
                if(const auto* e=std::get_if<gs130wi::Error>(&result)) {
                    if(rclcpp::ok()) {
                        RCLCPP_ERROR(node->get_logger(),"capture failed: code=%d errno=%d",int(e->code),e->system_errno);
                        passed=false;
                    }
                    break;
                }
                node->publish(std::get<gs130wi::StereoFrame>(result));
                ++frames;
                rclcpp::spin_some(node);
            }
        } catch(const std::exception& e) { RCLCPP_ERROR(node->get_logger(),"publish failed: %s",e.what()); passed=false; }
        if(auto e=capture.stop()) {
            RCLCPP_ERROR(node->get_logger(),"restore failed: code=%d errno=%d",int(e->code),e->system_errno);
            passed=false;
        }
        passed=passed && !node->observer_failed;
        std::cout<<"{\"passed\":"<<(passed?"true":"false")<<",\"frames\":"<<frames
            <<",\"imu_samples\":"<<node->samples<<",\"fsync_packets\":"<<node->markers
            <<",\"frame_association_validated\":false,\"host_sample_time_validated\":false}\n";
        rclcpp::shutdown(); return passed?0:1;
    } catch(const std::exception& e) {
        std::cerr<<e.what()<<'\n'; rclcpp::shutdown(); return 2;
    }
}
