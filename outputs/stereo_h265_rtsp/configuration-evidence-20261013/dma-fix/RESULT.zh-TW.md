# SC132GS camera DMA 故障修正與驗證（2026-10-13）

已修正並在 RUBIK Pi 部署可重現的 RAW10 接收邊界缺陷。原接收配置在
收到額外一列時讓 VFE 寫過 DMA allocation，重現本次 SID=0x8a0 的 SMMU
故障；正式修正版在兩眼的同一測試都完成 300 frames，沒有新 fault。

原先自然發生的長時間故障，尚未取得 fault 當下未裁切的完整 CSI 幾何。
因此可以確認並修正這條故障路徑，但不能斷言原始自然事件一定由 sensor
多輸出一列造成，也不能把短測試宣稱為永不再發生。

## 已確認的機制

- Ubuntu kernel `6.8.0-1084-qcom`；exact source `6.8.0-1084.89`。
- exact source 原廠 CAMSS 重建的 srcversion 為 `6836E35C0AA1F2FCD21FCBD`，
  與原廠模組一致。
- 每眼 1088×1280 packed RAW10：每列 1360 bytes；`sizeimage=0x1a9000`。
  IOMMU trace 證實映射長度同為 `0x1a9000`，沒有额外 padding。
- 使用原 payload-only 接收配置，在 camera 1 將 sensor output height
  1280 改為 1281、並核對讀回後，CSID ping/pong 都是 `0x1a9550`。
  比 buffer 多出的 `0x550`，恰好就是一列。
- 同一測試產生 `SID=0x8a0 / cb=28 / fsr=0x402`，software/hardware
  table walk 都失敗，擷取逾時。camera 0 的同類測試則是 `SID=0x840`。
- 故障位址落在 buffer 結尾；這是 camera IFE DMA 路徑，不是 H.265
  encoder 的 stream ID。

源碼說明見 [driver patch README](../../../sc132gs_v4l2_probe/driver-patches/README.zh-TW.md)，
包含 UML sequence diagram、Qualcomm downstream 源碼出處、部署與回復步驟。

## 正式修正

1. 在 CSID gen2 RAW10 RDI 使用 RAW8 byte transport，使硬體 crop engine
   生效；CSI packet data type、VFE 與 V4L2 格式仍維持 packed RAW10。
2. 以協議的 payload bytes 與 height 設定 inclusive crop；這次讀回
   HCROP=`0x054f0000`、VCROP=`0x04ff0000`，即每列 0..1359 bytes、0..1279 列。
3. 移除實驗用 frame-size 比較中斷與 TPG 額外列參數。前者在不完整 frame
   會抑制 EOF，因此不能留在正常串流路徑。
4. 獨立修正 FSYNC 過期脈衝補發：保留正常排程相位，跳過過期時槽，pulse
   長度從實際 GPIO assert 完成時間起算。沒有證據表明它就是本次 fault 的觸發源。

正式版 crop registers 與兩眼 ping/pong byte counters 的實際讀回值保存在
`production-crop-registers.jsonl`；正常 counters 都是 `0x1a9000`。
RAW8 在此用作 packed payload 的 byte transport，並非把像素精度改成 8-bit。

## 冷啟動與部署身份

- running module srcversion：`93BFD442CB057A0FAFA8C97`。
- running boot ID：`005c760b-d434-490f-a55e-073c02db97cb`。
- installed module SHA-256：
  `27a726f96a74daace3b9a705e5264dc0d239063dac72405967f4881c3415e3e0`。
- FSYNC binary SHA-256：
  `913741ebf3941b54d5708a581bc7dc4507841871257b0b03cccb9ce3c4bcd6fd`。
- modprobe options：`options qcom_camss geometry_guard=1`。
- override module：
  `/lib/modules/6.8.0-1084-qcom/updates/sc132gs-csid-monitor/qcom-camss.ko`。
- 原廠磁碟 module 保留；initrd 備份及回復工具位於
  `/home/ubuntu/camss-dma-fix-20261013/coldboot-backup`。

本次使用正常重啟載入正式 module，開機後相機 restore 與 RTSP 服務均啟動。
早期診斷 module 曾因熱切換觸發 runtime-power kernel error，需要使用者斷電；
相關 log 已保存。之後一律從冷啟動載入，沒有再使用熱切換。

## 實機回歸結果

