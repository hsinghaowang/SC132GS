# SC132GS 硬體 binning / 120 FPS（2026-10-07）

## 已驗證結果

後續已將持續 RTSP 曝光調至 1000 行（時序估算約 6.17 ms），解碼維持約 120 FPS。以下 RAW binning 比較表為先前 256 行曝光的結果；新的亮度比較與操作見 [曝光調整記錄](exposure-compare/README.zh-TW.md)。

硬體水平與垂直 binning 已於板上驗證：每眼 RAW10 544×640，合成 H.265 RTSP 1088×640。原 CSI 2 lane 不變。現持續服務為 `sc132gs-binning120-rtsp.service`，URL：`rtsp://192.168.137.226:8554/stereo`。

| 本次場景量測 | 全尺寸讀出 | 硬體 binning |
|---|---:|---:|
| 感測器輸出 / 眼 | 1088×1280 | 544×640 |
| RAW10 列間距 / bytes | 1360 | 688（包含 padding） |
| CAM0 600 張 RAW FPS | 120.006 | 120.004 |
| CAM0 序號缺口 | 0 | 0 |
| 中央區域 RAW 平均 / DN | 72.053 | 71.572 |
| 中央區域 RAW 時間噪聲 RMS / DN | 2.205 | 1.218 |

兩組均保留 32 張 RAW，取中央 80% 視野內 64×64 取樣網格；排除均值 <=8 或 >=1000 的點後，計算每點跨影格變異，再取 RMS。曝光寄存器同為 `3e00/01/02=00/10/00`，類比增益 `3e08/09=03/20`，HTS/VTS 與 PLL 設定相同。這是同一現場的 RAW 比較，尚未用均勻光源校準或建立黑電平模型；並非相對於軟體平均縮圖的優勢證明。

本次平均亮度差約 -0.67%，時間噪聲降低約 44.8%。可支持「低光 RAW 輸出更穩定」，不能宣稱感光度或亮度提高四倍。RAW 的細小週期紋理仍應納入後續固定圖樣噪聲與黑電平校準。

RTSP 軟體 H.265 解碼驗證：10 秒收到 1195 張影格，1195 個不同 RGB hash，PTS FPS 120.0025，1088×640，已直接檢視左右實際場景。60 秒服務記錄中，5 秒區段約 117.3–120.0 FPS（多數 118–120），時間戳配對偶有捨棄影格；編碼提交佇列 dropped_pairs=0。不能宣稱長時間完全無丟幀。固定曝光、AE 關閉、自由運行，未驗證左右曝光同步。播放端需使用軟體解碼；先前板上硬體解碼純綠問題未解決。

## 實作與安全啟動順序

- `prepare-experiment.py` 根據目前已安裝驅動的對應來源建立獨立實驗模組，正常模式行為保留。
- 實驗驅動於 STREAMON 前完整設定 binning，確認 544×640 寄存器且仍在 standby 後，才開啟感測器輸出。避免全尺寸影格進入半尺寸 DMA buffer。
- RTSP 額外模式為 `experimental-linear120-binning`，要求 fps=120、AE off、downscale=1，接收端以實際 RAW stride 解包。
- `run-binning-experiment.sh` 只在接收端首次註冊前載入實驗 sensor 模組；測試間保持 CAMSS 載入，只於兩個擷取服務停止後切換實驗參數與媒體格式。
- 已編譯，既有 CTest 4/4 通過；最終流程未再出現核心 Oops / IOMMU fault。

已安裝 `/lib/modules/6.8.0-1084-qcom/extra/sc132gs.ko` 未被替換，實驗模組只載入記憶體。服務是暫存 systemd unit，不保證重開機後自動啟動。重新開機會恢復原磁碟上的 sensor 驅動；需要 binning 時，必須先載入實驗 sensor 模組再註冊 CAMSS。

## 操作

停止 binning，啟動器會切回全尺寸讀出、軟體縮小的原 120 FPS 路徑：

```sh
sudo systemctl stop sc132gs-binning120-rtsp.service
```

同一次開機、實驗模組仍載入時，啟動持續 binning：

```sh
sudo systemd-run --unit=sc132gs-binning120-rtsp --property=TimeoutStopSec=15 \
  --setenv=DURATION_SECONDS=0 \
  /bin/bash /home/ubuntu/sc132gs-binning-20261007/run-binning-experiment.sh rtspbin120
```

開機後第一次進行實驗（CAMSS 必須尚未載入）：

```sh
sudo bash /home/ubuntu/sc132gs-binning-20261007/run-binning-experiment.sh bin120
```

啟動器明確拒絕在原 sensor 模組與已載入 CAMSS 上進行熱重載。請不要在串流中直接更改實驗模組參數或 HDR 模式。

## 失敗診斷保留

初版只改接收格式而未提前設定感測器，發生記憶體存取錯誤；隨後 SC132GS/CAMSS 熱重載造成 media graph 殘留與 `camss_find_sensor()` 崩潰，需要重新上電。熱重載本身在第二次流程亦重現問題，新 binning 設定未開始擷取。後續改成一次載入、停止擷取後切參數，RAW 與 RTSP 均成功。舊 `run-raw-experiment.sh` 已停用，執行會立即拒絕。

## 設定來源

Binning 設定區塊採 Espressif 官方表中 hbin/vbin 設定；120 FPS 保留先前板上驗證的 Kendryte 時序與 GS130WI 幾何修正。因此本次是實測得到的組合，非廠商提供的完整 120 FPS binning 模式。

- https://github.com/espressif/esp-video-components/blob/master/esp_cam_sensor/sensors/sc132gs/private_include/sc132gs_mipi_2lane_24Minput_544x640_raw10_60fps.h
- https://github.com/kendryte/k230_sdk/blob/7e302f733311d284be255f0d81d3463b6ae6ee6d/src/big/mpp/kernel/sensor/src/sc132gs_drv.c

`safe-full/`、`safe-bin120/` 與 `safe-rtspbin120/` 保存原始 RAW、時間戳、寄存器、統計、影像及服務記錄。`analyze-raw.py` 可以重算統計，不需要第三方 Python 套件。
