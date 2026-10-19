# FSYNC 完整包絡 200 µs：部署與驗證

2026-10-16（Asia/Taipei）。結果見 [RESULT.json](RESULT.json)。

## 修改

- 新增獨立 `PULSE_ENVELOPE_NS=200000`，用於完整 host 包絡與 probe 的最小 SOF 延遲檢查。
- `PULSE_OVERRUN_NS=25000` 保留；名義保持時間 `PULSE_NS=100000` 保留。
- 同步更新 kernel patch 與實際 callback fixture。稽核器新增 `--pulse-envelope-us 200`；預設 150 保留舊資料的驗證語意。

## 已驗證

| 項目 | 結果 |
|---|---|
| 實際 callback fixture | 26,000 個完整脈波；150.412 µs 接受、200 µs 接受、200.001 µs 拒絕；釋放 25 µs 接受、25.001 µs 拒絕 |
| 其他回歸 | publication／worker fixture 與 32 項 SOF／DMA association 檢查通過 |
| 板端編譯 | 6.8.0-1084-qcom；BTF 因缺 vmlinux 未產生 |
| 實際載入 srcversion | `E966374A47464C038D0632F` |
| 模組 SHA-256 | `aca51a31dac8dea9987e8fe746cbbd1734deafabddfaa7fc38a3f81cde44d5da` |
| 重開機 | boot ID `d3eaf26b-6373-4010-a47b-ee89c6fb2d94`，與起始不同 |
| 連續觀察 | 300.042 秒，同一 MainPID=2799、session=1、NRestarts=0；全程 running=1、locked_mask=3、error/error_count/skipped=0 |
| 同一 trace 獨立重播 | 98,182 個事件，無漏紀錄；每眼 9,818 幀、約 30 FPS，SOF／DMA 身分與 trigger 連續性通過 |
| host 完整包絡最大值 | **155.105 µs**，已實際超過舊 150 µs 門檻而被新版接受 |
| host 釋放延遲最大值 | **8.744 µs**，低於獨立 25 µs 上限 |
| Windows 外部解碼 | 兩次各 330 幀 Main10、2176×1280、yuv420p10le，PTS 遞增；第二次約 30 FPS |
| 最終回讀 | 新編譯／已安裝模組 hash 一致，loaded／disk srcversion 一致；串流 active、error=0、skipped=0 |

事件重播的時間跨度約 327 秒，包含開始輪詢時 ring 中已有的約 27 秒事件；受監控的 service/control 視窗為 300.042 秒。這是有限時間板端驗證，不代表長時間穩定性或實體電氣脈寬已獲保證。

## 稽核修正紀錄

第一份 [live-300s/result.json](live-300s/result.json) 保留 `passed=false`：實際服務正常、無事件遺失，但稽核器尚有從舊包絡導出的 low-call ≤50 µs 檢查，拒絕了一筆 51.719 µs low-call。其完整包絡為 155.105 µs，釋放延遲仍合格。

修正為從所選包絡扣掉 100 µs hold 推導必要 low-call 上限，並保留完整包絡與獨立釋放延遲的兩項檢查；對**同一份 trace** 重播後通過，見 [replay-corrected.json](live-300s/replay-corrected.json)。該檔的 `partial_trace_only=true` 表示未使用歷史兩小時 monitor 驗收格式；本次 300 秒連續性另外由全部 samples 與 RESULT.json 核對，沒有宣告兩小時驗收。

## 串流與備份

編譯期間舊模組自行於 session 66、第 5194 pulse 發生 error=14 並停止，狀態保留於 baseline。部署前備份於板端 `/home/ubuntu/sc132gs-envelope-200us-20261016/backup/`，並保存 module／initrd／設定／binary／腳本 hash。部署更新模組及 initramfs 後 reboot，未 hot-unload CAMSS。

開機先依 durable 設定恢復，再將 live brightness 恢復成變更前讀到的 30；durable brightness=40、revision=191 維持。modprobe options、durable YAML／JSON、RTSP binary、兩支 runner 的 hash 均與起始備份一致。最終串流為 Linear 30 FPS、Main10、AE 開啟，保留原 GPU rectification 與 depth 路徑。

## 回復舊模組

目前保留新版運行。若需回復，先停原 restore／RTSP service，再從本次 backup 還原 `0-qcom-camss.ko` 至 `/lib/modules/6.8.0-1084-qcom/updates/sc132gs-csid-monitor/qcom-camss.ko`，還原 `1-initrd.img-6.8.0-1084-qcom` 至 `/boot/initrd.img-6.8.0-1084-qcom`，執行 `depmod -a 6.8.0-1084-qcom` 後 reboot。舊 loaded srcversion 應為 `C243ABE8CAC3FA872B2A08C`；恢復後仍須確認串流及解碼。不要使用其他日期的 backup。
