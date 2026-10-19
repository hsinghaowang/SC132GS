#include "BayerLuma.hpp"
#include "ImageProcessingPlan.hpp"
#include "SensorSignalCalibration.hpp"
#include "StereoComposeNV12.hpp"
#include "StereoToneMapper.hpp"
#include "sc132gs-linear-ae-policy.hpp"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {

namespace ae = sc132gs::linear_ae;
using Raw = std::vector<std::uint16_t>;
using Bytes = std::vector<std::uint8_t>;
using Mapper = stereo_rtsp::StereoToneMapper;
constexpr int width = 64;
constexpr int height = 64;
constexpr int stride = width * 5 / 4 + 8; // Padding is deliberately nonzero.
constexpr std::size_t count = static_cast<std::size_t>(width) * height;

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

Bytes pack(const Raw& pixels) {
    Bytes bytes(static_cast<std::size_t>(stride) * height, 255);
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; x += 4) {
            auto* group = bytes.data() + static_cast<std::size_t>(y) * stride + x / 4 * 5;
            group[4] = 0;
            for (unsigned phase = 0; phase < 4; ++phase) {
                const auto code = pixels[static_cast<std::size_t>(y) * width + x + phase];
                group[phase] = static_cast<std::uint8_t>(code >> 2);
                group[4] |= static_cast<std::uint8_t>((code & 3) << (2 * phase));
            }
        }
    }
    return bytes;
}

Raw scene(bool border_highlights) {
    stereo_rtsp::detail::SensorSignalCalibration calibration(false);
    Raw pixels(count);
    for (int y = 0; y < height; ++y)
        for (int x = 0; x < width; ++x)
            pixels[static_cast<std::size_t>(y) * width + x] = static_cast<std::uint16_t>(
                calibration.black_level() + x / 8 + (y >= 32 ? 32 : 0));
    // Only 24 red CFA samples at the top border saturate: 0.586% of one
    // complete eye, but < 0.5% if incorrectly averaged across both eyes.
    if (border_highlights)
        for (unsigned x = 0; x < 48; x += 2) pixels[x] = 1023;
    return pixels;
}

// Test input for the production Policy. Sensor I/O and the controller's
// observation cadence are intentionally outside this portable signal test.
int median(Raw pixels) {
    const auto middle = pixels.begin() + static_cast<std::ptrdiff_t>((pixels.size() - 1) / 2);
    std::nth_element(pixels.begin(), middle, pixels.end());
    return *middle;
}

bool same_highlights(ae::HighlightStatistics a, ae::HighlightStatistics b) {
    return a.sample_count == b.sample_count &&
        a.near_saturated_count == b.near_saturated_count && a.valid == b.valid;
}

bool same_decision(const ae::Decision& a, const ae::Decision& b) {
    return a.exposure.rows == b.exposure.rows && a.exposure.gain == b.exposure.gain &&
        a.brightness_limited == b.brightness_limited && a.highlight_limited == b.highlight_limited &&
        a.constraint == b.constraint && a.effective_target_luma10 == b.effective_target_luma10 &&
        a.highlight_darkening_ev_x100 == b.highlight_darkening_ev_x100;
}

struct Observation {
    ae::Measurements measured;
    ae::Decision decision;
};
struct Run {
    std::vector<Observation> observations;
    Bytes first_left_y, first_right_y, first_nv12;
    Raw first_left10, first_right10;
};

