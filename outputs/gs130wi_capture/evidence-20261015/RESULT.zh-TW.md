# 共用 Capture API / ROS / RTSP 板端結果

2026-10-15，RUBIK Pi 3、kernel 6.8.0-1084-qcom。
程式以隔離目錄 `/home/ubuntu/capture-api-20261015` 建置，原服務 binary 沒有被替換。

| 範圍 | 實際結果 |
|---|---|
| Native C++17 consumer / C++20 backend | GCC 13.3 Release build 通過；API ownership/configuration contract 通過 |
| 相機相關檢查 | 12/12 CTest 通過，含既有 pairing、AE、geometry、影像轉換相關檢查 |
| 抽出 Linux IMU transport 後的 CLI | C++17 Release build 與 FSYNC driver fixture 通過 |
| Native API 短測 | 300 組 full-resolution、10-bit owning stereo frame；2,168 筆 IMU、329 筆 FSYNC 標記 |
| ROS publisher | Humble / GCC 11.4、C++17 adapter build/install；發布 360 組影像、2,579 筆 IMU、390 筆 FSYNC 標記 |
| 真實 DDS subscriber | 左眼 350 張、右眼 360 張，350 組左右/metadata 同 stamp；完整收到 2,579 筆 IMU，sample index gap=0 |
| ROS 影像 | 544×640、mono8；frame IDs、尺寸、資料長度、system-time stamp、metadata source/offset 檢查通過 |
| RTSP capture-api 路徑 | 1,365 input/submitted pairs、0 server dropped pairs；停止時計數 9,371 筆 IMU、1,415 筆 FSYNC 標記 |
| 新 RTSP client decode | 91 張 HEVC Main10，媒體 FPS 29.99983，穩態 PTS 遞增 |
| 原服務恢復後 decode | 181 張 HEVC Main10，媒體 FPS 30，穩態 PTS 遞增 |
| Cleanup | 各階段 IMU register snapshots 與起始狀態一致；相機持久設定、原 runner 與原 binary SHA256 一致；原服務 running、CAMSS 同步 error=0 |

IMU 總數包含相機初始化前與停止前的樣本，**不是逐 frame 區間統計**。
ROS 使用 best-effort SensorDataQoS；左眼有 10 張未被 subscriber 收到，不能將 publisher 計數視為無損交付。
本次沒有宣告光照、外參、電氣邊緣精度、曝光起點、長時間可靠性或 VIO 可用性。

相機來源為 `exposure_start_estimate`，offset=344,903 ns；個別 IMU 樣本沒有 host timestamp。
所有 frame-IMU association 與 host sample time validity 仍為 false。沒有將 IRQ、讀取時間或 ROS 發布時間當成 IMU sample stamp。

準備實測時，原 RTSP 服務曾已自行結束，報 kernel trigger association error=2；新 API 當時尚未接管硬體。保存 `board/original-failure-*` 後重啟原服務並先完成 baseline decode，再進行上述有限測試。該次失敗的原因未獨立確認，不能宣稱已修復長期穩定性。

收尾時原服務 session=16 在約 3,000 個 pulse 後再次停止，`skipped=1`、`error=10`（trigger gap），當時已無新 API/ROS/RTSP 測試 owner。紀錄為 `board/post-restore-failure-*`。再次重啟原服務後通過 181-frame decode；這項偶發失鎖仍未解決，因此目前只通過上述功能短測，**整體長時間穩定性未通過**。

第二次恢復後另以 13 個 status samples 監看 60.27 秒，原服務 active、雙眼 locked、running=1、error=0；詳見 `restored-monitor.json`。這只是有限恢復確認，不推翻上述穩定性限制。

此監看結束後 session=17 又在 pulse=3307 停止，`skipped=1`、`error=2`；當時狀態保存於 `last-state.txt`，更多紀錄為 `board/third-failure-*`。因此即使 60 秒監看通過，也不能視為問題消失。交付前再次重啟並解碼確認；沒有增加自動重啟來掩蓋資料中斷。

ROS 啟動測試曾遇到 Humble setup 的 nounset 與直接 CMake 安裝路徑問題，測試腳本已修正，並在啟動硬體前確認 package、Python type support 與 runtime library 可載入。兩次失敗測試均由 finally 恢復原 owner。

可重看 `board/api-probe.log`、`board/ros-subscriber.json`、`board/rtsp-api.log`、`decode-api-rtsp/result.json` 與 `decode-final-restored/result.json`；first-frame PGM 是真實 ROS 訂閱資料。
