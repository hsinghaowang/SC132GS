# Linear 120 FPS 候選設定與實機驗證

2026-10-07，RUBIK Pi 3／GS130WI 雙 SC132GS。

**每眼 2 lanes、1088×1280 RAW10 的雙眼自由運行 120 FPS 已通過擷取驗證。120 FPS 外部觸發同步尚未通過。**
目前正式服務已恢復 Linear 60 FPS＋AE，未部署候選設定為正式模式。

## 找到的來源與適用限制

- [D-Robotics SC132GS 公開設定](https://github.com/D-Robotics/x5-libcam-sensor/blob/8c4159238e5a0db768d273853e4dce0039522cba/sc132gs/inc/sc132gs_setting.h)：最新 main 的 commit 仍為 `8c4159238e5a0db768d273853e4dce0039522cba`。現有初始化陣列包含 1088×1280 Linear master 60 FPS／slave 30 FPS、HDR 30 FPS，以及 896×896 模式；沒有現成 120 FPS 陣列。
- [Kendryte SC132GS 驅動](https://github.com/kendryte/k230_sdk/blob/7e302f733311d284be255f0d81d3463b6ae6ee6d/src/big/mpp/kernel/sensor/src/sc132gs_drv.c)：找到 `sc132gs_mipi_2lane_1080x1280_120fps_init`。陣列內 `3018=32`、`3019=0c` 為兩條 lanes，但 mode metadata 寫 30 FPS／4 lanes，輸入時鐘標成 23.76 MHz，VTS 寫入被註解掉。因此不能靠陣列名稱或 metadata 宣稱成功，必須實測。
- [Espressif SC132GS 2-lane 表](https://github.com/espressif/esp-video-components/blob/dbbdcbd5e25bdb6561d3f7fd0c5149641ba5536f/esp_cam_sensor/sensors/sc132gs/private_include/sc132gs_mipi_2lane_24Minput_1080x1280_raw10_60fps.h)：本次查到的表仍為 60 FPS，作為時鐘／lane 設定對照。

Kendryte 來源完整保留在 `kendryte-sc132gs.c`，衍生寄存器表須連同 `NOTICE-Canaan.txt` 保留其授權聲明。

## 實際候選設定

使用 Kendryte 120 FPS 初始化序列，STREAMON 留到接收端已啟動、配置完畢後才執行。
保留 GS130WI 既有的 1088×1280 裁切／輸出尺寸，並使用短曝光 256 rows。
未修改輸入 MCLK、接線、Device Tree 或正式 kernel module。

可重現資料：

- `kendryte-120-registers.txt`：從來源陣列提取，忽略被註解的內容，移除最後 STREAMON。
- `gs130wi-geometry-short-exposure.txt`：既有 GS130WI 尺寸及短曝光適配。
- `linear120-trigger-candidate.txt`：`3222=00` 的觸發候選，測試證實它在本次設定下沒有跟隨較低頻率。
- `linear120-trigger-standard.txt`：`3222=02`、VTS=`3fff` 的既有 slave 設定適配。

重要讀回：候選自由運行 VTS 為 `0546`（1350），HTS 寄存器為 `02ee`。
原 Linear 模式 VTS 為 `0578`（1400）。候選的 `301f=3c`、`36f9=51`、`4837=0d` 等時鐘／MIPI 設定也不同。
這些差異必須整組處理，不能僅提高 FSYNC 頻率。

## 實機結果

每次捨棄 120 張暖機影格。單眼測 600 張；雙眼每眼測 1,200 張。
每一個完成的 V4L2 buffer 都檢查 ERROR flag 與 RAW10 payload 大小，FPS 使用 receiver timestamp 計算。
診斷程序不做 Bayer 轉換、編碼或網路傳輸。

| 模式 | 左眼 FPS | 右眼 FPS | 左右接收時間差 p95 | 判定 |
|---|---:|---:|---:|---|
| 單眼自由運行 | 120.000 | — | — | 單眼 120 FPS 通過 |
| 雙眼自由運行 | 120.000 | 120.000 | 4,031 us | 雙眼吞吐通過；未同步 |
| `3222=00`，要求 100 Hz 觸發 | 119.999 | 119.998 | 4,240 us | 未跟隨 100 Hz，仍自由運行 |
| `3222=00`，要求 120 Hz 觸發 | 120.000 | 120.000 | 3,372 us | 不能宣稱觸發同步成功 |
| 標準 slave，要求 100 Hz | 97.4798 | 97.4802 | 271 us | 跟隨較低速，但未每脈衝成幀 |
| 標準 slave，要求 120 Hz | 60.0009 | 60.0009 | 274 us | 120 FPS 同步未通過 |

所有雙眼測試每眼完成的 1,200 張影格均無 sequence gap，且 sparse payload hash 各不相同。
序號連續只證明已完成 buffer 的連續性，不能證明每個外部脈衝都產生影格。
診斷程式的 exit status 檢查時間差；它不判定 120 FPS 是否通過。

自由運行 RAW 樣本已用既有 BayerLuma 解碼，可辨識完整場景；曝光短，畫面偏暗。
[雙眼 RAW 預覽](../kendryte-dual/free120/stereo120-preview.png) 使用每眼亮度 autocontrast 供檢視，未改動 RAW。
這只驗證取樣影像內容，尚未驗證正式 AE、色彩、熱穩定、長時間影像品質或 RTSP 120 FPS。

## 尚未解決的同步邊界

目前證據表示 CSI lane 數不是自由運行 120 FPS 的阻礙。
外部觸發仍需一套可在 120 Hz 每脈衝成幀的 slave／master 設定。
標準 slave 的 120 Hz 測試呈現約 60 FPS，但尚不能單憑結果定位哪個 timing 寄存器造成限制。
也沒有示波器量測 GPIO 電氣邊緣與曝光開始；userspace GPIO generator 的指令頻率不能當成精確硬體時鐘證明。

因此不能把這個候選直接加入正式雙目同步模式。下一項必要資料是原廠 120 FPS external-trigger/master-slave 設定，或足以解釋 FSIN busy/rearm、曝光與讀出交疊限制的完整寄存器手冊。
正式導入亦須使 driver 的 mode、pixel-rate、曝光上限與 AE 一致；本次 I2C 診斷繞過 driver cached mode，不適合作為正式 public API。

## 恢復與檔案

最後確認正式服務 active、Linear 60 FPS、AE enabled、target 40、error_errno=0。
Windows RTSP/TCP 實測 480 個 H.265 access units、59.88 FPS。
板端 software H.265 decoder 到達 EOS 並輸出 [恢復後雙眼影像](restored-final-00.jpg)。
這不是 Windows 顯示 FPS 或端到端延遲的測量。

原始資料在 `../kendryte-single/`、`../kendryte-dual/`、`../kendryte-dual-slave/`。
本目錄內 `verify-kendryte-single.sh`、`verify-kendryte-dual.sh`、`verify-kendryte-dual-slave.sh` 包含復原 trap；限本次已核對身份與 I2C bus 的板子使用。
RAW／CSV／寄存器讀回／kernel log 均已保存。初期測試修正了文字表 CRLF 與配置等待時間；成功結果來自修正後、接收端仍存活且確認 STREAMON 的執行。