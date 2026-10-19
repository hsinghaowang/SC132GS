# GS130WI ROS 2 adapter

使用共用 `gs130wi_capture` library 發布影像、原始 IMU 與時間來源 metadata。實測環境為板端 ROS 2 Humble container；沒有將這版接到 VIO，沒有宣告相機與 IMU 已同步。

| Topic | Type | 時間語意 |
|---|---|---|
| `/stereo/left/image_mono` | sensor_msgs/msg/Image | camera host monotonic 換算為 ROS system time |
| `/stereo/right/image_mono` | sensor_msgs/msg/Image | 與左眼相同的 stereo timestamp |
| `/stereo/metadata` | gs130wi_ros/msg/StereoMetadata | camera session、sequence、原始 monotonic timestamp、source、offset |
| `/gs130wi/imu_samples` | gs130wi_ros/msg/ImuBatch | sensor elapsed/FSYNC offset、SI 六軸數值、批次通知/讀取時間 |

預設影像為 mono8；`ten_bit:=true` 時發布 mono16，但有效值為 0..1023，不放大為 0..65535。
三個 frame ID 可設定；沒有載入可靠 calibration 時不發布 CameraInfo/TF，亦不製造內外參。

**目前不發布 `sensor_msgs/msg/Imu`。** 沒有個別樣本的共同時鐘 timestamp 時，不能把 read/IRQ time 填進 header.stamp。自訂訊息明確保留未完成的時間有效性與 frame association 狀態；不要直接當作標準 VIO IMU 輸入。

## 建置

來源需要相鄰的 `gs130wi_capture`、`gs130wi_imu`、`stereo_h265_rtsp` 與 `sc132gs_v4l2_probe` backend 目錄。這是 repository 內的 adapter，尚未包成可脫離 backend source 的發佈套件。

```sh
source /opt/ros/humble/setup.bash
cmake -S outputs/gs130wi_ros -B build-ros \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PWD/install-ros" -DBUILD_TESTING=OFF
cmake --build build-ros -j2
cmake --install build-ros
source install-ros/share/gs130wi_ros/local_setup.bash
```

直接 CMake 安裝使用 package 的 `local_setup.bash`；沒有 colcon workspace 的頂層 `setup.bash`。
source ROS setup 時不要啟用 `set -u`，因 Humble setup 會讀取尚未定義的可選環境變數。

## 執行

先由平台 owner 停止舊串流、準備 Linear 30-Hz profile 與 kernel FSYNC producer，再執行：

```sh
ros2 run gs130wi_ros gs130wi_publisher --ros-args \
  -p downscale:=2 -p maximum_frames:=360
```

`maximum_frames:=0` 為持續執行，Ctrl+C 會停止擷取並還原 IMU；應檢查程式結束碼。
參數還包括 left/right_device、imu_device、imu_gpiochip、imu_line、ten_bit、left/right_frame_id、imu_frame_id。
它們在啟動時讀取，執行期間不要動態改硬體參數。

live 模式拒絕 `use_sim_time=true`。相機 MONOTONIC→REALTIME anchor 有 bracket 檢查，system clock 發生超出容差的跳變時停止發布，要求重新建立 acquisition；這不等同 IMU→host clock calibration。
訂閱採用 SensorDataQoS（best effort、volatile），IMU 與 metadata depth=64。DDS 丟失 batch 可由 sample_index 發現；不要假設 best effort 的完整性。

container 需掛入 `/dev/video0`、`/dev/video3`、`/dev/i2c-18`、`/dev/gpiochip4` 與 host `/run/lock`，並以允許 device 存取的身分執行。沿用平台 consumer CPU affinity。
現有 `ros2-humble` container 沒有掛硬體裝置，因此板測使用同一 image 的有限測試 container，沒有修改該既有 container。

`tools/verify_live.py` 是真正的 DDS 訂閱檢查，驗證左右影像/metadata 同 stamp、圖像大小、原始 IMU 欄位與時間有效性，不是只檢查 publisher 計數。

持續運行回歸可另外指定 `--minimum-active-seconds` 與 `--maximum-gap-seconds`；工具分別記錄左圖、右圖、IMU、metadata 的首末接收跨度與最大到達間隔，避免只收到開頭少量資料也通過長測。這仍是 best-effort DDS 的可用性檢查，sample index gaps 會如實報告，不能當作無損傳輸保證。
