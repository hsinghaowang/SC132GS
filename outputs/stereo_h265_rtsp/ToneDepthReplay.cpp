// Offline evidence tool: reads one saved RAW pair; never opens camera devices,
// controls exposure, or publishes RTSP. GPU matching uses the production engine.
#include "depth/GpuStereoDepth.hpp"
#include "BayerLuma.hpp"
#include "SensorSignalCalibration.hpp"
#include "StereoToneMapper.hpp"
#include "StereoDetailMapper.hpp"
#include "sc132gs-linear-ae-policy.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <string>
#include <utility>
#include <vector>

namespace gpu = stereo_rtsp::detail::depth_gpu;
namespace fs = std::filesystem;
namespace {
constexpr int width = 1088, height = 1280, stride = 1360;
constexpr int depth_width = 544, depth_height = 640;
constexpr std::size_t native_pixels = width * height;
constexpr std::size_t depth_pixels = depth_width * depth_height;
constexpr int warmups = 2;
using Mono10 = std::vector<std::uint16_t>;
using Bytes = std::vector<std::uint8_t>;
using Mapper = stereo_rtsp::StereoToneMapper;
enum class Failure { arguments = 2, file = 3, input = 4, mapping = 5, internal = 6 };
struct Error { Failure code; int native_code{}; };

template<class T> std::vector<T> read(const fs::path& path, std::size_t count) {
    if (fs::file_size(path) != count * sizeof(T)) throw Error{Failure::input};
    std::vector<T> values(count);
    std::ifstream file(path, std::ios::binary);
    if (!file.read(reinterpret_cast<char*>(values.data()),
                   static_cast<std::streamsize>(count * sizeof(T))))
        throw Error{Failure::file, errno};
    return values;
}

template<class T> void write(const fs::path& path, const std::vector<T>& values) {
    std::ofstream file(path, std::ios::binary);
    if (!file.write(reinterpret_cast<const char*>(values.data()),
                    static_cast<std::streamsize>(values.size() * sizeof(T))))
        throw Error{Failure::file, errno};
    file.close();
    if (!file) throw Error{Failure::file, errno};
}

void pgm(const fs::path& path, const Bytes& values, int w, int h) {
    if (values.size() != static_cast<std::size_t>(w) * h) throw Error{Failure::input};
    std::ofstream file(path, std::ios::binary);
    file << "P5\n" << w << ' ' << h << "\n255\n";
    file.write(reinterpret_cast<const char*>(values.data()),
               static_cast<std::streamsize>(values.size()));
    file.close();
    if (!file) throw Error{Failure::file, errno};
}

struct Eye {
    Mono10 mono10;
    sc132gs::linear_ae::HighlightStatistics raw_highlights;
};

Eye load_eye(const fs::path& path) {
    const auto packed = read<std::uint8_t>(path, stride * height);
    Eye eye;
    eye.raw_highlights = sc132gs::linear_ae::measure_packed_raw10(
        packed.data(), packed.size(), width, height, stride);
    if (!sc132gs::linear_ae::valid(eye.raw_highlights)) throw Error{Failure::input};
    eye.mono10.resize(native_pixels);
    stereo_rtsp::detail::BayerLuma converter(width, height, false);
    converter.convert10(packed, stride, eye.mono10, 1);
    stereo_rtsp::detail::SensorSignalCalibration calibration(false);
    if (calibration.apply(eye.mono10.data(), eye.mono10.size()) !=
        stereo_rtsp::detail::SensorSignalCalibration::ErrorCode::none)
        throw Error{Failure::input};
    return eye;
}

gpu::Calibration load_calibration(const fs::path& directory) {
    gpu::Calibration config;
    config.emit_gray = false;
    config.matching_precision = gpu::MatchingPrecision::eight_bits;
    config.left_map = read<std::int32_t>(directory / "left-map.i32", depth_pixels * 2);
    config.right_map = read<std::int32_t>(directory / "right-map.i32", depth_pixels * 2);
    config.left_valid = read<std::uint8_t>(directory / "left-valid.u8", depth_pixels);
    config.right_valid = read<std::uint8_t>(directory / "right-valid.u8", depth_pixels);
    config.yuv_palette = read<std::uint8_t>(directory / "palette.u8", 1024);
    std::ifstream file(directory / "focal-baseline.txt");
    if (!(file >> config.focal_times_baseline_m_px) ||
        !std::isfinite(config.focal_times_baseline_m_px) ||
        config.focal_times_baseline_m_px <= 0) throw Error{Failure::input};
    return config;
}

gpu::DepthFrame checked(gpu::Result<gpu::DepthFrame> result) {
    if (const auto* error = std::get_if<gpu::Error>(&result)) throw *error;
    return std::get<gpu::DepthFrame>(std::move(result));
}

Mapper::FrameInfo map(Mapper& mapper, const Eye& cam0, const Eye& cam1,
                      Bytes& y0, Bytes& y1) {
    // Mapper ordering is symmetric. Keep physical camera names explicit here;
    // the GPU rectifier maps cam1 to left and cam0 to right.
    const auto result = mapper.process({cam0.mono10.data(), native_pixels},
        {cam1.mono10.data(), native_pixels}, {y0.data(), native_pixels},
        {y1.data(), native_pixels}, 1);
    if (!result) throw Error{Failure::mapping, static_cast<int>(result.error)};
    return result.frame;
}

double quantile(std::vector<double> values, double fraction) {
    if (values.empty()) return std::numeric_limits<double>::quiet_NaN();
    const auto index = static_cast<std::size_t>(std::ceil(fraction * values.size())) - 1;
    std::nth_element(values.begin(), values.begin() + index, values.end());
    return values[index];
}

void number(std::ostream& out, double value) {
    if (std::isfinite(value)) out << value;
    else out << "null";
}

template<class T> void image_statistics(std::ostream& out, const std::vector<T>& values) {
    std::array<std::size_t, 1024> histogram{};
    double sum = 0;
    for (const auto value : values) {
        if (value > 1023) throw Error{Failure::input};
        ++histogram[value];
        sum += value;
    }
    auto percentile = [&](double fraction) {
        const auto rank = static_cast<std::size_t>(std::ceil(fraction * values.size()));
        std::size_t count = 0;
        for (std::size_t i = 0; i < histogram.size(); ++i) {
            count += histogram[i];
            if (count >= rank) return i;
        }
        return histogram.size() - 1;
    };
    out << "{\"mean_code\":" << sum / values.size()
        << ",\"p01_code\":" << percentile(0.01)
        << ",\"median_code\":" << percentile(0.5)
        << ",\"p99_code\":" << percentile(0.99)
        << ",\"distinct_codes\":"
        << std::count_if(histogram.begin(), histogram.end(), [](auto n) { return n != 0; })
        << '}';
}

void depth_statistics(std::ostream& out, const gpu::DepthFrame& frame, double wall_ms) {
    std::vector<double> valid;
    for (float z : frame.meters) if (std::isfinite(z) && z > 0) valid.push_back(z);
    out << "{\"valid_pixels\":" << valid.size()
        << ",\"valid_fraction\":" << double(valid.size()) / depth_pixels
        << ",\"median_m\":";
    number(out, quantile(valid, 0.5));
    out << ",\"gpu_ms\":" << frame.gpu_ms << ",\"rectify_ms\":" << frame.rectify_ms
        << ",\"wall_ms\":" << wall_ms << '}';
}

void difference_statistics(std::ostream& out, const gpu::DepthFrame& baseline,
                           const gpu::DepthFrame& shared, float fb) {
    std::vector<double> depth_change, disparity_change;
    double depth_sum = 0, disparity_sum = 0;
    std::size_t gained = 0, lost = 0, changed_disparity = 0;
    for (std::size_t i = 0; i < depth_pixels; ++i) {
        const double a = baseline.meters[i], b = shared.meters[i];
        const bool va = std::isfinite(a) && a > 0, vb = std::isfinite(b) && b > 0;
        if (!va && vb) ++gained;
        if (va && !vb) ++lost;
        if (va && vb) {
            const double dz = std::abs(b - a), dd = std::abs(fb / b - fb / a);
            depth_change.push_back(dz); disparity_change.push_back(dd);
            depth_sum += dz; disparity_sum += dd;
            if (dd > 0.5) ++changed_disparity;
        }
    }
    const auto n = depth_change.size();
    out << "{\"both_valid_pixels\":" << n << ",\"gained_valid_pixels\":" << gained
        << ",\"lost_valid_pixels\":" << lost << ",\"changed_disparity_over_half_px\":"
        << changed_disparity << ",\"mean_absolute_depth_change_m\":";
    number(out, n ? depth_sum / n : NAN);
    out << ",\"median_absolute_depth_change_m\":"; number(out, quantile(depth_change, 0.5));
    out << ",\"mean_absolute_disparity_change_px\":"; number(out, n ? disparity_sum / n : NAN);
    out << ",\"median_absolute_disparity_change_px\":"; number(out, quantile(disparity_change, 0.5));
    out << ",\"p95_absolute_disparity_change_px\":"; number(out, quantile(disparity_change, 0.95));
    out << '}';
}

void save_native(const fs::path& output, const std::string& name, const Eye& eye,
                 const Bytes& reference, const Bytes& shared) {
    Bytes linear(native_pixels), display(native_pixels);
    for (std::size_t i = 0; i < native_pixels; ++i) {
        linear[i] = static_cast<std::uint8_t>(eye.mono10[i] >> 2);
        display[i] = static_cast<std::uint8_t>(std::clamp(
            std::lround((static_cast<int>(shared[i]) - 16) * 255.0 / 219.0), 0L, 255L));
    }
    write(output / (name + "-calibrated-mono10.u16"), eye.mono10);
    pgm(output / (name + "-baseline-linear8.pgm"), linear, width, height);
    pgm(output / (name + "-reference-bt709-limited.pgm"), reference, width, height);
    write(output / (name + "-shared-y8.u8"), shared);
    pgm(output / (name + "-shared-y8-limited.pgm"), shared, width, height);
    pgm(output / (name + "-shared-display-fullrange.pgm"), display, width, height);
}

void save_depth(const fs::path& output, const std::string& name, const gpu::DepthFrame& frame) {
    if (frame.meters.size() != depth_pixels) throw Error{Failure::input};
    write(output / (name + "-depth.f32"), frame.meters);
    write(output / (name + "-depth-color.nv12"), frame.depth_nv12);
    pgm(output / (name + "-matching-left.pgm"), frame.left_luma, depth_width, depth_height);
}
} // namespace

