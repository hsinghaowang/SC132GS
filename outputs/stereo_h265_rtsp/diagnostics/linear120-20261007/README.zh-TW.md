# Linear 120 FPS RTSP 驗證（2026-10-07）

使用者接受每眼 544×640，合成 1088×640。板上現已持續啟動 `sc132gs-linear120-rtsp.service`，URL：`rtsp://192.168.137.226:8554/stereo`。服務為暫存 systemd unit，重開機不保證自動恢復。

## 實測結果

- H.265 硬體編碼 + RTSP/TCP + 軟體解碼通過，解碼影像已直接檢視，包含左右場景。
- 持續服務抽測：954 decoded frames、954 unique RGB hashes、PTS FPS 119.9992、1088×640，RGB 各通道空間範圍 255。JSON 與 PNG 在 `rtsp120-live-20261007/software-decode/`。
- 約 180 秒測試共輸入 21497 pairs；穩態約 119–120 FPS，時間戳配對偶有捨棄影格，不能宣稱完全無丟幀。
- 板上 `v4l2h265dec` 雖可計數約 120 FPS，但實際影像為純綠，判定不通過；播放請採軟體 H.265 解碼。尚未定位硬體解碼故障原因。
- 全尺寸 2176×1280@120 在 `v4l2h265enc` 失敗；可重現 poll error，不能以此推定確切硬體上限。
- 編譯與 CTest 4/4 通過；啟動器 shell 語法與解碼器 Python 語法檢查通過。

## 模式限制

目前感測器仍讀出 1088×1280，軟體生成每眼 544×640；未啟用感測器 binning。使用既有兩條 CSI lane、Linear、固定短曝光、AE 關閉、自由運行。左右影格依接收時間戳配對，並非曝光同步。較暗畫面是實際測試結果，亮度/曝光最佳化尚未驗證。

## 操作

停止實驗服務會由啟動器恢復原 Linear 60 FPS 服務：

```sh
sudo systemctl stop sc132gs-linear120-rtsp.service
```

持續啟動（需原 Linear 60 FPS 服務處於 active）：

```sh
sudo systemd-run --unit=sc132gs-linear120-rtsp --property=TimeoutStopSec=15 \
  --setenv=PROFILE_DIR=/home/ubuntu/stereo-h265-rtsp/linear120-profile \
  --setenv=DOWNSCALE=2 --setenv=DURATION_SECONDS=0 \
  /bin/bash /home/ubuntu/stereo-h265-rtsp/run-linear120-rtsp.sh
```

請避免在此實驗服務執行時從其他工具切 HDR 或修改曝光；感測器設定繞過既有驅動快取，AE 尚未適配。

## Binning 查證

Espressif 官方 SC132GS `544x640_raw10_60fps` 表明確含 `hbin color`、`vbin color` 註記（0x5900=f1、0x3220=87 等）。這是硬體 binning 候選的公開證據，但只標示 60 FPS；本板 binning + 120 FPS 尚未驗證，不能直接搬用零散寄存器。

來源：https://github.com/espressif/esp-video-components/blob/master/esp_cam_sensor/sensors/sc132gs/private_include/sc132gs_mipi_2lane_24Minput_544x640_raw10_60fps.h
