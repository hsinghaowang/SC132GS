#include "devices/eeprom/eeprom.hpp"
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <vector>

// Offline transport shim: only the captured file is accessed, never /dev/i2c-*.
static std::vector<uint8_t> image;
namespace gs130::base {
I2cDevice::I2cDevice(uint8_t, uint8_t) {}
I2cDevice::~I2cDevice() = default;
Status I2cDevice::readBurst16(uint16_t offset, uint8_t* data, uint32_t count) const {
    if (!data || static_cast<size_t>(offset) + count > image.size())
        return Status::ParamError;
    std::memcpy(data, image.data() + offset, count);
    return Status::Ok;
}
}
namespace gs130::eeprom {
bool register_model(const ModelDesc*) { return true; }
extern const ModelDesc kUnionStereoImuFisheyeV1p2R0N4;
}
static void print_camera(const gs130::CameraIntrinsics& camera) {
    std::cout << "{\"intrinsics\":[" << camera.fx << ',' << camera.fy << ','
              << camera.cx << ',' << camera.cy << "],\"distortion_coeffs\":[";
    for (unsigned i = 0; i < 4; ++i)
        std::cout << (i ? "," : "") << camera.dist_coeffs[i];
    std::cout << "],\"fisheye\":"
              << (camera.dist_model == gs130::DistModel::Fisheye ? "true" : "false") << '}';
}
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    std::ifstream input(argv[1], std::ios::binary);
    if (!input) return 3;
    image.assign(std::istreambuf_iterator<char>(input), {});
    gs130::base::I2cDevice file_transport(0, 0);
    const auto& parser = gs130::eeprom::kUnionStereoImuFisheyeV1p2R0N4;
    gs130::StereoImuModel calibration{};
    if (!parser.probe(file_transport)) return 4;
    if (parser.read(file_transport, &calibration) != gs130::Status::Ok) return 5;
    std::cout << std::setprecision(17) << "{\"probe_passed\":true,\"right\":";
    print_camera(calibration.cam_right);
    std::cout << ",\"left\":";
    print_camera(calibration.cam_left);
    std::cout << "}\n";
}
