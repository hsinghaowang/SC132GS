#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <span>

namespace sc132gs {
// Board/profile B: a fixed display response; sensor metering stays in RAW10.
class HdrDisplay final {
public:
    static constexpr int black = 52;
    static constexpr int gamma_x100 = 50;
    HdrDisplay() {
        for (int raw = 0; raw <= 1023; ++raw)
            lut_[raw] = static_cast<std::uint16_t>(std::lround(1023 *
                std::sqrt(std::max(0, raw - black) / double(1023 - black))));
    }
    HdrDisplay(const HdrDisplay&) = delete;
    HdrDisplay& operator=(const HdrDisplay&) = delete;
    HdrDisplay(HdrDisplay&&) noexcept = default;
    HdrDisplay& operator=(HdrDisplay&&) noexcept = default;
    void apply(std::span<std::uint16_t> pixels) const noexcept {
        for (auto& pixel : pixels) pixel = lut_[std::min<unsigned>(pixel,1023)];
    }
    [[nodiscard]] static int raw_target(int displayed_percent) noexcept {
        if(displayed_percent<=0) return 0;
        const double normalized=std::clamp(displayed_percent,0,100)/100.0;
        return static_cast<int>(std::lround(black+(1023-black)*normalized*normalized));
    }
    [[nodiscard]] static int displayed_percent(int raw10) noexcept {
        return static_cast<int>(std::lround(100*std::sqrt(
            std::clamp(raw10-black,0,1023-black)/double(1023-black))));
    }
private:
    std::array<std::uint16_t,1024> lut_{};
};
}