Run run(bool shared_y8, double maximum_gain) {
    stereo_rtsp::Settings settings;
    settings.main10 = !shared_y8;
    settings.shared_tone_map = shared_y8;
    settings.capture_api = true;
    settings.depth_calibration = "synthetic-profile";
    const auto planned = stereo_rtsp::detail::image_processing_plan(settings);
    const auto* plan = std::get_if<stereo_rtsp::detail::ImageProcessingPlan>(&planned);
    require(plan && plan->capture10 && plan->sensor_signal && plan->shared_y8 == shared_y8,
        "encoder choice changed capture/AE precision or calibration");
    stereo_rtsp::detail::BayerLuma left_converter(width, height), right_converter(width, height);
    stereo_rtsp::detail::SensorSignalCalibration calibration(false);
    Mapper::Config tone_config;
    tone_config.max_gain = maximum_gain;
    Mapper mapper(tone_config);
    ae::Policy pre_tone_policy, post_tone_policy;
    ae::Exposure current{200, 8};
    const ae::Settings ae_settings{};
    const ae::Limits limits{};
    Run result;
    for (unsigned frame = 0; frame < 7; ++frame) {
        const bool clipped = frame < 3;
        auto left_packed = pack(scene(clipped));
        auto right_packed = pack(scene(false));
        const auto saved_left_packed = left_packed, saved_right_packed = right_packed;
        const auto left_highlights = ae::measure_packed_raw10(
            left_packed.data(), left_packed.size(), width, height, stride);
        const auto right_highlights = ae::measure_packed_raw10(
            right_packed.data(), right_packed.size(), width, height, stride);
        require(left_highlights.valid && right_highlights.valid &&
            left_highlights.sample_count == count && right_highlights.sample_count == count &&
            left_highlights.near_saturated_count == (clipped ? 24U : 0U) &&
            right_highlights.near_saturated_count == 0,
            "full-RAW statistics missed CFA border samples or counted stride padding");
        Raw left10(count), right10(count);
        left_converter.convert10(left_packed, stride, left10, 1);
        right_converter.convert10(right_packed, stride, right10, 1);
        if (clipped) {
            require(ae::saturation_bp(left_highlights) > ae_settings.saturation_limit_bp &&
                ae::measure_highlights10(left10.data(), left10.size()).near_saturated_count == 0,
                "fixture must expose RAW clipping hidden by grayscale reconstruction");
        }
        using CalibrationCode = stereo_rtsp::detail::SensorSignalCalibration::ErrorCode;
        require(calibration.apply(left10.data(), left10.size()) == CalibrationCode::none &&
            calibration.apply(right10.data(), right10.size()) == CalibrationCode::none,
            "signal calibration failed");
        const auto saved_left10 = left10, saved_right10 = right10;
        const ae::Measurements before{median(left10), median(right10), left_highlights, right_highlights};
        const auto decision = pre_tone_policy.decide(ae_settings, limits, current, before);

        if (plan->shared_y8) {
            Bytes left_y(count), right_y(count);
            const auto mapped = mapper.process({left10.data(), count}, {right10.data(), count},
                {left_y.data(), count}, {right_y.data(), count}, frame * 33333333ULL);
            require(static_cast<bool>(mapped), "shared tone map failed");
            require(mapped.frame.applied_gain >= 1 && mapped.frame.applied_gain <= maximum_gain,
                "shared gain escaped configured range");
            for (std::size_t i = 0; i < count; ++i) {
                require(left_y[i] >= 16 && left_y[i] <= 235 && right_y[i] >= 16 && right_y[i] <= 235,
                    "final Y' escaped limited range");
                if (left10[i] == right10[i])
                    require(left_y[i] == right_y[i], "one pair used separate eye mappings");
            }
            Bytes nv12(count * 3, 0);
            stereo_rtsp::detail::compose_mirrored_side_by_side_nv12(
                left_y.data(), right_y.data(), nv12.data(), width, height);
            for (int y = 0; y < height; ++y) {
                for (int x = 0; x < width; ++x) {
                    const auto eye_index = static_cast<std::size_t>(y) * width + width - 1 - x;
                    const auto output_index = static_cast<std::size_t>(y) * width * 2 + x;
                    require(nv12[output_index] == left_y[eye_index] &&
                        nv12[output_index + width] == right_y[eye_index],
                        "NV12 changed final depth Y' bytes or eye placement");
                }
            }
            require(std::all_of(nv12.begin() + static_cast<std::ptrdiff_t>(count * 2), nv12.end(),
                [](std::uint8_t code) { return code == 128; }), "grayscale NV12 chroma is not neutral");
            if (frame == 0) {
                result.first_left_y = std::move(left_y);
                result.first_right_y = std::move(right_y);
                result.first_nv12 = std::move(nv12);
            }
        }
        require(left10 == saved_left10 && right10 == saved_right10 &&
            left_packed == saved_left_packed && right_packed == saved_right_packed,
            "display/compose path mutated original RAW or AE input");
        const ae::Measurements after{median(left10), median(right10),
            ae::measure_packed_raw10(left_packed.data(), left_packed.size(), width, height, stride),
            ae::measure_packed_raw10(right_packed.data(), right_packed.size(), width, height, stride)};
        require(before.left_median == after.left_median && before.right_median == after.right_median &&
            same_highlights(before.left_highlights, after.left_highlights) &&
            same_highlights(before.right_highlights, after.right_highlights),
            "tone mapping changed AE statistics");
        const auto after_decision = post_tone_policy.decide(ae_settings, limits, current, after);
        require(same_decision(decision, after_decision), "tone mapping changed stateful AE decision");
        if (clipped)
            require(decision.highlight_limited && decision.constraint == ae::Constraint::highlight_tradeoff &&
                decision.effective_target_luma10 <= ae_settings.target_percent * 1023 / 100 &&
                decision.exposure.rows > current.rows,
                "single-eye sparse highlight must apply a bounded body-target tradeoff");
        if (frame == 3 || frame == 4)
            require(decision.highlight_limited, "highlight hold released before settled clean observations");
        if (frame >= 5)
            require(!decision.highlight_limited, "highlight hold failed to release after clean observations");
        result.observations.push_back({before, decision});
        if (frame == 0) {
            result.first_left10 = left10;
            result.first_right10 = right10;
        }
        current = decision.exposure;
    }
    return result;
}

