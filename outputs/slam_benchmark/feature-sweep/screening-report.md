# OpenVINS tracking feature sweep

RUBIK Pi 3 / QCS6490; full EuRoC image + IMU replay, paced 20 Hz; native sequential runner. Physical cameras, IMU capture and ROS DDS are excluded.

`num_pts` is divided by two cameras in the pinned implementation. Baseline 200 means target 100 per eye. Initializer target remains 50 total; only tracker num_pts changes. Actual tracked feature counts depend on the scene.

| Dataset | num_pts (per eye target) | Repeat | Lag P95/P99/max ms* | Service P95 ms* | >50 ms service* | ATE m | 1s RPE m / deg | Pose coverage after init |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MH_01_easy | 100 (50) | 1 | 43.1 / 51.4 / 66.8 | 41.0 | 0.8% | 0.1200 | 0.0362 / 0.294 | 100.0% |
| MH_01_easy | 150 (75) | 1 | 56.4 / 64.1 / 93.2 | 48.9 | 4.3% | 0.0934 | 0.0443 / 0.330 | 100.0% |
| MH_01_easy | 200 (100) | 1 | 72.0 / 101.5 / 133.0 | 54.7 | 15.2% | 0.1035 | 0.0262 / 0.217 | 100.0% |
| V2_02_medium | 100 (50) | 1 | 49.8 / 58.5 / 70.9 | 44.4 | 1.8% | 0.0547 | 0.0252 / 0.280 | 100.0% |
| V2_02_medium | 150 (75) | 1 | 55.2 / 63.4 / 107.2 | 49.0 | 4.2% | 0.0447 | 0.0215 / 0.291 | 100.0% |
| V2_02_medium | 200 (100) | 1 | 69.3 / 88.9 / 116.1 | 55.9 | 20.3% | 0.0508 | 0.0270 / 0.328 | 100.0% |

* Post-initialization frames. Lag is replay schedule to completion, including PNG read/decode and IMU feed; service is read + IMU + estimator. It is not exposure-to-pose hardware latency.

ATE uses full-trajectory SE3 alignment, scale fixed to 1. RPE is evaluated at 1 second. No ground-truth initialization. One full run per setting is an initial screening result, not three-repeat certification. Fresh baseline runs allow comparison without reusing the earlier baseline measured at a different time.