| 測試 | 結果與證據 |
|---|---|
| camera 1 未限制路徑，多一列 | `cam1-overrun-unguarded`：SMMU fault，擷取 timeout 124，counter=`0x1a9550` |
| 正式版 camera 0，多一列 | `production-cam0-extra-row`：讀回 1281，300 frames，exit 0，無新 SMMU/Oops |
| 正式版 camera 1，多一列 | `production-cam1-extra-row`：讀回 1281，300 frames，exit 0，無新 SMMU/Oops |
| 正式版 camera 1，少一列 | `production-cam1-short-row`：讀回 1279，300 frames，exit 0，無新 SMMU/Oops |
| RAW10 資料完整性 | `production-raw10-byte-proof/result.json`：兩眼各 3 frames，guard 開關前後逐 byte 相同 |
| FSYNC 排程 | fresh CMake configure、C++17 target build 與 `fsync-schedule-check` CTest 通過；`production-fsync-ctest.txt` |
| Windows RTSP 解碼 | `production-windows-decode/decode.json`：482 frames，2176×1280，`yuv420p10le`，60.0036 PTS FPS，16 個不同取樣 frame |
| 持續串流 | `production-endurance-v2/result.json`：604.39 秒通過，無新 kernel fault、無擷取計數停滯 |

幾何回歸總表為 `production-geometry-regression.json`。每個測試有前後 dmesg、
完整 sensor 寫入讀回值、capture exit code、CSID counter、服務恢復狀態。
少一列的 counter=`0x1a8ab0`；該測試沒有證明 buffer 最後一列有有效影像內容。

test-pattern frame 本身隨 frame 序號變化，因此 `stable_three_frames=false`。
驗證比較的是 guard 前後同序號 frames 的完整 bytes，不是以「圖樣靜止」為判準。

## 無效／失敗的早期測試

- payload-only 加 crop：仍越界，不能採用。
- byte transport 加 frame-size 比較中斷：沒有新 SMMU，但擷取 stall，不能採用。
- width +4：擷取 stall；此測試未證實 sensor 能產生有效的擴寬 frame，
  不能作為有效的超寬 CSI 測試，也沒有宣稱其連續擷取通過。
- 舊 height -1 腳本只寫低 byte，實際讀回 `0x05ff`=1535，並非 1279。
  該結果無效；正式回歸已改成完整 16-bit 寫入並核對讀回。
- 第一版 endurance 腳本用了板端不支援的 dmesg time-format；在任何測量前失敗。
  修正為板端支援的預設 boot-relative timestamp 後，另開 v2 資料夾執行。

## 驗證界線與恢復狀態

- 這次 verified path 是 Linear、每眼 1088×1280、60 FPS。沒有把其他模式
  或其他 kernel 的相容性宣稱為已驗證。
- 歷史自然故障曾經運作約 14 小時 40 分鐘才出現；短期 endurance 不能替代
  同等或更長的自然事件觀察，也不能排除其他 buffer-lifetime 故障。
- GPIO trace 是軟體 GPIO 呼叫時間，不是示波器電氣邊緣；軟體排程測試不等於
  相機／IMU 真實 exposure timing 的校準證明。
- Windows Main10 解碼不是螢幕 10 bpc 證明，也不是使用者的畫質確認。
- 每次 sensor geometry / test-pattern 測試後，camera service 已重新套用保存設定。
  最後核對值：Linear、binning off、60 FPS、AE on、brightness/target 30、
  exposure rows 1330、max gain 128、control_error=0、revision 181。

原始 PMIC register `-EIO` 與本次 camera DMA 故障目前沒有因果證據。

## 16 小時自然串流測試（進行中）

短期回歸通過後，已啟動一次性的 `sc132gs-dma-soak-20261013.service`。
此 transient unit 以 Nice=10 讀取擷取計數與 dmesg，每 10 秒記錄一次，
最多執行 57,600 秒；不重啟串流、不寫 sensor registers，也不改相機設定。
偵測到 service 停止、新 SMMU/Oops 或 capture counter 停滯時，保存證據並結束。

板端結果資料夾：
`/home/ubuntu/sc132gs-camera-tests/dma-fix-20261013/production-natural-16h`。
完成後的 `result.json` 記錄 passed/failure；`samples.jsonl`、前後 dmesg、
server log 與相機狀態供後續分析。本次交付時 unit 為 active，尚沒有完成結果，
不能把這項測試列為通過。原始自然事件的精確觸發條件仍未確認。

本次正式 module 沒有 geometry_monitor / geometry_test_extra_lines 參數。
早期 `load_csid_monitor.sh` 與 TPG helper 已換成拒絕執行的退役入口，原檔另存
`.retired.txt`；repository 移除未驗證的 TPG helper，避免誤用。
## 16 小時測試的實際結果（後續檢查）

此測試在 1621.90 秒（約 27 分鐘）提前結束，`passed=false`，原因為
`camera service stopped`。camera service 自啟動共運作 37 分 55 秒，
退出前完成 136333 pairs，記錄 `camera queue overran 32 frames`。
本次 dmesg 與 monitor 沒有偵測到新的 SMMU/Oops，不能把此次 queue overrun
直接當成原 SMMU fault，也不能把長測列為通過。

