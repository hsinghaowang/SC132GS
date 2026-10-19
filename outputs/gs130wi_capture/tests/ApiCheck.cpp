#include "gs130wi/Capture.hpp"
#include <iostream>
#include <type_traits>

static_assert(!std::is_copy_constructible_v<gs130wi::Capture>);
static_assert(std::is_nothrow_move_constructible_v<gs130wi::Capture>);
static_assert(!std::is_copy_constructible_v<gs130wi::StereoFrame>);
int main() {
    // Invalid dependency/profile must be rejected before opening hardware.
    auto result=gs130wi::Capture::open({});
    const auto* e=std::get_if<gs130wi::Error>(&result);
    if(!e || e->code!=gs130wi::ErrorCode::configuration)return 1;
    gs130wi::StereoFrame frame;
    frame.images[0].mono10={0,512,1023};
    auto owner=std::move(frame);
    if(owner.images[0].mono10[2]!=1023)return 1;
    if(owner.synchronization.imu_association!=gs130wi::AssociationState::unverified)return 1;
    std::cout<<"C++17 ownership/configuration/unverified-time contract passed\n";
}
