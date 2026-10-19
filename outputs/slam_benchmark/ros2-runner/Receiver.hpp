#pragma once
#include <cstdint>
#include <memory>
#include <string>

namespace slam_benchmark {
enum class ErrorCode { None, InvalidInput, Configuration, Runtime };
struct Error { ErrorCode code = ErrorCode::None; std::string detail; };
struct ReceiverOptions { std::string config; std::string output; std::uint32_t imu_queue_depth=100; };
struct ReceiveResult {
  Error error;
  std::uint64_t imu = 0, left = 0, right = 0, pairs = 0, poses = 0;
};
// Owns the ROS node, estimator and subscriptions. run() blocks until SIGINT/SIGTERM.
// One executor ingests messages; one owned worker serializes all estimator access.
// No detached worker survives run(). High-rate IMU odometry/TF visualization is disabled.
class Receiver final {
public:
  explicit Receiver(ReceiverOptions options);
  ~Receiver();
  Receiver(Receiver&&) noexcept;
  Receiver& operator=(Receiver&&) noexcept;
  Receiver(const Receiver&) = delete;
  Receiver& operator=(const Receiver&) = delete;
  ReceiveResult run();
private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};
}
