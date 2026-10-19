#include "core/VioManager.h"
#include "core/VioManagerOptions.h"
#include "state/State.h"
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <thread>

namespace {
using Clock = std::chrono::steady_clock;
struct Image { double time; std::string name; };
std::vector<std::string> fields(std::string line) {
  if (!line.empty() && line.back()=='\r') line.pop_back();
  std::vector<std::string> result;
  std::istringstream input(line);
  for (std::string value; std::getline(input, value, ',');) result.push_back(value);
  return result;
}
std::vector<Image> images(const std::filesystem::path& path) {
  std::ifstream input(path);
  if (!input) throw std::runtime_error("cannot open camera CSV: " + path.string());
  std::vector<Image> result;
  for (std::string line; std::getline(input, line);) {
    if (line.empty() || line[0] == '#') continue;
    const auto row = fields(line);
    if (row.size() < 2) throw std::runtime_error("invalid camera CSV row");
    result.push_back({std::stod(row[0])*1e-9, row[1]});
  }
  return result;
}
double ms(Clock::time_point a, Clock::time_point b) {
  return std::chrono::duration<double,std::milli>(b-a).count();
}
}

int main(int argc, char** argv) try {
  if (argc != 6) {
    std::cerr << "usage: euroc_benchmark config.yaml mav0 output-directory paced(0|1) max-frames(0=all)\n";
    return 2;
  }
  const std::filesystem::path dataset(argv[2]), output(argv[3]);
  const bool paced = std::stoi(argv[4]) != 0;
  const auto limit = std::stoul(argv[5]);
  std::filesystem::create_directories(output);
  const auto left = images(dataset/"cam0/data.csv");
  const auto right = images(dataset/"cam1/data.csv");
  if (left.empty() || left.size() != right.size()) throw std::runtime_error("empty or unequal stereo sequences");
  for (size_t i=0;i<left.size();++i) {
    if (left[i].time != right[i].time || (i && left[i].time <= left[i-1].time))
      throw std::runtime_error("stereo timestamps unmatched or nonmonotonic");
  }
  std::ifstream imu_csv(dataset/"imu0/data.csv");
  if (!imu_csv) throw std::runtime_error("cannot open IMU CSV");
  std::vector<ov_core::ImuData> imu;
  for (std::string line;std::getline(imu_csv,line);) {
    if (line.empty() || line[0]=='#') continue;
    const auto row=fields(line);
    if (row.size()<7) throw std::runtime_error("invalid IMU row");
    ov_core::ImuData sample;
    sample.timestamp=std::stod(row[0])*1e-9;
    for(int k=0;k<3;++k) { sample.wm(k)=std::stod(row[k+1]); sample.am(k)=std::stod(row[k+4]); }
    if (!sample.wm.allFinite() || !sample.am.allFinite() || (!imu.empty() && sample.timestamp<=imu.back().timestamp))
      throw std::runtime_error("invalid IMU value or order");
    imu.push_back(sample);
  }
  auto parser=std::make_shared<ov_core::YamlParser>(argv[1]);
  ov_core::Printer::setPrintLevel("WARNING");
  ov_msckf::VioManagerOptions options;
  options.print_and_load(parser);
  if (!parser->successful()) throw std::runtime_error("configuration parsing failed");
  options.use_multi_threading_subs=false;
  options.use_multi_threading_pubs=false;
  options.record_timing_information=true;
  options.record_timing_filepath=(output/"internal-timing.csv").string();
  ov_msckf::VioManager estimator(options);
  std::ofstream timing(output/"frames.csv"), trajectory(output/"trajectory.csv");
  if(!timing || !trajectory) throw std::runtime_error("cannot open output files");
  timing << "frame,camera_timestamp,read_ms,imu_ms,estimator_ms,completion_lag_ms,initialized,state_advanced\n" << std::setprecision(17);
  trajectory << "# timestamp_imu,px,py,pz,qw,qx,qy,qz\n" << std::setprecision(17);
  size_t imu_index=0, processed=0, poses=0;
  double previous_pose=-1;
  const auto start=Clock::now();
  for(size_t i=0;i<left.size() && (!limit || i<limit);++i) {
    const double t=left[i].time;
    const double offset=estimator.get_state()->_calib_dt_CAMtoIMU->value()(0);
    // One IMU sample strictly beyond the camera time allows interpolation.
    size_t next=imu_index;
    while(next<imu.size() && imu[next].timestamp<=t+offset) ++next;
    if(next>=imu.size()) break;
    ++next;
    const double release=std::max(t,imu[next-1].timestamp)-left.front().time;
    if(paced) std::this_thread::sleep_until(start+std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(release)));
    const auto begin=Clock::now();
    ov_core::CameraData camera;
    camera.timestamp=t; camera.sensor_ids={0,1};
    for(int k=0;k<2;++k) {
      auto image=cv::imread((dataset/("cam"+std::to_string(k))/"data"/(k?right[i].name:left[i].name)).string(),cv::IMREAD_GRAYSCALE);
      if(image.empty() || image.cols!=752 || image.rows!=480) throw std::runtime_error("missing image or wrong resolution");
      camera.images.push_back(image);
      camera.masks.push_back(cv::Mat::zeros(image.size(),CV_8UC1));
    }
    const auto read_end=Clock::now();
    while(imu_index<next) estimator.feed_measurement_imu(imu[imu_index++]);
    const auto imu_end=Clock::now();
    estimator.feed_measurement_camera(camera);
    const auto end=Clock::now();
    const auto state=estimator.get_state();
    const bool valid=estimator.initialized() && state->_timestamp>previous_pose;
    if(valid) {
      const auto p=state->_imu->pos();
      // JPL stores R_GtoI; export Hamilton quaternion for R_ItoG.
      const Eigen::Quaterniond q(state->_imu->Rot().transpose());
      if(!p.allFinite() || !q.coeffs().allFinite()) throw std::runtime_error("nonfinite estimate");
      trajectory << state->_timestamp+state->_calib_dt_CAMtoIMU->value()(0) << ',' << p.x()<<','<<p.y()<<','<<p.z()<<','<<q.w()<<','<<q.x()<<','<<q.y()<<','<<q.z()<<'\n';
      previous_pose=state->_timestamp;
      ++poses;
    }
    timing << i << ',' << t << ',' << ms(begin,read_end) << ',' << ms(read_end,imu_end) << ',' << ms(imu_end,end) << ',';
    if(paced) timing << ms(start,end)-(t-left.front().time)*1000; else timing << "nan";
    timing << ','<<estimator.initialized()<<','<<valid<<'\n';
    ++processed;
    if(processed%200==0) std::cout << "PROGRESS frames=" << processed << " poses=" << poses << std::endl;
  }
  const double elapsed=ms(start,Clock::now())/1000;
  std::ofstream summary(output/"summary.json");
  summary << std::setprecision(17) << "{\"frames\":"<<processed<<",\"input_frames\":"<<left.size()<<",\"poses\":"<<poses<<",\"elapsed_s\":"<<elapsed<<",\"paced\":"<<(paced?"true":"false")<<",\"opencv_threads\":"<<options.num_opencv_threads<<",\"gt_initialization\":false,\"ros_transport\":false}\n";
  std::cout << "DONE frames="<<processed<<" poses="<<poses<<" elapsed_s="<<elapsed<<std::endl;
  return poses ? 0 : 3;
} catch(const std::exception& e) {
  std::cerr<<"BENCHMARK_ERROR: "<<e.what()<<'\n';
  return 1;
}
