#include "../sc132gs_v4l2_probe/sc132gs-linear-ae-policy.hpp"

#include <array>
#include <cstdint>
#include <iostream>
#include <vector>

namespace {
using namespace sc132gs::linear_ae;

int failures{};
void check(bool condition, const char* message) {
    if (!condition) { std::cerr << message << '\n'; ++failures; }
}

Measurements measured(int median, std::uint64_t left_clipped = 0,
                       std::uint64_t right_clipped = 0) {
    return {median, median, {10000, left_clipped, true}, {10000, right_clipped, true}};
}

void set_raw10(std::vector<std::uint8_t>& bytes, int stride, int x, int y, int value) {
    const auto offset = static_cast<std::size_t>(y) * stride + (x / 4) * 5;
    const unsigned shift = static_cast<unsigned>(x % 4) * 2;
    bytes[offset + x % 4] = static_cast<std::uint8_t>(value >> 2);
    bytes[offset + 4] = static_cast<std::uint8_t>(
        (bytes[offset + 4] & ~(3U << shift)) | (static_cast<unsigned>(value & 3) << shift));
}

void check_measurements() {
    constexpr int width = 16, height = 12, stride = 24;
    // Padding deliberately looks saturated, and must not enter the denominator.
    std::vector<std::uint8_t> raw(stride * height, 255);
    for (int y = 0; y < height; ++y)
        for (int x = 0; x < width; ++x) set_raw10(raw, stride, x, y, 100);
    // All Bayer phases and border corners participate, despite central AE metering.
    for (int phase = 0; phase < 4; ++phase) set_raw10(raw, stride, phase, 0, 1008 + phase);
    set_raw10(raw, stride, width - 1, height - 1, 1023);
    set_raw10(raw, stride, width - 2, height - 1, 1007);
    const auto result = measure_packed_raw10(raw.data(), raw.size(), width, height, stride);
    check(valid(result) && result.sample_count == width * height && result.near_saturated_count == 5,
          "RAW clipping must include every CFA phase and borders, exclude row padding");
    check(saturation_bp(result) == 261, "RAW clipping basis points use full-image denominator and round up");
    check(!valid(measure_packed_raw10(nullptr, raw.size(), width, height, stride)), "null RAW rejected");
    check(!valid(measure_packed_raw10(raw.data(), raw.size() - 1, width, height, stride)), "truncated RAW rejected");
    check(!valid(measure_packed_raw10(raw.data(), raw.size(), width - 1, height, stride)), "non-packed width rejected");
    check(!valid(measure_packed_raw10(raw.data(), raw.size(), width, height, 19)), "short stride rejected");
    check(!valid(measure_packed_raw10(raw.data(), raw.size(), -4, height, stride)), "negative dimensions rejected");
    const std::array<std::uint16_t, 4> values{0, 1007, 1008, 1023};
    const auto direct = measure_highlights10(values.data(), values.size());
    check(direct.sample_count == 4 && direct.near_saturated_count == 2, "10-bit threshold boundaries");
    const std::array<std::uint16_t, 1> invalid{1024};
    check(!valid(measure_highlights10(invalid.data(), invalid.size())), "out-of-range 10-bit code rejected");
    check(!valid({1, 2, true}), "inconsistent externally provided counts rejected");
    const HighlightStatistics native{1088U * 1280U, 10, true};
    check(valid_stereo_coverage(native, native, 1088U * 1280U), "native luma and RAW coverage accepted");
    check(valid_stereo_coverage(native, native, 544U * 640U), "downscale2 luma retains complete native RAW coverage");
    check(valid_stereo_coverage(native, native, 272U * 320U), "downscale4 luma retains complete native RAW coverage");
    check(!valid_stereo_coverage(native, {1088U * 640U, 0, true}, 544U * 640U),
          "different RAW coverage in the two eyes rejected");
    check(!valid_stereo_coverage({100, 0, true}, {100, 0, true}, 101), "partial RAW coverage rejected");
    check(!valid_stereo_coverage(native, native, 0), "empty luma coverage rejected");
}

void check_control() {
    const Settings settings{};
    const Limits limits{8, 1000, 0, 32};
    Policy policy;
    const auto shadow = policy.decide(settings, limits, {100, 0}, measured(40));
    check(shadow.exposure.rows > 100 && shadow.exposure.gain == 0 && !shadow.highlight_limited,
          "dark unclipped scene raises exposure before gain");
    const auto gain = policy.decide(settings, limits, {1000, 0}, measured(40));
    check(gain.exposure.rows == 1000 && gain.exposure.gain > 0, "gain only rises at exposure ceiling");
    const auto limited = policy.decide(settings, limits, {1000, 32}, measured(40));
    check(limited.brightness_limited && limited.constraint == Constraint::exposure_and_gain,
          "dark scene at both limits reports an unmet target");

    // Broad clipping in the worse eye lowers the target continuously. A bright
    // body then reduces gain first through the same bounded control law.
    const auto clipped = policy.decide(settings, limits, {100, 12}, measured(900, 0, 1001));
    check(clipped.exposure.rows == 100 && clipped.exposure.gain == 8 && clipped.highlight_limited &&
          clipped.constraint == Constraint::highlights,
          "broad worse-eye clipping reduces a bright body's gain first");
    const auto shorter = policy.decide(settings, limits, {100, 0}, measured(900, 1001, 0));
    check(shorter.exposure.rows < 100 && shorter.exposure.gain == 0, "clipping shortens exposure after gain reaches minimum");

    const auto hold1 = policy.decide(settings, limits, {80, 0}, measured(40));
    const auto hold2 = policy.decide(settings, limits, {80, 0}, measured(40));
    check(hold1.exposure.rows > 80 && hold2.exposure.rows > 80 && hold1.highlight_limited && hold2.highlight_limited,
          "remembered highlight penalty still permits a dark body to recover");
    const auto release = policy.decide(settings, limits, {80, 0}, measured(40));
    check(release.exposure.rows > 80 && !release.highlight_limited, "third low-clipping observation releases guard");

    policy.reset();
    (void)policy.decide(settings, limits, {100, 0}, measured(40, 51));
    (void)policy.decide(settings, limits, {80, 0}, measured(40));
    (void)policy.decide(settings, limits, {80, 0}, measured(40, 26));
    const auto restarted = policy.decide(settings, limits, {80, 0}, measured(40));
    check(restarted.highlight_limited && restarted.exposure.rows > 80, "hysteresis never freezes dark-body recovery");
    policy.reset();
    const auto at_limit = policy.decide(settings, limits, {100, 0}, measured(40, 50));
    check(!at_limit.highlight_limited, "entry limit is strictly greater than configured bound");
    const auto invalid = policy.decide(settings, limits, {100, 0}, {40, 40, {}, {10000, 0, true}});
    check(invalid.exposure.rows == 100 && invalid.constraint == Constraint::invalid_statistics,
          "missing RAW measurements cannot silently drive auto exposure");
    const auto cap = policy.decide(settings, limits, {1100, 36}, measured(40));
    check(cap.exposure.rows == 1000 && cap.exposure.gain == 32, "configuration limits are always enforced");

    auto zero = settings;
    zero.target_percent = 0;
    const auto off = policy.decide(zero, limits, {100, 12}, measured(40, 100));
    check(off.exposure.rows == 8 && off.exposure.gain == 0, "zero target selects minimum exposure and gain");

}

void check_minority_highlights() {
    Settings settings;
    settings.target_percent = 30;
    const Limits limits{8, 1377, 0, 128};
    Policy policy;
    const auto dark = policy.decide(settings, limits, {51, 0}, measured(4, 600, 725));
    check(dark.exposure.rows > 51 && dark.exposure.gain == 0 && dark.highlight_limited &&
          dark.constraint == Constraint::highlight_tradeoff,
          "minority lamps cannot force an already dark body down further");
    const int requested = settings.target_percent * 1023 / 100;
    for (std::uint64_t clipped = 0; clipped <= 1000; ++clipped) {
        const auto decision = policy.decide(settings, limits, {51, 0}, measured(4, clipped));
        check(decision.effective_target_luma10 >= std::lround(requested * std::exp2(-0.25)) &&
              decision.effective_target_luma10 <= requested && decision.exposure.rows > 51,
              "minority-area target loss is bounded by quarter EV and recovery remains possible");
    }
    // Reproduce v1's latched 37 bp band after broad clipping. Remembering
    // highlights may retain a small penalty, but cannot retain exposure=51.
    (void)policy.decide(settings, limits, {60, 0}, measured(4, 2000));
    const auto legacy_band = policy.decide(settings, limits, {51, 0}, measured(4, 37));
    check(legacy_band.exposure.rows > 51 && legacy_band.effective_target_luma10 >=
          std::lround(requested * std::exp2(-0.25)),
          "v1 51-row/37-bp latch regression recovers toward bounded body target");

    // Closed-loop synthetic plant: six percent emitter area stays clipped,
    // while the body signal responds linearly to rows and logarithmically to gain.
    policy.reset();
    Exposure exposure{51, 0};
    int body = 0;
    for (int step = 0; step < 160; ++step) {
        body = static_cast<int>(std::lround(307.0 * exposure.rows / 1377 *
            std::exp2((exposure.gain - 30) / 32.0)));
        body = std::clamp(body, 0, 1023);
        exposure = policy.decide(settings, limits, exposure, measured(body, 600)).exposure;
    }
    check(body >= requested * 8 / 10 && body <= requested * 11 / 10,
          "persistent minority emitters settle with a visible body, not minimum exposure");
    const auto settled = exposure;
    for (int step = 0; step < 20; ++step) {
        body = static_cast<int>(std::lround(307.0 * exposure.rows / 1377 *
            std::exp2((exposure.gain - 30) / 32.0)));
        exposure = policy.decide(settings, limits, exposure, measured(body, 600)).exposure;
    }
    check(exposure.rows == settled.rows && exposure.gain == settled.gain,
          "synthetic constant minority source does not sustain an actuator limit cycle");
    auto invalid = settings;
    invalid.small_highlight_limit_bp = invalid.saturation_limit_bp;
    check(policy.decide(invalid, limits, exposure, measured(body)).constraint == Constraint::invalid_statistics,
          "zero adaptive-area denominator rejected");
}

void check_highlight_boundary() {
    Settings settings;
    settings.target_percent = 30;
    const Limits limits{8, 1377, 0, 128};
    Policy policy;
    const auto below = policy.decide(settings, limits, {1377, 30}, measured(220, 1000));
    const auto above = policy.decide(settings, limits, {1377, 30}, measured(220, 1001));
    check(std::abs(below.effective_target_luma10 - above.effective_target_luma10) <= 1 &&
          below.exposure.gain == above.exposure.gain && above.exposure.gain > 30,
          "10-percent boundary cannot reverse a dark body's gain command");
    int previous_target = 1023;
    for (int clipped = 51; clipped <= 10000; ++clipped) {
        const auto decision = policy.decide(settings, limits, {1377, 30}, measured(220, clipped));
        check(decision.effective_target_luma10 <= previous_target &&
              decision.effective_target_luma10 >= std::lround(306 * std::exp2(-2.0)),
              "area compensation remains monotone and bounded through complete saturation");
        previous_target = decision.effective_target_luma10;
    }
    policy.reset();
    Exposure exposure{1377, 30};
    int late_commands = 0;
    for (int step = 0; step < 200; ++step) {
        const int body = static_cast<int>(std::lround(307 * std::exp2((exposure.gain - 30) / 32.0)));
        const auto next = policy.decide(settings, limits, exposure,
            measured(body, step % 2 ? 999 : 1001)).exposure;
        if (step >= 160 && (next.rows != exposure.rows || next.gain != exposure.gain)) ++late_commands;
        exposure = next;
    }
    check(late_commands == 0, "clipping-area jitter across 10 percent settles without actuator chatter");
    auto invalid = settings;
    invalid.max_large_highlight_darkening_ev = 0.1;
    check(policy.decide(invalid, limits, exposure, measured(220)).constraint == Constraint::invalid_statistics,
          "broad-area budget cannot invert the continuous compensation curve");
}
}

int main() {
    check_measurements();
    check_control();
    check_minority_highlights();
    check_highlight_boundary();
    if (failures) return 1;
    std::cout << "Linear AE RAW clipping coverage, worst-eye guard, hysteresis and control limits passed\n";
}
