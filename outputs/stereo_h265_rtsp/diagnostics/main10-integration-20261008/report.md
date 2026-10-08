# 相機 Main10 RTSP / 60 FPS / VLC 實測

2026-10-08，RUBIK Pi 3，192.168.137.226，kernel 6.8.0-1084-qcom。

已完成真實雙相機 RAW10 → 線性 R16 灰階 → P010 → 硬體 H.265 Main10 →
RTSP → Windows VLC。正式 `sc132gs-camera-rtsp.service` 已使用新版本，
測試專用服務已停止，VLC 保留即時播放。

| 項目 | 最終實測 |
|---|---|
| 輸出 | 2176×1280，兩眼左右並排、各眼水平鏡像 |
| 編碼 | Main10，10-bit luma/chroma，full range，20 Mbps 設定 |
| 電腦端 300 秒 RTSP/TCP 接收 | 18,000 個 HEVC access units，60.00 FPS |
| 板端穩定 60 個五秒統計窗 | 擷取平均 59.99970，編碼平均 59.99971 FPS |
| 板端五秒擷取窗範圍 | 59.9764–60.0228 FPS |
| 最終測試擷取 sequence gap | 0 |
| 編碼輸入丟幀 | 0 |
| VLC 解碼格式 | Planar 4:2:0 YUV 10-bit LE (I0AL)，60 FPS |
| VLC 實際顯示計數 | 73.328 秒增加 4,408 幀，約 60.11 FPS |
| VLC 該統計區間 Lost | 13 → 13，沒有增加；13 是此前啟動階段累積值 |
| 相機畫面 10-bit 數值抽樣 | 988 個不同灰階值，範圍 36–1023，低兩位有值 |
| 建置／測試 | Release 建置成功，全部 6 項 CTest 通過 |

VLC 計數由 UI 讀取，更新時間與截圖存在小幅偏差，因此顯示率解讀為
約 60 FPS；不是面板掃描率或端到端延遲量測。

上述五分鐘測試時，相機為 Linear 60、AE off、exposure_lines=1194、gain_index=0、target=40。
Main10 AE 程式路徑已改成線性 10-bit histogram，但此次沒有切換 AE 開關。
R16 值是 Bayer 插值／灰階轉換結果，不是逐像素原始 Bayer；H.265 有損，
也未驗證螢幕的實際 10-bit 輸出能力。988 個灰階值是較早同配置相機串流
解碼樣本；最終 NEON 轉換另以不規則 Bayer 圖样逐像素對照參考驗證。

## 修正與界線

初版五分鐘接收 17,986 幀、59.95 FPS，曾有少量擷取跳幀。
加入 AArch64 NEON 灰階轉換並逐像素核對後，最終五分鐘測試沒有跳幀。
此結論只涵蓋本次五分鐘負載，不代表更長時間熱穩定驗證。

板端同時軟體解碼 Main10 會競爭 CPU，曾降到約 52 FPS，故最終長測在
Windows 端接收。硬體編碼 session 在多次服務重啟後曾殘留，達到
driver session limit；停止所有 codec 使用者後重新載入 iris_vpu 已恢復。
未修改 kernel/firmware，重啟殘留問題沒有被宣稱修復。
截圖可見偶發細橫線；本次沒有進行 RAW／HEVC 同步定位，沒有宣稱修復
既有影像橫線問題。

## 證據與部署

- `simd-sustained-rtp.txt`：300 秒電腦端接收結果、SDP。
- `simd-running.log`、`simd-server-metrics.json`：最終擷取／編碼統計。
- `vlc-simd-codec.png`、`vlc-simd-codec.txt`：10-bit 解碼格式。
- `vlc-simd-stats-start/end.json/png`、`vlc-simd-metrics.json`：顯示幀率。
- `vlc-final-live.png`：五分鐘後的雙眼實際畫面。
- `decoded-luma10.u16le`、`decoded-levels.json`：10-bit 數值樣本。
- `final-service.txt`、`final-ae.txt`、`integration-kernel.log`：服務、設定、driver。

正式 binary：`/home/ubuntu/stereo-h265-rtsp/build-main10/stereo-h265-rtsp`。
SHA256：`14aea30fdec6932b3faed4b4bccc3749b3bcd0a7fcd91dece22cdde461e8dc8a`。
完整來源／建置：`/home/ubuntu/stereo-main10-20261008/`。
旧 wrapper、launcher 與來源備份：
`/home/ubuntu/stereo-h265-rtsp/main10-backup-20261008/`。
原 8-bit binary 保留於 `build-exposure60`。

播放位址：`rtsp://192.168.137.226:8554/stereo`。

## 後續 AE 與提交驗證

依使用者要求，在上述長測完成後開啟 AE、維持 target 40%。
`ae-enabled.txt` 記錄最新讀回：兩眼亮度 39%／40%、曝光 1330 行、
gain_index=42、fps_x10=599、error_errno=0。

提交時將 Main10 變更與先前未提交的相機設定／120 FPS 實驗分離。
這份暫存內容在獨立目錄完成 Release 建置，4 項 CTest 全部通過；
上表的 6 項測試與實機長測屬於含先前功能的部署版本。
`main10-camera-profile.patch` 保留既有板端 wrapper 的 Main10 部署差異。
