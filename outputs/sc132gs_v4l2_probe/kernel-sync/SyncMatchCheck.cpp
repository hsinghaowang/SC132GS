#include "camss-sync-match.h"
#include <array>
#include <iostream>
#include <stdexcept>

int main() {
    try {
        const std::array<camss_sync_trigger, 4> pulse{{
            {1, 1'000'000, 1'000'010}, {2, 17'666'667, 17'666'677},
            {3, 34'333'334, 34'333'344}, {0, 0, 0}}};
        camss_sync_trigger selected{};
        auto check = [&](bool ok) { if (!ok) throw std::runtime_error("trigger association failed"); };
        check(camss_sync_future_slot(1000,999,16667)==0);
        check(camss_sync_future_slot(1000,1000,16667)==1);
        check(camss_sync_future_slot(1000,1000+16667*40,16667)==41);
        for(unsigned slot=0;slot<20000;slot++) {
            const auto deadline=1000000ULL+slot*16666667ULL;
            check(camss_sync_future_slot(1000000,deadline+106000+8333333,16666667)==slot+1);
        }
        check(camss_sync_hardware_frame(100,100,50,120));
        check(camss_sync_hardware_frame(100,200,100,120));
        check(!camss_sync_hardware_frame(100,200,100,220));
        check(!camss_sync_hardware_frame(50,200,100,120));
        check(!camss_sync_hardware_frame(100,100,50,0));
        check(!camss_sync_hardware_frame(100,100,50,90));
        for(unsigned n=2;n<100;++n)
            check(!camss_sync_hardware_frame(100,n*100,(n-1)*100,n*100+20));
        check(camss_sync_match(pulse.data(), pulse.size(), 19'666'677,
                              1'000'000, 3'000'000, &selected) == 1 && selected.id == 2);
        // Late IRQ spans two possible triggers: reject, never round to a slot.
        check(camss_sync_match(pulse.data(), pulse.size(), 36'333'344,
                              1'000'000, 20'000'000, &selected) == 2);
        // Missing trigger, future trigger, empty ring, and invalid window.
        check(camss_sync_match(pulse.data(), pulse.size(), 5'000'000, 1, 2, &selected) == 0);
        check(camss_sync_match(pulse.data(), pulse.size(), 1, 0, 3'000'000, &selected) == 0);
        check(camss_sync_match(pulse.data(), 0, 19'666'677, 1, 3'000'000, &selected) == 0);
        check(camss_sync_match(pulse.data(), pulse.size(), 19'666'677, 3, 2, &selected) == 0);
        // Startup order and one missing eye do not change trigger identity.
        for (const auto sof : {19'666'677ULL, 19'667'677ULL})
            check(camss_sync_match(pulse.data(), pulse.size(), sof, 1'000'000, 3'000'000,
                                  &selected) == 1 && selected.id == 2);
        std::cout << "passed: unique association, ambiguous IRQ, absent/future trigger, "
                     "invalid window, independent eye startup\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