void same_ae(const Run& a, const Run& b) {
    require(a.observations.size() == b.observations.size(), "observation count differs");
    for (std::size_t i = 0; i < a.observations.size(); ++i) {
        const auto& x = a.observations[i];
        const auto& y = b.observations[i];
        require(x.measured.left_median == y.measured.left_median &&
            x.measured.right_median == y.measured.right_median &&
            same_highlights(x.measured.left_highlights, y.measured.left_highlights) &&
            same_highlights(x.measured.right_highlights, y.measured.right_highlights) &&
            same_decision(x.decision, y.decision), "LUT or codec choice changed AE history");
    }
    require(a.first_left10 == b.first_left10 && a.first_right10 == b.first_right10,
        "codec choice changed calibrated 10-bit signal");
}

} // namespace

int main(int argc, char** argv) {
    try {
        require(argc <= 2, "usage: stereo-signal-path-check [output-128x64.nv12]");
        const auto main10 = run(false, 1.0);
        const auto fixed_y8 = run(true, 1.0);
        const auto adaptive_y8 = run(true, 4.0);
        same_ae(main10, fixed_y8);
        same_ae(main10, adaptive_y8);
        require(fixed_y8.first_left_y != adaptive_y8.first_left_y,
            "fixture did not exercise a changed LUT");
        // Constant patches survive demosaic and black correction as 0,1,2,3.
        // Final Y' must distinguish all four; truncating mono10 to mono8 first
        // would collapse them. These are BT.709 reference codes at unity gain.
        for (std::size_t code = 0; code < 4; ++code) {
            const auto position = 4 * static_cast<std::size_t>(width) + code * 8 + 4;
            require(fixed_y8.first_left10[position] == code &&
                fixed_y8.first_left_y[position] == 16 + code,
                "single-quantization path lost low RAW10 bits or applied OETF twice");
        }
        if (argc == 2) {
            std::ofstream output(argv[1], std::ios::binary);
            require(static_cast<bool>(output), "cannot open requested NV12 fixture");
            output.write(reinterpret_cast<const char*>(adaptive_y8.first_nv12.data()),
                static_cast<std::streamsize>(adaptive_y8.first_nv12.size()));
            require(static_cast<bool>(output), "cannot write requested NV12 fixture");
        }
        std::cout << "RAW10 -> calibration -> shared final Y' -> NV12 passed; "
                     "sparse CFA clipping protects AE; codec/LUT choices preserve AE history\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Stereo signal path check failed: " << error.what() << '\n';
        return 1;
    }
}
