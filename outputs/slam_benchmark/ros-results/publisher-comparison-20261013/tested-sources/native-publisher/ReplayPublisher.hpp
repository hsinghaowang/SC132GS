#pragma once
#include <cstdint>
#include <memory>
#include <string>

namespace slam_benchmark {
enum class PublishErrorCode { None, InvalidInput, DiscoveryTimeout, Interrupted, Runtime };
struct PublishError { PublishErrorCode code=PublishErrorCode::None; std::string detail; };
struct ReplayOptions { std::string dataset, output; std::uint64_t maximum_frames=0; };
struct PublishResult { PublishError error; std::uint64_t imu=0, pairs=0; };
// Owns publishers and files; run() publishes historic stamps against CLOCK_MONOTONIC.
// No estimator, camera driver, or detached worker belongs to this role.
class ReplayPublisher final {
public:
  explicit ReplayPublisher(ReplayOptions options);
  ~ReplayPublisher();
  ReplayPublisher(ReplayPublisher&&) noexcept;
  ReplayPublisher& operator=(ReplayPublisher&&) noexcept;
  ReplayPublisher(const ReplayPublisher&)=delete;
  ReplayPublisher& operator=(const ReplayPublisher&)=delete;
  PublishResult run();
private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};
}
