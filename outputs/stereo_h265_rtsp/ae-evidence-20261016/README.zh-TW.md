# AE 啟用與重新啟動驗證

現場確認 AE 原本為 `mode=off`，目標 30%，曝光 1377 rows、增益 34。原啟動腳本會先強制以手動曝光開機；這次部署未再套用啟動後的曝光設定，因此保留了關閉狀態。

先以控制 socket 啟用 AE，在 16 秒觀察內增益由 34 調到 32，左右亮度約 29%／31%，`error_errno=0`。`before.json`、`samples.json` 保留原狀態與觀察值。

## 修正與部署

- `run-camera-profile.sh` 收到 `AUTO_EXPOSURE=1` 時，等待第一筆輸入速率紀錄，再呼叫既有 `set-brightness` 控制啟用 AE；未指定時保留原來的手動啟動行為。
- `run-stereo-rtsp.sh` 增加可選的 `CAMERA_CPUS` 親和性設定。
- 板端既有 `sc132gs-camera-rtsp.service` 使用 `45-auto-exposure.conf`：`AUTO_EXPOSURE=1`、`BRIGHTNESS=30`、`CAMERA_CPUS=4-6`。
- 板端啟動腳本另有既存 kernel FSYNC 路徑與 bitrate 設定；此次僅加入上述區塊，沒有以儲存庫版本覆蓋整支腳本。

未重建或更換 RTSP binary，未更改校正檔、binning、解析度或儲存的 camera profile。`restart-verified.json` 保存 binary 與儲存設定檔的前後一致雜湊。

## 取像錯誤與證據限制

初次啟用 AE 並觀察成功後，上游曾發生 `FSYNC error=9`，導致串流停止。後續在 AE 尚未開啟、甚至沒有 RTSP 用戶端時，也能於啟動初期重現。完整紀錄保留於板端：

`/home/ubuntu/main10-rectification-20261016/ae-enable-20261016/`

將處理程序限制在 CPU 4–6 後，先完成 35 秒 AE 關閉的取像觀察，再完成正式腳本重啟與 AE 開啟後的 60 秒觀察，皆未再出現該錯誤。這支持 CPU 排程／處理餘裕是影響因素，尚非完整排程追蹤所得的根因證明；未放寬任何驅動保護檢查。

## 驗證結果

- 實際服務重啟後自動進入 `mode=auto`、目標 30%。
- 60 筆每秒觀察皆為 `running=1`、`error=0`、`error_errno=0`。
- 增益從 34 調到約 26；觀察結束時左右亮度約 28%／30%，曝光 1377 rows。
- 重新啟動 PC 預覽後，兩路皆為 live：灰階 2176×1280、`yuv420p10le`；深度 544×640、`yuv420p`。`viewer-status.json` 是短視窗解碼狀態快照，不能當成長時間 FPS 測試。
- 兩支修改後腳本通過 `bash -n`；差異通過 `git diff --check`。

這次驗證範圍為 AE 控制、服務重新啟動及一分鐘持續運作，尚非長時間穩定性或測距精度驗證。

板端原腳本備份為同一證據目錄內的 `run-camera-profile.before.sh` 與 `run-stereo-rtsp.before.sh`；臨時 CPU 診斷 wrapper 已退出正式啟動路徑，`46-ae-diagnostic.conf` 已移除。

## 後續長連線中止與手動恢復

同日 11:52:25，服務運行約 26 分鐘後因 `FSYNC error=14`（脈衝時間驗證超限）退出；停止前 depth 計算仍約 30 FPS，depth pipeline 的 `failed=0`。現有證據無法將此故障歸因於 VLC。

`later-fsync-pulse-analysis.json` 保存停止前事件環形紀錄的分析。第 46783 次脈衝的 host GPIO 拉低呼叫耗時 44.634 µs，完整包絡為 150.412 µs，超過原來 150 µs 上限；獨立的釋放超時為 5.778 µs，仍在 25 µs 上限內。這些數字是 host 呼叫時間界線，並非示波器量到的電氣脈衝。

服務當時 `Restart=no`，程序退出後 8554 埠失去監聽，因此重新連線也無法恢復。13:02:14 已依要求手動啟動既有服務，session 42 恢復 `running=1`、`locked_mask=3`、`error=0` 與 AE auto，詳見 `manual-restart.json`；PC 另成功解碼兩路各 30 張影像。

本次提交沒有修改 150 µs 門檻、kernel module 或自動重啟設定。AE 啟動修正與 CPU 配置的短期驗證通過，不代表這個後續 FSYNC 超限問題已修復。

完整故障與恢復紀錄仍保留於板端 `main10-rectification-20261016/vlc-failure-20261016-124503/` 與 `main10-rectification-20261016/manual-start-20261016-130214/`。