使用者表示測試期間有用 VLC 播放；目前無法確定播放／關閉與退出的精確時點。
log 保存了多次 RTSP connect/close，尚未確認因果關係。已保存長測資料至
本資料夾的 `production-natural-16h`，並重新套用保存的相機設定恢復串流。
後續需查明哪一眼停止 dequeue、配對 queue 為何達到上限；不得把重啟當成修復完成。
## Queue overrun 定位準備

最後一次記錄的 RTSP client close 約在 pair 127055，queue overrun 時為
pair 136333，間隔約 155 秒；不能直接認定 VLC close 造成故障。

已在 StereoCapture 私有實作加入 typed HealthReason 診斷事件：queue 首次到
8 frames、overrun 及 timeout 時記錄兩眼 queue 深度、dequeue 累積數、
距離最後 dequeue 的毫秒數、最後配對序號與 queue 頭部 timestamp。
此改動只增加紀錄，沒有提高 queue 上限、丟棄 frame 或修改錯誤恢復行為，
因此尚不能宣稱 queue overrun 已修正。

首次診斷 build 未設定 Release，啟動驗證未通過；已回復原執行檔，再以
CMAKE_BUILD_TYPE=Release 重建及部署。Release 版通過 camera restore 驗證，
Windows RTSP/TCP 六次開啟／解碼 120 frames／關閉均通過，維持
2176×1280、yuv420p10le、約 60 PTS FPS。
證據為 `queue-health-reconnect.json` 與 `rtsp-health-release-build.log`。

Release 診斷 binary SHA-256：
`d31889264ca3da37cf8c83f26d87c6f4c317664f59541e9becef3bdca6bd8f1e`。
原執行檔保存於板端 `rtsp-before-health-diagnostics`。
新的唯讀觀察 unit 為 `sc132gs-queue-watch-release-20261013.service`，
最多 3600 秒；資料位於板端
`/home/ubuntu/sc132gs-camera-tests/dma-fix-20261013/queue-health-release-watch`。
這是定位 queue 故障的觀察，交付時尚未完成；未重新把失敗的 16h 測試列為通過。
## 18:00 排程恢復（2026-10-13，Asia/Taipei）

依照使用者要求，在 18:00 排程執行後啟動 camera restore，服務啟動驗證通過。
已讀回 Linear、binning off、60 FPS、AE on、target 30、exposure ceiling 1330
rows、max gain 128、control_error=0、revision 181；gain 由 AE 隨光線調整。
使用原已部署的 CAMSS srcversion 93BFD442CB057A0FAFA8C97 與 Release 診斷版。

Windows 實際解碼證據為 `resume-1800-windows-decode/decode.json`：
482 frames，2176×1280，yuv420p10le，59.9988 PTS FPS，16 個不同取樣 frame，passed=true。
encoder 的啟動設定仍是 Main10、20 Mbps、60 FPS；未修改 B-frame 設定。

已確認只啟動一個新 transient unit：
`sc132gs-resume-20261013-1800-watch.service`。
板端資料另存 `/home/ubuntu/sc132gs-camera-tests/dma-fix-20261013/resume-20261013-1800`，
監看時間為 3600 秒。啟動後前 60 秒 service active、capture counters 持續增加，
input / encoded FPS 約 60，沒有新 kernel fault。這項一小時測試仍在進行，尚無完整結果。

一次性的恢復 automation 已設為 PAUSED，避免重複執行；板端監看繼續執行並自行保存結果。
## 18:00 恢復後一小時監看結果

已取回板端 `resume-20261013-1800/result.json`：passed=true，failure=null，
elapsed_s=3607.20，boot ID 維持 005c760b-d434-490f-a55e-073c02db97cb。
監看從 18:02:29 執行約一小時，約 19:02:36 結束；沒有新 SMMU/Oops，
擷取計數持續增加。完整 samples、dmesg、server log、status 與 summary
已保存於本資料夾的 `resume-20261013-1800`。

19:23 取回結果時，Windows 熱點已停止，原 192.168.137.x 介面／route
不存在，ping 與 SSH 不通。使用者於 19:25 前後重開熱點後，重新連線成功。
板子 boot ID 沒有改變，RTSP service 仍 active，input/encoded FPS 約 60；
因此當時無法取回結果是連線路徑中斷，沒有證據表明它是 camera driver 當機。

熱點恢復後，Windows 再次解碼 481 frames，2176×1280、yuv420p10le、
60.0000 PTS FPS、passed=true；證據為 `resume-1800-post-hotspot-decode/decode.json`。
相機仍維持 Linear、binning off、60 FPS、AE on、target 30、control_error=0。

一次性 automation 只負責 18:00 恢復，沒有排定 19:03 取回／回報；本次
因此未準時自動回報，之後由使用者詢問才取回。測試在板端已正常結束，
不能把沒有回報誤認為監看仍在執行。本次一小時通過不代表先前偶發的
queue overrun 已找到根因或永久修正；整體 driver 故障修復目標尚未完成。