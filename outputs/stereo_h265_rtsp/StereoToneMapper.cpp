#include "StereoToneMapper.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>

namespace stereo_rtsp {
namespace {

using Histogram = std::array<std::size_t, 1024>;
using Lut = std::array<std::uint8_t, 1024>;

bool valid_config(const StereoToneMapper::Config& config) noexcept {
    return std::isfinite(config.max_gain) && config.max_gain >= 1.0 &&
        config.max_gain <= 16.0 && std::isfinite(config.upper_percentile) &&
        config.upper_percentile > 0.5 && config.upper_percentile <= 1.0 &&
        std::isfinite(config.target_highlight) && config.target_highlight > 0.0 &&
        config.target_highlight < 1.0 && config.minimum_span > 0 &&
        config.minimum_span <= 1023 && std::isfinite(config.bright_response_ms) &&
        config.bright_response_ms > 0.0 && std::isfinite(config.dark_response_ms) &&
        config.dark_response_ms > 0.0;
}

struct ByteRange {
    std::uintptr_t begin{};
    std::uintptr_t end{};
};

bool range(const void* data, std::size_t bytes, ByteRange& result) noexcept {
    result.begin = reinterpret_cast<std::uintptr_t>(data);
    if (!data || bytes > std::numeric_limits<std::uintptr_t>::max() - result.begin)
        return false;
    result.end = result.begin + bytes;
    return true;
}

bool overlaps(ByteRange a, ByteRange b) noexcept {
    return a.begin < b.end && b.begin < a.end;
}

std::uint16_t percentile(const Histogram& histogram, std::size_t count,
                         double fraction) noexcept {
    const auto rank = std::max<std::size_t>(1, static_cast<std::size_t>(
        std::ceil(fraction * static_cast<double>(count))));
    std::size_t accumulated = 0;
    for (std::size_t code = 0; code < histogram.size(); ++code) {
        accumulated += histogram[code];
        if (accumulated >= rank) return static_cast<std::uint16_t>(code);
    }
    return 1023;
}

Lut make_lut(double gain) noexcept {
    Lut result{};
    for (std::size_t code = 0; code < result.size(); ++code) {
        const double x = static_cast<double>(code) / 1023.0;
        // Rational shoulder: f(0) = 0, f(1) = 1, f'(x) <= gain.
        // Percentiles adjust gain only; small bright objects are never clipped
        // at a percentile boundary. Keep floating precision until final Y'.
        const double mapped = gain * x / (1.0 + (gain - 1.0) * x);
        const double encoded = mapped < 0.018 ? 4.5 * mapped :
            1.099 * std::pow(mapped, 0.45) - 0.099;
        result[code] = static_cast<std::uint8_t>(
            std::clamp(std::lround(16.0 + 219.0 * encoded), 16L, 235L));
    }
    return result;
}

} // namespace

struct StereoToneMapper::Impl {
    explicit Impl(Config settings) : config(settings) {}
    Config config;
    Lut lut{};
    double gain{1.0};
    std::uint64_t last_timestamp_ns{};
    std::uint64_t revision{};
    bool initialized{};
};

StereoToneMapper::StereoToneMapper() : StereoToneMapper(Config{}) {}
StereoToneMapper::StereoToneMapper(Config config)
    : impl_(std::make_unique<Impl>(config)) {}
StereoToneMapper::~StereoToneMapper() = default;
StereoToneMapper::StereoToneMapper(StereoToneMapper&&) noexcept = default;
StereoToneMapper& StereoToneMapper::operator=(StereoToneMapper&&) noexcept = default;

StereoToneMapper::Result StereoToneMapper::process(
    Input left, Input right, Output left_y, Output right_y,
    std::uint64_t timestamp_ns) noexcept {
    if (!impl_) return {ErrorCode::moved_from, {}};
    auto& state = *impl_;
    if (!valid_config(state.config)) return {ErrorCode::invalid_config, {}};
    const auto count = left.size;
    if (!count || right.size != count || left_y.size != count || right_y.size != count ||
        count > std::numeric_limits<std::size_t>::max() / sizeof(std::uint16_t))
        return {ErrorCode::invalid_buffer, {}};
    ByteRange left_range, right_range, left_output, right_output;
    if (!range(left.data, count * sizeof(std::uint16_t), left_range) ||
        !range(right.data, count * sizeof(std::uint16_t), right_range) ||
        !range(left_y.data, count, left_output) || !range(right_y.data, count, right_output))
        return {ErrorCode::invalid_buffer, {}};
    if (overlaps(left_output, right_output) || overlaps(left_output, left_range) ||
        overlaps(left_output, right_range) || overlaps(right_output, left_range) ||
        overlaps(right_output, right_range)) return {ErrorCode::overlapping_buffers, {}};
    if (state.initialized && timestamp_ns < state.last_timestamp_ns)
        return {ErrorCode::timestamp_regressed, {}};

    Histogram left_histogram{}, right_histogram{};
    for (std::size_t i = 0; i < count; ++i) {
        if (left.data[i] > 1023 || right.data[i] > 1023)
            return {ErrorCode::sample_out_of_range, {}};
        ++left_histogram[left.data[i]];
        ++right_histogram[right.data[i]];
    }

    const auto& config = state.config;
    const auto left_high = percentile(left_histogram, count, config.upper_percentile);
    const auto right_high = percentile(right_histogram, count, config.upper_percentile);
    const auto left_low = percentile(left_histogram, count, 1.0 - config.upper_percentile);
    const auto right_low = percentile(right_histogram, count, 1.0 - config.upper_percentile);
    const auto high = std::max(left_high, right_high);
    const auto span = std::max(left_high - left_low, right_high - right_low);
    const bool fallback = high < config.minimum_span || span < config.minimum_span;
    double requested_gain = 1.0;
    if (!fallback && high != 0) {
        const double reference = static_cast<double>(high) / 1023.0;
        // Solve f(reference) = target for gain. A brighter eye constrains both
        // eyes; independently stretching their histograms would destroy parity.
        requested_gain = std::clamp(config.target_highlight * (1.0 - reference) /
            (reference * (1.0 - config.target_highlight)), 1.0, config.max_gain);
    }
    double gain = requested_gain;
    if (state.initialized) {
        const double dt_ms = static_cast<double>(timestamp_ns - state.last_timestamp_ns) / 1.0e6;
        const double tau_ms = requested_gain < state.gain ?
            config.bright_response_ms : config.dark_response_ms;
        const double alpha = -std::expm1(-dt_ms / tau_ms);
        gain = std::clamp(state.gain + alpha * (requested_gain - state.gain),
                          1.0, config.max_gain);
    }
    const Lut lut = state.initialized && gain == state.gain ? state.lut : make_lut(gain);
    const auto revision = state.revision + (!state.initialized || lut != state.lut ? 1 : 0);

    // All validation and state preparation are complete before any writes.
    // The immutable local LUT is used for the whole pair.
    for (std::size_t i = 0; i < count; ++i) {
        left_y.data[i] = lut[left.data[i]];
        right_y.data[i] = lut[right.data[i]];
    }
    state.lut = lut;
    state.gain = gain;
    state.last_timestamp_ns = timestamp_ns;
    state.revision = revision;
    state.initialized = true;
    return {ErrorCode::none,
        {revision, timestamp_ns, gain, requested_gain, left_high, right_high, fallback}};
}

void StereoToneMapper::reset() noexcept {
    if (impl_) {
        impl_->initialized = false;
        impl_->gain = 1.0;
        impl_->last_timestamp_ns = 0;
    }
}

} // namespace stereo_rtsp
