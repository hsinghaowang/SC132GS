cmake_minimum_required(VERSION 3.20)
project(stereo_h265_rtsp LANGUAGES CXX)

find_package(PkgConfig REQUIRED)
find_package(Threads REQUIRED)
pkg_check_modules(GST REQUIRED IMPORTED_TARGET
    gstreamer-1.0 gstreamer-app-1.0 gstreamer-video-1.0 gstreamer-rtsp-server-1.0)

set(SC132GS_AE_SOURCE_DIR
    "${CMAKE_CURRENT_SOURCE_DIR}/../sc132gs_v4l2_probe"
    CACHE PATH "Directory containing SC132GS AE and control server sources")
add_executable(stereo-h265-rtsp main.cpp StereoRtspServer.cpp StereoCapture.cpp
    Raw10Luma.cpp BayerLuma.cpp StereoComposeNV12.cpp Main10Encoder.cpp
    "${SC132GS_AE_SOURCE_DIR}/sc132gs-ae.cpp"
    "${SC132GS_AE_SOURCE_DIR}/sc132gs-control-server.cpp")
target_compile_features(stereo-h265-rtsp PUBLIC cxx_std_20)
set_target_properties(stereo-h265-rtsp PROPERTIES
    CXX_STANDARD 20 CXX_STANDARD_REQUIRED ON CXX_EXTENSIONS OFF)
target_include_directories(stereo-h265-rtsp PRIVATE "${SC132GS_AE_SOURCE_DIR}")
target_link_libraries(stereo-h265-rtsp PRIVATE PkgConfig::GST Threads::Threads)
target_compile_options(stereo-h265-rtsp PRIVATE -Wall -Wextra -Wpedantic)

include(CTest)
if(BUILD_TESTING)
    add_executable(camera-mode-check
        "${SC132GS_AE_SOURCE_DIR}/sc132gs-mode-check.cpp"
        "${SC132GS_AE_SOURCE_DIR}/sc132gs-mode.cpp")
    target_compile_features(camera-mode-check PRIVATE cxx_std_20)
    target_compile_options(camera-mode-check PRIVATE -Wall -Wextra -Wpedantic)
    add_test(NAME camera-mode-check COMMAND camera-mode-check)
    add_executable(bayer-luma-check BayerLumaCheck.cpp BayerLuma.cpp)
    target_include_directories(bayer-luma-check PRIVATE "${SC132GS_AE_SOURCE_DIR}")
    target_compile_features(bayer-luma-check PRIVATE cxx_std_20)
    target_compile_options(bayer-luma-check PRIVATE -Wall -Wextra -Wpedantic)
    add_test(NAME bayer-luma-check COMMAND bayer-luma-check)
    add_executable(raw10-luma-check Raw10LumaCheck.cpp Raw10Luma.cpp)
    target_compile_features(raw10-luma-check PRIVATE cxx_std_20)
    target_compile_options(raw10-luma-check PRIVATE -Wall -Wextra -Wpedantic)
    add_test(NAME raw10-luma-check COMMAND raw10-luma-check)

    add_executable(stereo-compose-check StereoComposeNV12Check.cpp
        StereoComposeNV12.cpp)
    target_compile_features(stereo-compose-check PRIVATE cxx_std_20)
    target_compile_options(stereo-compose-check PRIVATE -Wall -Wextra -Wpedantic)
    add_test(NAME stereo-compose-check COMMAND stereo-compose-check)

    add_executable(stereo-capture-check StereoCaptureCheck.cpp
        StereoCapture.cpp BayerLuma.cpp)
    target_include_directories(stereo-capture-check PRIVATE "${SC132GS_AE_SOURCE_DIR}")
    target_compile_features(stereo-capture-check PRIVATE cxx_std_20)
    target_compile_options(stereo-capture-check PRIVATE -Wall -Wextra -Wpedantic)
endif()
