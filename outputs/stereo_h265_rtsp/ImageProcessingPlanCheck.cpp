#include "ImageProcessingPlan.hpp"
#include <iostream>
#include <stdexcept>
using namespace stereo_rtsp;
using namespace stereo_rtsp::detail;
static void require(bool condition) {if(!condition)throw std::runtime_error("image processing contract");}
int main() {
    Settings s;s.main10=true;s.capture_api=true;s.depth_calibration="calibration";
    const auto ten=std::get<ImageProcessingPlan>(image_processing_plan(s));
    s.main10=false;s.shared_tone_map=true;
    const auto eight=std::get<ImageProcessingPlan>(image_processing_plan(s));
    require(ten.capture10 && eight.capture10 && ten.sensor_signal && eight.sensor_signal);
    require(!ten.shared_y8 && eight.shared_y8);
    s.main10=true;
    require(std::get<ImagePlanError>(image_processing_plan(s))==ImagePlanError::tone_output);
    s.main10=false;s.gpu_rectification_map="map";
    require(std::get<ImageProcessingPlan>(image_processing_plan(s)).shared_y8);
    s.detail_tone_map=true;
    require(std::get<ImageProcessingPlan>(image_processing_plan(s)).shared_y8);
    s.gpu_rectification_map.clear();
    require(std::get<ImagePlanError>(image_processing_plan(s))==ImagePlanError::detail_mapping);
    s.detail_tone_map=false;s.gpu_rectification_map="map";
    s.display_range=VideoRange::full;
    require(std::get<ImageProcessingPlan>(image_processing_plan(s)).shared_y8);
    s.gpu_rectification_map.clear();
    require(std::get<ImagePlanError>(image_processing_plan(s))==ImagePlanError::display_range);
    s.display_range=VideoRange::limited;s.gpu_rectification_map="map";
    s.downscale=2;
    require(std::get<ImagePlanError>(image_processing_plan(s))==ImagePlanError::depth_geometry);
    s.depth_calibration.clear();
    require(std::get<ImagePlanError>(image_processing_plan(s))==ImagePlanError::rectification_profile);
    s.downscale=1;s.depth_calibration="calibration";
    s.gpu_rectification_map.clear();s.shared_tone_map=false;
    require(std::get<ImagePlanError>(image_processing_plan(s))==ImagePlanError::depth_geometry);
    std::cout<<"8-bit output retains 10-bit capture/AE; unsupported combinations fail closed\n";
}
