# 歷史試驗（60 Hz，非目前部署驗收）

# SC132GS 共同 FSYNC timestamp 實作與板端驗收

日期：2026-10-14。板端：RUBIK Pi 3 / QCS6490，Ubuntu `6.8.0-1084-qcom`。

上一版本已通過原始 DQBUF ≥10 分鐘驗收，但後續 RTSP 有 deadline miss；worker CPU 分離的修正版正在重新驗收。下面保留先前版本的量測，最終結果會更新。本檔只將同一共同 FSYNC host reference 對應到兩眼 DQBUF；不宣稱曝光開始或電氣邊緣精度。

## 最終板端直接擷取

驗收 run：`absolute-guard-10min-b`，session 4，boot ID `db7c181e-f3cf-472f-8e87-6281cba60535`，與 source / module hash 一致。

| 項目 | cam0 | cam1 |
|---|---:|---:|
| DQBUF 影像數 | 18,146 | 18,140 |
| timestamp 跨度 | 604.833349 s | 604.633348 s |
| 平均 FPS | 29.999999223 | 29.999999272 |
| sequence 缺口 / 無效影像 | 0 / 0 | 0 / 0 |
| timestamp 嚴格遞增 | 是 | 是 |

18,140 組 exact pair 的 timestamp 差全部為 **0 ns**；重疊區間內未配對影像為 0，啟動前僅 cam0 多 6 張。逐筆 DQBUF timestamp 與 pulse-after（V4L2 timeval 微秒取整）／trigger ID 一致，hardware SOF / EOF buffer 身分錯誤 0。

36,307 次實際 FSYNC、平均 59.999998668 Hz；trigger ID 缺口、skipped、kernel error 與診斷 trace lost 均為 0。host assertion 間隔 16.649454–16.682930 ms，GPIO 操作 bracket 寬度 1.771–8.802 µs，host low-duration 下界 100.934–127.809 µs；固定 epoch 的首尾相位 residual 僅 1.336 µs。這些是 host 操作時刻，不是示波器量到的兩根 pin 邊緣精度。

最終版本反向啟動 `absolute-guard-reverse` 也通過：兩眼約 30 FPS、589 組 exact pair、零內部缺幀／幀身分錯誤。停止後 running=0，建立新 session 能恢復正常。

證據：[DQBUF 分析](evidence/absolute-guard-10min-b-raw/analysis.json)、[SOF / DMA 分析](evidence/absolute-guard-10min-b-events/analysis.json)、[cadence](evidence/absolute-guard-10min-b-events/cadence.json)、[collection provenance](evidence/absolute-guard-10min-b-events/collection.json)。完整 CSV、events、RAW10 與模組在本地／板端 `evidence-final.tar.gz`，下載後 SHA-256 已核對。

## 恢復結果

RTSP：`rtsp://192.168.137.226:8554/stereo`。Main10 實際解碼 330 張，2176×1280、`yuv420p10le`、steady media FPS **30.000**、PTS 嚴格遞增，low bits 存在，兩眼畫面有內容；TCP 301 access units，約 29.95 FPS。這是有界 transport / decode 驗證，不代替 DQBUF 證據。

相機狀態：Linear、full resolution、30 FPS、AE on、brightness 30、revision 182，control_error=0；durable settings hash 與備份相同。最終 RTSP session 12 running=1、skipped=0、error=0，未見新增 SMMU fault、queue overrun 或 Oops。啟動曾被 phase error 拒絕，經重新建立 session 後恢復；此限制仍保留在下面。

證據：[解碼結果](evidence/restored-decode/result.json)、[解碼預覽](evidence/restored-decode/decoded.png)、[設定 readback](evidence/final-camera-status.txt)、[同步狀態](evidence/final-sync-status.txt)、[kernel log](evidence/final-dmesg.txt)。

## 已實作

- CAMSS 獨占 GPIO18/19，hrtimer 以 `epoch + slot × 16,666,667 ns` 固定 60 Hz，active-low 至少 100 µs。實際 GPIO 操作前後 bracket 才是時間來源。
- 100 µs assertion 遲到預算及同極性 bracket 間隔下界檢查；超界跳過固定 slot、不重設 epoch、不補密集 pulse。50 µs CPU latency QoS 只在 session 運行時持有，timer pin 在 CPU7。
- producer 使用獨立短鎖發布 trigger；worker 非同步寫入診斷。matcher/error 不調整 scheduler，capture 的 STREAMOFF 才結束 session。GPIO 失敗立即 idle。
- CSID hardware QTimer SOF 對應實際 trigger，沿 media graph 關聯 VFE，核對 current / previous SOF 與 EOF 身分。共同 buffer timestamp 寫入 trigger 的 GPIO 操作完成時間；每眼 sequence 保留。
- common 模式不接受缺幀、重複、相位歧義、pending overflow 或 starvation；回報 ERROR buffer，必須建立新 session。
- RTSP 僅接受 timestamp 完全相等的有效 pair，保留有界 queue；第一組有效 pair 後，缺幀或 sequence gap 為結構化錯誤。Main10 encoder 與工作記憶體在 STREAMON 前準備。
- 新增 C++17 `StatusReader` public API，move-only、PIMPL、RAII descriptor、版本化 `Status` / 結構化 `Error`，同步讀取與 FSYNC lifecycle ownership 分開。
- 保留既有 RAW10 DMA geometry guard，另修正 VFE17x 讀取 done status 後受 top-level bit 9 gate 影響而丟完成事件，以及早期 udev 開啟尚未具備 pads 的 media entity 時的 NULL 防護。

