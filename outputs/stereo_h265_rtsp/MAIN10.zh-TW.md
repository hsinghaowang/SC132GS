# 相機 Main10 RTSP 整合

目前預設（2026-10-12）：Linear 全解析度、60 FPS、AE target30。
使用者確認 Linear 看不到霧狀；HDR 調校暫停，以下 HDR 結果保留為
歷史診斷與限制，不是目前採用的模式。

後續品質限制（2026-10-12）：使用者回報 HDR 長曝光存在幾乎整片
固定霧狀紋理。下列暗部改善數值只證明逐幀雜訊改善，不代表固定
空間偏差改善。已核對前兩次修正沒有回退；尚未找到消除紋理的設定。
詳見 `diagnostics/hdr-tuning-20261012/HAZE_RESULT.zh-TW.md`。

2026-10-12 長曝光版本已在 OpenVINS 建置完成後重開套用，8/8 CTest 通過。
本場景 HDR 15 FPS、AE target=30、TOTAL=4350、SECOND=1、gain index=0，
與 Linear 30 FPS 的同 target 比較：雙眼中位亮度差約 -2.0%/-1.4%，
解碼飽和比例由 4.48%/4.20% 降至 0；四個固定暗部區塊的未編碼
對比／殘差雜訊比提升 34～38%，RTSP 解碼後提升 27～38%。
這是降低 FPS 的品質取捨，不是同 FPS 的優勢證明。HDR 壓縮亮部後，
整區平均仍低約 23～27%；不宣稱整張平均值相同。
正式 owner 上限為 30/24/20/15 FPS → 1492/2560/3629/4350 nominal rows。
驅動寄存器範圍 4492 在 15 FPS 的手動試驗造成停流，故不提供為正式上限。
量測與限制見 `diagnostics/hdr-tuning-20261012/sensor-signal/README.zh-TW.md`。

2026-10-12 最新 sensor profile：`sc132gs-camera apply --ae on --ae-target N`
設定並保存 0..100% 的有效線性灰階 P50 目標，切換 Linear/HDR 保留 target。
本板編碼前遮光量測得到 Linear 黑位 37、HDR 黑位 53（10-bit）。
未 binning 的 Main10 預設先以 `round(1023*clamp((gray10-B)/(1023-B),0,1))`
扣除模式黑位並正規化，再輸出與衡量 AE；這是固定線性校正，gamma=1。
目標為 `round(1023*N/100)`，對應未校正數值
`B+round((1023-B)*N/100)`。相同 target 因此代表相同有效灰階，
不再把兩種模式不同的黑位誤認為光訊號。兩者使用每眼中央 80% 區域 P50，
不是整張影像平均值。HDR 原始 RAW clipping 的亮部保護仍優先。
校正已實測 gain index 0、11、21；binning 與明確選用的 B profile 不套用此校正。
RAW buffer 不修改。B profile 保留歷史較暗 80% 取樣與顯示曲線。

2026-10-12 後續：依使用者要求，Main10 HDR 預設取消 B 顯示曲線及
其 AE target 換算，先查看未提亮的感測器灰階。`--hdr-display sensor`
為預設；`--hdr-display b` 才啟用 B 曲線及配套 AE target 語意。
先前手動觀察設定為 AE off、TOTAL=1200、SECOND=1、gain=21。
以下 B 曲線調校記錄描述前一階段，並非目前預設直播輸出。

2026-10-12 HDR 調校：Main10 HDR 在編碼前套用使用者選定的 B 曲線，
`round(1023*sqrt(clamp((gray10-52)/971,0,1)))`。52 為此板／模式的
經驗黑位準；此曲線保留固定亮暗部關係，不逐幀自動拉伸。
AE 與亮部飽和判斷仍量測原始 RAW10。固定 TOTAL=1492、SECOND=1、
gain=21 的暗部量測，經 B 曲線換算約 30%，因此此場景 target 採 30%。
這是暗部取樣群的亮度，並非整張畫面平均亮度。
HDR B 的 target 不再乘以前的 80%；80% 僅保留為暗部取樣群大小。
Linear 與舊 8-bit HDR 路徑的 target 語意維持原狀。

