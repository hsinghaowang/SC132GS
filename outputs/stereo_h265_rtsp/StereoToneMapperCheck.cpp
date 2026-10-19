#include "StereoToneMapper.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

namespace {

using Mapper = stereo_rtsp::StereoToneMapper;
using Raw = std::vector<std::uint16_t>;
using Bytes = std::vector<std::uint8_t>;

static_assert(!std::is_copy_constructible<Mapper>::value, "Mapper owns stream history");
static_assert(std::is_nothrow_move_constructible<Mapper>::value, "Mapper supports ownership transfer");

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

Mapper::Result map(Mapper& mapper, const Raw& left, const Raw& right,
                   Bytes& left_y, Bytes& right_y, std::uint64_t timestamp_ns) {
    return mapper.process({left.data(), left.size()}, {right.data(), right.size()},
        {left_y.data(), left_y.size()}, {right_y.data(), right_y.size()}, timestamp_ns);
}

Raw ramp(std::size_t count, unsigned maximum) {
    Raw result(count);
    for (std::size_t i = 0; i < count; ++i)
        result[i] = static_cast<std::uint16_t>(i * maximum / (count - 1));
    return result;
}

unsigned distinct(const Bytes& values) {
    std::array<bool, 256> seen{};
    for (auto value : values) seen[value] = true;
    return static_cast<unsigned>(std::count(seen.begin(), seen.end(), true));
}

void transfer_and_detail() {
    Mapper::Config config;
    config.max_gain = 1.0;
    Mapper mapper(config);
    const auto input = ramp(1024, 1023);
    const auto original = input;
    Bytes left(1024), right(1024);
    const auto result = map(mapper, input, input, left, right, 1);
    require(static_cast<bool>(result), "reference ramp failed");
    require(input == original, "AE input modified by tone mapper");
    require(left == right, "identical eyes must remain identical");
    require(left[0] == 16 && left[1] == 17 && left[2] == 18 && left[3] == 19 &&
        left[4] == 20 && left[184] == 106 && left[512] == 171 && left[1023] == 235,
        "BT.709 references or one-step 10-bit quantization incorrect");
    require(std::is_sorted(left.begin(), left.end()), "reference LUT must be monotonic");
    // Direct >>2 discards distinctions between 0, 1, 2, 3 before video encoding.
    require(left[0] < left[1] && left[1] < left[2] && left[2] < left[3],
        "RAW precision was truncated before video transfer");

    const auto dark = ramp(256, 255);
    Bytes dark_y(256), other_y(256), shifted(256);
    Mapper adaptive;
    const auto adaptive_result = map(adaptive, dark, dark, dark_y, other_y, 1);
    require(static_cast<bool>(adaptive_result) && adaptive_result.frame.applied_gain == 4.0,
        "dark textured frame should use bounded gain");
    for (std::size_t i = 0; i < shifted.size(); ++i)
        shifted[i] = static_cast<std::uint8_t>(dark[i] >> 2);
    require(distinct(dark_y) > distinct(shifted), "dark detail did not improve over >>2");
    require(std::is_sorted(dark_y.begin(), dark_y.end()), "dark LUT wrapped or reversed");
}

void common_mapping_and_highlights() {
    auto dark = ramp(4096, 127);
    auto bright = ramp(4096, 1023);
    dark[1024] = bright[1024] = 100;
    Bytes left(dark.size()), right(dark.size());
    Mapper mapper;
    const auto result = map(mapper, dark, bright, left, right, 1);
    require(static_cast<bool>(result) && result.frame.applied_gain == 1.0,
        "brighter eye must constrain the shared mapping");
    require(left[1024] == right[1024], "same radiance mapped differently across eyes");
    Mapper swapped;
    Bytes swapped_left(dark.size()), swapped_right(dark.size());
    const auto reversed = map(swapped, bright, dark, swapped_left, swapped_right, 1);
    require(static_cast<bool>(reversed) && reversed.frame.applied_gain == result.frame.applied_gain &&
        swapped_left == right && swapped_right == left, "eye ordering changed shared LUT");

    // The sparse bright object lies above P99: it must retain intensity ordering
    // instead of being clipped to the percentile boundary.
    dark[4092] = 256;
    dark[4093] = 512;
    dark[4094] = 768;
    dark[4095] = 1023;
    Mapper sparse;
    const auto sparse_result = map(sparse, dark, dark, left, right, 1);
    require(static_cast<bool>(sparse_result) && sparse_result.frame.applied_gain <= 4.0,
        "sparse highlight mapping failed");
    require(left[4092] < left[4093] && left[4093] < left[4094] &&
        left[4094] < left[4095] && left[4095] == 235,
        "percentile mapping clipped a small bright object");
}

void fallback_and_time() {
    Bytes left(1024), right(1024);
    for (unsigned uniform : {0U, 3U, 300U, 1023U}) {
        Raw flat(1024, static_cast<std::uint16_t>(uniform));
        Mapper mapper;
        const auto result = map(mapper, flat, flat, left, right, 1);
        require(static_cast<bool>(result) && result.frame.fallback &&
            result.frame.applied_gain == 1.0, "uniform frame must use conservative fallback");
        require(left == right && std::all_of(left.begin(), left.end(),
            [&](std::uint8_t value) { return value == left[0]; }),
            "uniform frame output is not uniform");
        if (uniform == 0) require(left[0] == 16, "black level not anchored");
    }
    const auto bright = ramp(1024, 1023);
    const auto dark = ramp(1024, 127);
    Mapper direct, split;
    require(static_cast<bool>(map(direct, bright, bright, left, right, 0)), "time init failed");
    require(static_cast<bool>(map(split, bright, bright, left, right, 0)), "split init failed");
    const auto duplicate = map(direct, dark, dark, left, right, 0);
    require(static_cast<bool>(duplicate) && duplicate.frame.applied_gain == 1.0 &&
        duplicate.frame.lut_revision == 1, "equal timestamp advanced state");
    const auto one_step = map(direct, dark, dark, left, right, 200000000);
    require(static_cast<bool>(map(split, dark, dark, left, right, 100000000)), "split step failed");
    const auto two_steps = map(split, dark, dark, left, right, 200000000);
    require(static_cast<bool>(one_step) && static_cast<bool>(two_steps) &&
        one_step.frame.applied_gain > 1.0 && one_step.frame.applied_gain < 4.0 &&
        std::abs(one_step.frame.applied_gain - two_steps.frame.applied_gain) < 1.0e-12,
        "smoothing must depend on elapsed time rather than frame count");
    const auto before_bright = one_step.frame.applied_gain;
    const auto protect = map(direct, bright, bright, left, right, 280000000);
    require(static_cast<bool>(protect) && protect.frame.applied_gain < before_bright &&
        (protect.frame.applied_gain - 1.0) / (before_bright - 1.0) < 0.4,
        "gain reduction did not use fast response");
    const auto old_revision = protect.frame.lut_revision;
    direct.reset();
    const auto restart = map(direct, dark, dark, left, right, 1);
    require(static_cast<bool>(restart) && restart.frame.applied_gain == 4.0 &&
        restart.frame.lut_revision > old_revision, "reset must clear time and preserve unique revisions");
}

void transactional_errors() {
    auto dark = ramp(1024, 127);
    const auto bright = ramp(1024, 1023);
    Bytes left(1024, 251), right(1024, 252);
    Mapper mapper, reference;
    require(static_cast<bool>(map(mapper, dark, dark, left, right, 100)), "transaction init failed");
    require(static_cast<bool>(map(reference, dark, dark, left, right, 100)), "reference init failed");
    const auto saved_left = left, saved_right = right;
    auto result = mapper.process({dark.data(), dark.size()}, {dark.data(), dark.size()},
        {nullptr, left.size()}, {right.data(), right.size()}, 200);
    require(result.error == Mapper::ErrorCode::invalid_buffer, "null buffer accepted");
    result = mapper.process({dark.data(), dark.size()}, {dark.data(), dark.size()},
        {left.data(), left.size() - 1}, {right.data(), right.size()}, 200);
    require(result.error == Mapper::ErrorCode::invalid_buffer, "mismatched size accepted");
    result = mapper.process({dark.data(), dark.size()}, {dark.data(), dark.size()},
        {left.data(), left.size()}, {left.data(), left.size()}, 200);
    require(result.error == Mapper::ErrorCode::overlapping_buffers, "overlapping outputs accepted");
    const auto original = dark;
    result = mapper.process({dark.data(), dark.size()}, {dark.data(), dark.size()},
        {reinterpret_cast<std::uint8_t*>(dark.data()), dark.size()},
        {right.data(), right.size()}, 200);
    require(result.error == Mapper::ErrorCode::overlapping_buffers && dark == original,
        "input/output alias modified AE source");
    dark.back() = 1024;
    result = map(mapper, dark, dark, left, right, 200);
    require(result.error == Mapper::ErrorCode::sample_out_of_range, "invalid RAW10 accepted");
    dark = original;
    result = map(mapper, dark, dark, left, right, 99);
    require(result.error == Mapper::ErrorCode::timestamp_regressed, "regressing time accepted");
    require(left == saved_left && right == saved_right, "failed transaction changed outputs");
    const auto after = map(mapper, bright, bright, left, right, 100000100);
    const auto expected = map(reference, bright, bright, left, right, 100000100);
    require(static_cast<bool>(after) && static_cast<bool>(expected) &&
        after.frame.applied_gain == expected.frame.applied_gain &&
        after.frame.lut_revision == expected.frame.lut_revision,
        "failed transaction changed temporal state");
    Mapper::Config invalid_config;
    invalid_config.max_gain = std::numeric_limits<double>::quiet_NaN();
    Mapper invalid(invalid_config);
    require(map(invalid, dark, dark, left, right, 1).error == Mapper::ErrorCode::invalid_config,
        "invalid configuration accepted");
    Mapper moved(std::move(mapper));
    require(map(mapper, dark, dark, left, right, 1).error == Mapper::ErrorCode::moved_from,
        "moved-from state not reported");
    require(static_cast<bool>(map(moved, bright, bright, left, right, 200000100)),
        "move lost valid stream state");
}

} // namespace

int main() {
    try {
        transfer_and_detail();
        common_mapping_and_highlights();
        fallback_and_time();
        transactional_errors();
        std::cout << "Stereo RAW10 tone mapping: transfer, detail, shared LUT, highlights, "
                     "fallback, timing and transactional errors passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Stereo tone mapper check failed: " << error.what() << '\n';
        return 1;
    }
}
