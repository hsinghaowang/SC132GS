#include "CalibrationCapture.hpp"
#include <type_traits>
static_assert(std::is_move_constructible<calibration::CalibrationCapture>::value);
static_assert(!std::is_copy_constructible<calibration::CalibrationCapture>::value);
static_assert(std::is_nothrow_destructible<calibration::CalibrationCapture>::value);
class Client final : public calibration::CalibrationCapture::Observer {
    void on_progress(const calibration::Progress&) noexcept override {}
};
