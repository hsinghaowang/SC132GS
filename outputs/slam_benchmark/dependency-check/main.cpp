#include <ceres/ceres.h>
#include <Eigen/Core>
#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#include <iostream>

int main() {
    const cv::Mat image(8, 8, CV_8UC1, cv::Scalar(40));
    cv::Mat resized;
    cv::resize(image, resized, cv::Size(4, 4));
    ceres::Problem problem;
    double parameter = 1.0;
    problem.AddParameterBlock(&parameter, 1);
    const Eigen::Vector3d vector(1.0, 2.0, 3.0);
    if (cv::mean(resized)[0] != 40.0 || problem.NumParameters() != 1 || vector.squaredNorm() != 14.0)
        return 1;
    std::cout << "OpenCV=" << CV_VERSION << " Ceres=" << CERES_VERSION_STRING
              << " Eigen=" << EIGEN_WORLD_VERSION << '.' << EIGEN_MAJOR_VERSION
              << '.' << EIGEN_MINOR_VERSION << " dependency_link_and_run=passed\n";
}
