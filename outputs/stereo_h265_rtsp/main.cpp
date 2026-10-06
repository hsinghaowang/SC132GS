#include "StereoRtspServer.hpp"

#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>

namespace {
int positive_int(const char* value) {
    const std::string text(value);
    std::size_t end{};
    const int parsed = std::stoi(text, &end);
    if (end != text.size() || parsed <= 0) {
        throw std::invalid_argument("expected positive integer: " + text);
    }
    return parsed;
}
}

int main(int argc, char** argv) {
    try {
        stereo_rtsp::Settings settings;
        for (int i = 1; i < argc; ++i) {
            const std::string option(argv[i]);
            if (i + 1 >= argc) {
                throw std::invalid_argument("missing value for " + option);
            }
            const char* value = argv[++i];
            if (option == "--cam0") settings.cam0 = value;
            else if (option == "--cam1") settings.cam1 = value;
            else if (option == "--bind") settings.bind_address = value;
            else if (option == "--port") settings.port = value;
            else if (option == "--mount") settings.mount = value;
            else if (option == "--downscale") settings.downscale = positive_int(value);
            else if (option == "--fps") settings.frame_rate = positive_int(value);
            else if (option == "--brightness")
                settings.target_brightness_percent = positive_int(value);
            else if (option == "--auto-exposure") {
                const std::string mode(value);
                if (mode != "on" && mode != "off")
                    throw std::invalid_argument("auto-exposure must be on or off");
                settings.auto_exposure = mode == "on";
            }
            else throw std::invalid_argument("unknown option: " + option);
        }
        if (settings.cam0.empty() || settings.cam1.empty() ||
            settings.cam0 == settings.cam1) {
            throw std::invalid_argument("provide distinct --cam0 and --cam1 nodes; use sc132gs-discover pair");
        }
        stereo_rtsp::StereoRtspServer server(std::move(settings));
        if (auto result = server.run(); std::holds_alternative<stereo_rtsp::Error>(result)) {
            const auto& error = std::get<stereo_rtsp::Error>(result);
            std::cerr << "stereo-h265-rtsp: " << error.detail << '\n';
            return 1;
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "stereo-h265-rtsp: " << error.what() << '\n';
        return 2;
    }
}
