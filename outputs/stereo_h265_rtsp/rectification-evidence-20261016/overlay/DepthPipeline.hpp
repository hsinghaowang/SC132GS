#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
namespace stereo_rtsp::detail {
enum class DepthStage { initialization, input, matching, encoding, internal };
struct DepthError {DepthStage stage;int native_code{};};
struct DepthAccessUnit {
    const std::uint8_t* data{};std::size_t bytes{};
    std::uint64_t source_timestamp_ns{};bool keyframe{};
};
struct DepthStatistics {std::uint64_t submitted{},processed{},replaced{},busy{};bool failed{};};
enum class DepthSubmission { accepted, replaced, busy, disabled, geometry };
// Private asynchronous consumer. Copies borrowed input into one bounded slot.
class DepthPipeline final {
public:
    class Observer {
    public:
        virtual ~Observer()=default;
        // Encoder callback thread; access-unit bytes expire on return.
        virtual void on_depth_access_unit(const DepthAccessUnit&)noexcept=0;
        virtual void on_depth_error(DepthError)noexcept=0;
    };
    DepthPipeline(std::string calibration_directory,Observer&);
    ~DepthPipeline();
    DepthPipeline(DepthPipeline&&)noexcept;
    DepthPipeline& operator=(DepthPipeline&&)noexcept;
    DepthPipeline(const DepthPipeline&)=delete;
    DepthPipeline& operator=(const DepthPipeline&)=delete;
    DepthSubmission submit(const std::uint16_t* cam0,const std::uint16_t* cam1,
        std::size_t pixels_per_eye,std::uint64_t timestamp_ns)noexcept;
    void request_keyframe()noexcept;
    void stop()noexcept; // Joins matching and encoder callbacks before returning.
    DepthStatistics statistics()const noexcept;
private:struct Impl;std::unique_ptr<Impl> impl_;
};
}