int main(int argc, char** argv) {
    try {
        if (argc != 5 && argc != 6) {
            std::cerr << "usage: tone-depth-replay CALIBRATION_DIR CAM0.raw10 CAM1.raw10 NEW_OUTPUT_DIR\n";
            throw Error{Failure::arguments};
        }
        const auto config = load_calibration(argv[1]);
        const auto cam0 = load_eye(argv[2]), cam1 = load_eye(argv[3]);
        const fs::path output = argv[4];
        if (!fs::create_directories(output)) throw Error{Failure::file, EEXIST};
        Bytes y0(native_pixels), y1(native_pixels), reference0(native_pixels), reference1(native_pixels);
        Mapper mapper;
        const auto mapping = map(mapper, cam0, cam1, y0, y1);
        Mapper::Config reference_config;
        reference_config.max_gain = 1;
        Mapper reference(reference_config);
        map(reference, cam0, cam1, reference0, reference1);
        save_native(output, "cam0", cam0, reference0, y0);
        save_native(output, "cam1", cam1, reference1, y1);
        const auto matching0=y0,matching1=y1;
        Bytes display0(native_pixels),display1(native_pixels);
        stereo_rtsp::StereoDetailMapper::Config detail_config;
        if(argc==6)detail_config.clip_limit=std::stod(argv[5]);
        stereo_rtsp::StereoDetailMapper display_mapper(detail_config);
        const auto display=display_mapper.process({cam0.mono10.data(),native_pixels},
            {cam1.mono10.data(),native_pixels},{display0.data(),native_pixels},
            {display1.data(),native_pixels},1);
        if(!display||y0!=matching0||y1!=matching1)throw Error{Failure::mapping};
        for(int eye=0;eye<2;++eye){
            const auto& values=eye==0?display0:display1;
            write(output/("cam"+std::to_string(eye)+"-detail-y8.u8"),values);
            Bytes full(native_pixels);
            for(std::size_t i=0;i<native_pixels;++i)full[i]=values[i];
            pgm(output/("cam"+std::to_string(eye)+"-detail-fullrange.pgm"),full,width,height);
        }

        auto opened = gpu::GpuStereoDepth::open(config);
        if (const auto* error = std::get_if<gpu::Error>(&opened)) throw *error;
        auto engine = std::get<gpu::GpuStereoDepth>(std::move(opened));
        const gpu::StereoView view10{cam0.mono10.data(), cam1.mono10.data(), native_pixels};
        const gpu::StereoView8 view8{y0.data(), y1.data(), native_pixels};
        for (int i = 0; i < warmups; ++i) engine.recycle(checked(engine.process(view10)));
        auto start = std::chrono::steady_clock::now();
        const auto baseline = checked(engine.process(view10, gpu::Preview::left_luma));
        const double baseline_ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - start).count();
        for (int i = 0; i < warmups; ++i) engine.recycle(checked(engine.process8(view8)));
        start = std::chrono::steady_clock::now();
        const auto shared = checked(engine.process8(view8, gpu::Preview::left_luma));
        const double shared_ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - start).count();
        save_depth(output, "baseline", baseline);
        save_depth(output, "shared", shared);
        start=std::chrono::steady_clock::now();
        const auto candidate=checked(engine.process8({display0.data(),display1.data(),native_pixels},gpu::Preview::left_luma));
        const double candidate_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
        save_depth(output,"candidate",candidate);
        auto precise_config=config;precise_config.matching_precision=gpu::MatchingPrecision::ten_bits;
        auto precise_open=gpu::GpuStereoDepth::open(precise_config);
        if(const auto* error=std::get_if<gpu::Error>(&precise_open))throw *error;
        auto precise=std::get<gpu::GpuStereoDepth>(std::move(precise_open));
        start=std::chrono::steady_clock::now();
        const auto reference10=checked(precise.process(view10,gpu::Preview::left_luma));
        const double reference10_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
        save_depth(output,"reference10",reference10);

        std::ofstream report(output / "comparison.json");
        report << std::setprecision(12)
            << "{\n\"schema\":1,\"same_raw_pair\":true,\"camera_access\":false,"
            << "\"live_ae_test\":false,\"ground_truth_available\":false,"
            << "\"temporal_mapping_test\":false,\"warmup_per_path\":" << warmups
            << ",\"matching_bits\":8,\"depth_width\":544,\"depth_height\":640,"
            << "\"native_width\":1088,\"native_height\":1280,"
            << "\"focal_times_baseline_m_px\":" << config.focal_times_baseline_m_px
            << ",\"comparison_scope\":\"same RAW pair: legacy linear8, shared BT709 limited Y8, full-range detail Y8 and 10-bit matching reference; reference is not ground truth\","
            << "\"eye_order\":\"input cam0 right and cam1 left; matching previews are rectified cam1 left\","
            << "\"native_baseline_preview\":\"calibrated mono10 >> 2, linear full range; not a decoded Main10 frame\","
            << "\"native_reference_preview\":\"unit-gain BT709 limited Y8; not a decoded Main10 frame\","
            << "\"shared_preview\":\"limited files contain exact Y8 codes 16..235; display-fullrange expands these to 0..255\","
            << "\"depth_validity_denominator\":\"all 544x640 pixels, including invalid calibration borders\","
            << "\"native_binary_layout\":\"host little-endian u16 mono10 and f32 meters; invalid depth NaN\","
            << "\"raw_highlight_threshold\":" << sc132gs::linear_ae::near_saturation_raw10
            << ",\"raw_highlights\":[";
        for (const auto* eye : {&cam0, &cam1}) {
            if (eye == &cam1) report << ',';
            report << "{\"sample_count\":" << eye->raw_highlights.sample_count
                << ",\"near_saturated_count\":" << eye->raw_highlights.near_saturated_count
                << ",\"saturation_bp_ceil\":" << sc132gs::linear_ae::saturation_bp(eye->raw_highlights) << '}';
        }
        report << "],\"calibrated_mono10\":["; image_statistics(report, cam0.mono10);
        report << ','; image_statistics(report, cam1.mono10);
        report << "],\"shared_y8\":["; image_statistics(report, y0);
        report << ','; image_statistics(report, y1);
        report << "],\"mapping\":{\"gain\":" << mapping.applied_gain
            << ",\"requested_gain\":" << mapping.requested_gain
            << ",\"cam0_p99\":" << mapping.left_high_code
            << ",\"cam1_p99\":" << mapping.right_high_code
            << ",\"fallback\":" << (mapping.fallback ? "true" : "false")
            << ",\"lut_revision\":" << mapping.lut_revision << "},\"baseline_depth\":";
        depth_statistics(report, baseline, baseline_ms);
        report << ",\"shared_depth\":"; depth_statistics(report, shared, shared_ms);
        report << ",\"detail_y8\":[";image_statistics(report,display0);
        report << ',';image_statistics(report,display1);
        report << "],\"detail_clip_limit\":"<<detail_config.clip_limit<<",\"candidate_depth\":";
        depth_statistics(report,candidate,candidate_ms);
        report << ",\"reference10_depth\":";depth_statistics(report,reference10,reference10_ms);
        report << ",\"old_vs_candidate\":";difference_statistics(report,shared,candidate,config.focal_times_baseline_m_px);
        report << ",\"reference10_vs_old\":";difference_statistics(report,reference10,shared,config.focal_times_baseline_m_px);
        report << ",\"reference10_vs_candidate\":";difference_statistics(report,reference10,candidate,config.focal_times_baseline_m_px);
        report << ",\"difference_on_both_valid\":";
        difference_statistics(report, baseline, shared, config.focal_times_baseline_m_px);
        report << "}\n";
        report.close();
        if (!report) throw Error{Failure::file, errno};
        std::cout << "{\"completed\":true,\"same_raw_pair\":true,\"matching_bits\":8}\n";
        return 0;
    } catch (const gpu::Error& error) {
        std::cerr << "{\"error\":\"gpu\",\"stage\":" << int(error.stage)
            << ",\"native_code\":" << error.native_code << "}\n";
    } catch (const Error& error) {
        std::cerr << "{\"error\":\"replay\",\"code\":" << int(error.code)
            << ",\"native_code\":" << error.native_code << "}\n";
    } catch (const fs::filesystem_error& error) {
        std::cerr << "{\"error\":\"filesystem\",\"native_code\":" << error.code().value() << "}\n";
    } catch (...) {
        std::cerr << "{\"error\":\"internal\"}\n";
    }
    return 1;
}