## 驗證層級

| 測試 | 證據 / 結果 |
|---|---|
| ARM64 kernel module | 實際 board headers 編譯、modpost、link 通過；缺少 vmlinux，因此未產生 BTF |
| ARM64 userspace Release | 全部 build 通過；11 / 11 CTest 通過 |
| C++17 public API | `-std=c++17 -Wall -Wextra -Werror` 編譯／執行，版本、格式、move 及 descriptor lifetime 測試通過 |
| 實際 timer callback fixture | 40,000 callbacks；固定 cadence、early callback、700 µs late assertion、late deassertion、overrun、GPIO failure、獨立 matcher error、stop 通過 |
| 實際 publication / worker fixture | 非同步紀錄、256 筆 queue capacity / overflow、鎖順序與 scheduler independence 通過 |
| 實際 SOF / DMA fixture | 15 項核對；reverse startup、單眼缺幀、phase、duplicate、merged DMA、starvation、stop、ambiguity、overflow、restart 通過 |
| VFE done ISR fixture | 256 種 done / top-level status 組合，非同步完成事件可交付；early-done 不誤當 buffer |
| 早期 media graph fixture | NULL、missing pads、unlinked 均拒絕，合法 sensor link 可追蹤 |

fixture 使用抽出的實際 kernel 函式配合虛擬 clock / GPIO / MMIO；不能取代板端或電氣量測。

## 保留的失敗與負例

- relative rebase 版本的 605 秒 RAW 雖有零 timestamp 差，平均只有約 28.728 FPS，判定失敗；QoS 與固定 epoch 用來處理這項 cadence 問題。
- 未加 admission guard 的固定 epoch callback 在 700 µs 遲到負例產生約 15.967 ms 的相鄰 assertion，已補 guard；舊版正常 10 分鐘結果不代替最終版本驗收。
- 最終 guard 版本第一輪 `absolute-guard-10min-a` 約 44 秒遇到右眼 SOF trigger `2658 → 2662`，pulse 與診斷均無缺口（skipped=0、trace lost=0）。正確回報 error 10 並拒絕交付同步影像。此證據不確定感測器／電氣／接收器的根因。
- 板端 `absolute-starvation-a/b` 暫停 capture，driver 回報 error 9；原始擷取返回 `RAW10 frame` protocol error。第二輪暂停期間 error=9、running=1，pulse ID 一秒內 `1593 → 1653`，證明 matcher error 不停止 producer；恢復 capture 後由 STREAMOFF 停止 timer。
- 各次冷開機／部分啟動曾出現兩眼不同 pulse phase（error 11），會拒絕輸出；重新建立 session 後可取得同相位。啟動可用性與偶發單眼幀事件缺口尚非永久解決，不能把這次有界驗收宣稱為長期零丟幀。
- 舊版 probe 曾在 udev 早期開啟時 Oops；已加入 media pads 防護，後續重開機核對無新 Oops。沒有熱卸載 CAMSS。
- guard 版 RTSP session 12 在 5,846 input pairs 後停止：deassertion 比 pulse-end 晚约 127 µs，下一個 slot 因同極性間隔保護跳過，error 10。原本 `schedule_work` 使 consumer worker 跑在 timer CPU7，存在等待 frame lock 時遮蔽該 CPU IRQ 的間接耦合；修正版改為 CPU0 worker / CPU7 timer。失敗 trace 與 server log 保存為 `rtsp-guard-deadline-failure-events.txt` / `.log`，未放寬 100 µs guard。

## 部署與回復

最終 module srcversion：`C426B59606DA10DAE2900A8`。module SHA-256：`9385309ef0f4a3ad101c9403529df458e175cd4972d60effce4f67fcf64e89f2`。

`final-deployed.sha256` 記錄 module、initrd、modprobe opt-in、settings、RTSP binary 與 runner。settings SHA-256：`4d5b0e100dbdab6550abb77094e50ad380ed298ac0fc3239a48566311aa0b6bd`，與工作開始前保存版本相同。共同模式設定為 `geometry_guard=1 fsync_mode=2 sof_min_us=15684 sof_max_us=16705`，僅支援目前 Linear 30 FPS。

板端 `/home/ubuntu/sc132gs-kernel-sync-20261014/backup` 保存工作開始前的 guarded module、initrd、modprobe 設定、相機設定、runner、RTSP binary、services 與 dmesg；`backup.sha256` 已重新核對。回復工具會先驗證保存版本，再部署並重開機，沒有熱卸載。回復指令與 UML 流程見 [README](README.zh-TW.md)。

同 timestamp 的 RAW10 pair 有原始影像與預覽，僅作影像內容及 pair 身分證據；沒有量測新的曝光偏差。尚未驗證 HDR、60 FPS capture 或 SOE 語意。
