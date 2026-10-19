#include "CameraConfiguration.hpp"
#include <iostream>
#include <stdexcept>
#include <string>
using namespace sc132gs::configuration;
namespace {
const char* error_name(ErrorCode code) {
    switch (code) {
    case ErrorCode::invalid_argument: return "invalid_argument";
    case ErrorCode::unsupported: return "unsupported_configuration";
    case ErrorCode::busy: return "busy";
    case ErrorCode::device: return "device";
    case ErrorCode::verification: return "verification";
    case ErrorCode::internal: return "internal";
    }
    return "internal";
}
int integer(const std::string& value) {
    std::size_t end{}; const int result = std::stoi(value, &end);
    if (end != value.size()) throw std::invalid_argument("number");
    return result;
}
bool on_off(const std::string& value) {
    if (value != "on" && value != "off") throw std::invalid_argument("on/off");
    return value == "on";
}
int report(const Result<State>& result) {
    if (const auto* error = std::get_if<Error>(&result)) {
        std::cerr << "error code=" << error_name(error->code) << " errno=" << error->system_error
                  << " rollback_failed=" << error->rollback_failed << '\n';
        return 1;
    }
    const auto& s = std::get<State>(result);
    std::cout << "ok sensor_mode=" << (s.settings.mode == Mode::hdr ? "hdr" : "linear")
              << " binning=" << s.settings.binning << " max_fps=" << s.settings.maximum_fps
              << " effective_fps=" << s.configured_fps << " measured_fps_x10=" << s.measured_fps_x10
              << " eye_resolution=" << s.eye_resolution.width << 'x' << s.eye_resolution.height
              << " ae=" << s.settings.exposure.automatic << " brightness=" << s.settings.exposure.brightness_percent
              << " ae_target_percent=" << s.settings.exposure.brightness_percent
              << " exposure_rows=" << s.exposure_rows << " gain_index=" << s.gain_index
              << " exposure_ceiling_rows=" << s.exposure_ceiling_rows
              << " max_exposure_us=" << s.settings.exposure.maximum_time.count()
              << " max_gain_index=" << s.settings.exposure.maximum_gain_index
              << " limited=" << s.brightness_limited << " control_error=" << s.control_error
              << " revision=" << s.revision << '\n';
    return 0;
}
}
int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: sc132gs-camera status | capabilities | reset | apply [--mode linear|hdr] "
                     "[--binning on|off] [--max-fps N] [--ae on|off] [--ae-target 0..100 | --brightness 0..100] "
                     "[--exposure-us N | --hdr-total-rows N] [--gain-index 0..128] "
                     "[--max-exposure-us N] [--max-gain-index 0..128]\n";
        return 2;
    }
    try {
        const std::string command(argv[1]);
        if (command == "capabilities" && argc == 2) {
            for (const auto& profile : CameraController::capabilities()) {
                std::cout << "sensor_mode=" << (profile.mode == Mode::hdr ? "hdr" : "linear")
                          << " binning=" << profile.binning << " eye_resolution=" << profile.eye_resolution.width
                          << 'x' << profile.eye_resolution.height << " supported_fps=";
                for (auto rate : profile.supported_fps) std::cout << rate << ',';
                std::cout << " exposure_us_supported=" << (profile.rows_per_second > 0) << '\n';
            }
            return 0;
        }
        LinuxBackend backend;
        CameraController camera(backend);
        auto status = camera.inspect();
        if (command == "status" && argc == 2) return report(status);
        if (command != "apply" && command != "reset") throw std::invalid_argument("command");
        if (command == "reset" && argc != 2) throw std::invalid_argument("reset takes no options");
        if (std::holds_alternative<Error>(status)) return report(status);
        const auto previous = std::get<State>(status);
        if (command == "reset") return report(camera.apply(Settings{}, previous.revision));
        auto config = previous.settings;
        bool mode_changed = false, brightness_given = false, max_gain_given = false;
        for (int i=2; i<argc; i+=2) {
            if (i+1 >= argc) throw std::invalid_argument("missing value");
            const std::string key(argv[i]), value(argv[i+1]);
            if (key == "--mode") {
                if (value != "linear" && value != "hdr") throw std::invalid_argument("mode");
                config.mode = value == "hdr" ? Mode::hdr : Mode::linear;
                mode_changed = config.mode != previous.settings.mode;
            } else if (key == "--binning") config.binning = on_off(value);
            else if (key == "--max-fps") config.maximum_fps = integer(value);
            else if (key == "--ae") config.exposure.automatic = on_off(value);
            else if (key == "--brightness" || key == "--ae-target") {
                if(brightness_given) throw std::invalid_argument("duplicate AE target");
                config.exposure.brightness_percent = integer(value); brightness_given = true;
            }
            else if (key == "--exposure-us") config.exposure.time = std::chrono::microseconds(integer(value));
            else if (key == "--hdr-total-rows") config.exposure.hdr_total_rows = integer(value);
            else if (key == "--gain-index") config.exposure.gain_index = integer(value);
            else if (key == "--max-exposure-us") config.exposure.maximum_time = std::chrono::microseconds(integer(value));
            else if (key == "--max-gain-index") { config.exposure.maximum_gain_index = integer(value); max_gain_given = true; }
            else throw std::invalid_argument("option");
        }
        if (mode_changed && !max_gain_given) config.exposure.maximum_gain_index = 128;
        return report(camera.apply(config, previous.revision));
    } catch (...) { std::cerr << "error code=invalid_argument errno=22 rollback_failed=0\n"; return 2; }
}