數值精度與顯示亮度是兩件事。這條路徑把相機 Bayer RAW10 轉成線性
10-bit 灰階，以 R16 儲存 0..1023，再放入 P010 的高 10 bits。
H.265 Main10 仍是有損壓縮；保留的是 10-bit 灰階處理與傳輸精度，
不是逐像素無損 Bayer RAW。

```mermaid
sequenceDiagram
    participant C as StereoCapture / V4L2
    participant B as BayerLuma
    participant A as AutoExposure
    participant S as SensorSignalCalibration
    participant E as Main10Encoder / V4L2
    participant R as RTSP server
    participant V as VLC
    C->>B: Bayer RAW10
    B-->>C: R16 linear gray (0..1023)
    C->>A: HDR original RAW clipping statistics
    C->>S: Mirrored side-by-side R16
    S-->>A: Black-calibrated linear P50
    A-->>C: Exposure / gain decision
    S->>E: Linear 10-bit gray, gamma=1
    Note over E: P010 packing, neutral UV, Main10 encode
    E-->>R: HEVC access units with camera PTS
    R-->>V: H.265 RTP / TCP
    Note over V: Decode to 10-bit YUV; render to display
```

Main10Encoder 是擷取執行緒擁有的 move-only PIMPL 物件，負責 codec fd、
mmap 與 V4L2 buffer 的 RAII 生命週期。RTSP 客戶端共用同一編碼器，
重新連線只要求 keyframe，不開新的硬體編碼 session。

AArch64 的 full-size R16 灰階轉換使用 NEON，保留原來的 bilinear
插值與整數四捨五入。測試比較不規則 Bayer 圖樣的向量區、尾端及邊界，
確認與純量參考逐像素一致。

## 使用

`--hevc-profile main10 --bitrate 20000000` 啟用 Main10；`main` 保留 NV12
8-bit 路徑。未 binning 的預設 Main10 Linear/HDR 都套用上述黑位線性校正，
兩者皆不經中間 8-bit limited-range 量化。顯示端可自行調整 gamma。
以下為歷史 B profile 的調校紀錄：AE 使用 10-bit histogram。Linear 使用灰階中位數；HDR 雙目標 AE 直接
取 Bayer 轉換前的 RAW10 統計，以原始數值檢查感測器飽和。
HDR 固定將 samples 按亮度分組：較暗 80% 與最亮 20%。暗部使用較暗
80% 的中位數（整體 P40）。Main10 B 的設定亮度就是這個暗部中位數
經 B 曲線後的百分比；target=30% 反算為 RAW10 139/1023。
較舊路徑的 `設定亮度 × 80%` 換算不適用於 Main10 B。高光上限 5% 表示
每眼最亮 20% samples 中，sample>=1020 的占比不超過 5%，等於全區約 1%。
分組遇到非整數數量時，高光 sample 數向上取整，其餘歸入暗部。
不刻意製造 5% 過曝。硬體限制可能使兩個目標無法同時達成。傳給編碼器的
R16 灰階在 HDR Main10 編碼前才套用 B 曲線。0..100 目標可設定；黑位、曝光與增益上限
仍限制實際可達亮度。

2026-10-08 HDR 增益控制已解除固定 0 的限制，沿用 Linear 的曝光優先
政策：TOTAL 到上限後才增加類比增益，並受 max-gain-index 限制。
先前人工比較設定是 AE 關閉、TOTAL 1492、要求比例 256、gain index 16、
max-gain-index 16；實際 3e08/09=03/2d，約 1.40625x 類比增益。
先前 B profile 已驗證的本場景設定：暗部 target=30%、高光組過曝上限 5%、max-gain-index 128。
TOTAL 與 SECOND 以 clustered V4L2 controls 一起提交，再由感測器 group
hold 更新曝光與 HDRC 係數。短曝光增益維持原值。SECOND 到下限仍缺乏
亮部餘裕時，停止增加長曝光 gain，回報 brightness_limited 與
highlight_limited。5% 限制是即時控制目標，場景突變時需要收斂時間，
不是保證每一幀都不超標。相機間更新仍不代表電氣上的同步曝光。

