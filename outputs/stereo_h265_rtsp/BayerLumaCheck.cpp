#include "BayerLuma.hpp"
#include <algorithm>
#include <chrono>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

using stereo_rtsp::detail::BayerLuma;

void require(bool value) { if (!value) throw std::runtime_error("Bayer conversion check failed"); }

std::vector<std::uint8_t> pack(const std::vector<unsigned>& pixels, int w, int h, int stride) {
    std::vector<std::uint8_t> raw(stride * h, 0xa5);
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; x += 4) {
            auto* p = raw.data() + y * stride + x * 5 / 4;
            p[4] = 0;
            for (int i = 0; i < 4; ++i) {
                const auto v = pixels[y * w + x + i];
                p[i] = v >> 2;
                p[4] |= (v & 3) << (i * 2);
            }
        }
    return raw;
}

int main(int argc, char** argv) {
    try {
        if (argc == 3) {
            constexpr int w = 1088, h = 1280, stride = w * 5 / 4;
            std::ifstream input(argv[1], std::ios::binary);
            std::vector<std::uint8_t> raw(stride * h), gray(w * h);
            input.read(reinterpret_cast<char*>(raw.data()), raw.size());
            require(input.gcount() == static_cast<std::streamsize>(raw.size()));
            BayerLuma converter(w, h);
            const auto start = std::chrono::steady_clock::now();
            for (int i = 0; i < 60; ++i) converter.convert(raw, stride, gray, 1);
            const auto ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count() / 60;
            std::ofstream output(argv[2], std::ios::binary);
            output << "P5\n" << w << ' ' << h << "\n255\n";
            output.write(reinterpret_cast<const char*>(gray.data()), gray.size());
            require(static_cast<bool>(output));
            std::cout << "conversion_ms=" << ms << '\n';
            return 0;
        }
        constexpr int w = 16, h = 12, stride = w * 5 / 4 + 7;
        BayerLuma converter(w, h);
        std::vector<unsigned> pixels(w * h);
        for (int y = 0; y < h; ++y)
            for (int x = 0; x < w; ++x)
                pixels[y*w+x] = (y%2 == x%2) ? (y%2 ? 160 : 960) : 320;
        auto raw = pack(pixels, w, h, stride);
        for (int scale : {1, 2, 4}) {
            std::vector<std::uint8_t> gray(w*h/(scale*scale));
            converter.convert(raw, stride, gray, scale);
            for (auto v : gray) require(v == 111); // Uniform color must have no CFA grid, including borders.
        }
        for (unsigned level : {0U, 2U, 6U, 511U, 1023U}) {
            std::fill(pixels.begin(), pixels.end(), level);
            raw = pack(pixels, w, h, stride);
            std::vector<std::uint8_t> gray(w*h);
            converter.convert(raw, stride, gray, 1);
            for (auto v : gray) require(v == std::min(255U, (level+2)/4));
        }
        // An achromatic affine ramp must remain exact away from reflected borders.
        for (int y = 0; y < h; ++y)
            for (int x = 0; x < w; ++x) pixels[y*w+x] = 64 + 8*x + 12*y;
        raw = pack(pixels, w, h, stride);
        std::vector<std::uint8_t> gray(w*h);
        converter.convert(raw, stride, gray, 1);
        for (int y = 1; y < h-1; ++y)
            for (int x = 1; x < w-1; ++x) require(gray[y*w+x] == pixels[y*w+x]/4);
        bool rejected = false;
        try { converter.convert(std::span<const std::uint8_t>(raw).first(10), stride, gray, 1); }
        catch (const std::invalid_argument&) { rejected = true; }
        require(rejected);
        rejected = false;
        try { converter.convert(raw, stride, gray, 3); }
        catch (const std::invalid_argument&) { rejected = true; }
        require(rejected);
        std::cout << "RGGB flat color, precision, borders, padded stride, scales and ramp passed\n";
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
