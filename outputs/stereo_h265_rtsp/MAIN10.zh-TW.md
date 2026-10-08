# 相機 Main10 RTSP 整合

數值精度與顯示亮度是兩件事。這條路徑把相機 Bayer RAW10 轉成線性
10-bit 灰階，以 R16 儲存 0..1023，再放入 P010 的高 10 bits。
H.265 Main10 仍是有損壓縮；保留的是 10-bit 灰階處理與傳輸精度，
不是逐像素無損 Bayer RAW。

```mermaid
sequenceDiagram
    participant C as StereoCapture / V4L2
    participant B as BayerLuma
    participant A as AutoExposure
    participant E as Main10Encoder / V4L2
    participant R as RTSP server
    participant V as VLC
    C->>B: Bayer RAW10
    B-->>C: R16 linear gray (0..1023)
    C->>A: 10-bit gray statistics
    C->>E: Mirrored side-by-side R16
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
8-bit 路徑。Main10 路徑不套用顯示 gamma 或 8-bit limited-range 轉換。
AE 若啟用，以線性 10-bit histogram 計算；本次實機保留原本 AE off。

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