HDR AE 防震盪：每次控制週期先略過 3 組曝光生效／穩定中的 frame pairs，
再平均 9 組統計；每 12 組才更新一次（30 FPS 時約 2.5 Hz）。SECOND
到下限且高光接近上限時，鎖住提亮方向，超標則每次降低一級 gain。
高光必須低於上限減去 `max(1 個百分點, 上限 / 3)`，連續 8 次控制週期
才恢復提亮，避免暗部與高光反覆爭奪 gain。target 改變時重設此狀態。

`sudo sc132gs-ctl hdr-overexposure 5` 可改執行中的過曝上限（整數 0..100%，
目前此額外參數未寫入持久設定，服務重啟回到 5%）。既有
`sudo sc132gs-camera apply --ae on --brightness 40 --max-gain-index 128`
控制暗部 target 與增益上限。完整證據見 `diagnostics/hdr-dual-target-20261008/`。

之前的 HDR 預覽提亮在 VLC 顯示端完成：啟用 Image adjust，設定 Gamma=2.63、
Contrast=1.05、Brightness=0.97，接近舊 HDR 預覽曲線。這些是 VLC 全域
顯示設定；觀看其他 Linear／一般影片時可取消 Image adjust。
顯示調整不會改寫 RTSP 串流或 stereo 接收的 10-bit 灰階。

板端正式服務使用 `/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp`。
`run-camera-profile.sh` 預設 Main10，可用 `SERVER_BIN` / `HEVC_PROFILE`
覆寫。原 binary 位於 `build-exposure60`，舊 wrapper / launcher 備份於
`/home/ubuntu/stereo-h265-rtsp/main10-backup-20261008/`。

此次完整建置來源保存在 `/home/ubuntu/stereo-main10-20261008/`，包括
`stereo_h265_rtsp` 與 `sc132gs_v4l2_probe` 兩個相鄰來源目錄。
可用 `cmake -S /home/ubuntu/stereo-main10-20261008/stereo_h265_rtsp
-B /home/ubuntu/stereo-main10-20261008/build -DCMAKE_BUILD_TYPE=Release`
重新設定後建置。正式目錄亦已同步 RTSP C++ 來源；若從正式目錄建置，
需明確設定 `SC132GS_AE_SOURCE_DIR` 指向上述新版 AE 來源。

## 平台注意事項

- 原生 V4L2 bypass GStreamer encoder 的 P010 negotiation 限制；
  GStreamer 仍負責 h265parse、RTSP、RTP。
- 捕獲 queue 先 STREAMON，再啟動輸入 queue。此次成功配置也明確指定
  BT.709、full range 與線性 transfer；尚未隔離早期失敗的單一根因。
- Qualcomm 的 OUTPUT S_PARM 設 operating rate，CAPTURE S_PARM 設碼流 FPS；
  兩者都要設 60，否則實際輸出可達 60 但 SPS 仍寫 30。
- 長時間接收測試在電腦端執行。板端軟體 Main10 解碼會競爭 CPU，曾使
  擷取降到約 52 FPS；不能拿這種同機雙重負載當作一般串流結果。
- VLC 解碼為 10-bit 不等於螢幕面板輸出 10-bit。此次沒有驗證面板 bit depth。
- 多次停止／啟動 codec 後，驅動曾累積殘留 session，報
  `total 1080p sessions 5, exceeded max limit 4`。停止相機服務並確認
  `/dev/video32`、`/dev/video33` 沒有使用者後，重新載入 `iris_vpu`
  再啟動可恢復。此次沒有修改 kernel/firmware，不能聲稱重啟殘留問題已修復。

實測證據與量測結果：`diagnostics/main10-integration-20261008/`。
HDR AE 與顯示修正：`diagnostics/hdr-main10-ae-display-20261008/`。
