#pragma once
#include <array>
#include <cstdint>
#include <memory>
#include <string>

namespace calibration {
enum class ErrorCode { none, invalid_configuration, camera, storage, queue_full };
struct Error { ErrorCode code=ErrorCode::none; int system_errno=0, eye=-1; };
struct Options {
    std::string first_camera, second_camera, output_directory;
    std::uint32_t seconds=10, select_every_frames=12;
};
struct Progress { std::array<std::uint64_t,2> saved{}; };
struct Result {
    Error error;
    std::array<std::uint64_t,2> captured{}, saved{}, driver_sequence_gaps{};
    std::uint64_t maximum_storage_queue=0;
};
// C++17 API. Owns capture, copied frames and a joined storage worker.
// run() is single-use/single-caller; request_stop() may be called concurrently.
// The optional observer must outlive this object; notifications run on the
// storage thread. They do not replace the synchronous run() result.
class CalibrationCapture final {
public:
    class Observer {
    public:
        virtual ~Observer()=default;
        virtual void on_progress(const Progress&) noexcept=0;
    };
    explicit CalibrationCapture(Options, Observer* = nullptr);
    ~CalibrationCapture();
    CalibrationCapture(CalibrationCapture&&) noexcept;
    CalibrationCapture& operator=(CalibrationCapture&&) noexcept;
    CalibrationCapture(const CalibrationCapture&)=delete;
    CalibrationCapture& operator=(const CalibrationCapture&)=delete;
    Result run() noexcept;
    void request_stop() noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}
