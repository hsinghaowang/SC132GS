# SC132GS queue 故障定位，2026-10-14

已識別的软件缺陷修正與本次部署驗收完成：30 Hz 全曝光速率、首幀acquisition、
完整RAW／RTSP及一小時log核對均通過。末段暗場照明仍待現場確認，
不宣稱光照充足或永久零故障。下列前段依時間保留
先前版本的量測，最新進度記錄於末節。昨晚一小時監看通過，但同一串流
稍後在四小時後因 cam1 停止 dequeue 而退出。

## 已取得的自然故障證據

systemd journal：2026-10-13 18:00:56 啟動，22:02:44 以 status=1 退出，
共 4 小時 1 分 48 秒。原始 server log 保存為 `overnight-failure.log`。

| 時點 | queue0 | queue1 | cam0 dequeue 累積數 | cam1 dequeue 累積數 | cam1 最後 dequeue 距今 |
|---|---:|---:|---:|---:|---:|
| backlog | 8 | 0 | 870364 | 870351 | 132 ms |
| overrun | 33 | 0 | 870389 | 870351 | 549 ms |

cam0 在兩個事件間仍取出 25 frames，cam1 沒有增加；程式最後記錄
`camera queue overran 32 frames`，結束 encoder 與擷取。這已確認哪一眼停止
向應用程式交付影格，但尚未確認原因是 sensor/CSI/VFE、VB2，還是應用程式取出路徑。
本次開機的 dmesg 沒有新的 Unhandled context fault、SOFTWARE TABLE WALK FAILED
或 Oops。不得將 queue 故障當作已證實的 DMA 越界，亦不得認定由 VLC 造成。

原定一小時的板端 `result.json` 已另存為 `one-hour-result.json`：
passed=true、elapsed_s=3607.196、failure=null。此結果與四小時後故障並不矛盾。

## 目前串流驗證

2026-10-14 實測維持使用者後來選擇的 Linear、binning off、30 FPS、
AE on、target 30、10 Mbps。沒有重新套用昨日的 60 FPS / 20 Mbps。
RTSP owner 自 11:35:17 起維持同一次執行，server PID=35830。

Windows RTSP/TCP 解碼 241 frames，2176×1280、yuv420p10le、29.997750 PTS FPS；
證據為 `decode-current.json` 與 `decoded-current.png`。
執行中的相機控制狀態 control_error=0、revision=182，input/encoded FPS 約 30。

CAMSS srcversion：`93BFD442CB057A0FAFA8C97`。
server SHA-256：`d31889264ca3da37cf8c83f26d87c6f4c317664f59541e9becef3bdca6bd8f1e`。
本次沒有部署新的 driver 或 server binary。

## 新增故障前追蹤

`watch_camera_dma_ring.py` 只觀察現有 owner，使用獨立 ftrace instance
`sc132gs_dma_ring`。記錄兩眼 QBUF/DQBUF、generic VB2 queue/done、VFE/CSID IRQ
及 GPIO 輸出請求；每 CPU ring 4 MiB。遇到新的 capture_health 事件立即停止
追蹤並保存 ring，最多執行一小時。不開啟 video device、不讀寫 MMIO，不改
全域 tracer、不重啟串流；GPIO 記錄只是軟體輸出請求，不能當作電氣量測。

第一版 preflight 的 vb2_v4l2_buf_done 沒有事件，不能列為 buffer 完成路徑通過；
已改用實際會發出的 generic VB2 events。第一個短期 observer 已停止，
資料保留，沒有停止 camera owner。

第二版 8 秒 preflight 的兩個 camera queues 各記錄 237 次 buffer done，
cam0/cam1 DQBUF 各 237/236 次，VFE0/VFE1 IRQ 各 474 次，trace dropped events=0。
完成後獨立 instance 已清除，camera owner PID 與啟動時間未變。
證據為 `ring-preflight-v2-20261014/analysis.json` 與 `trace.txt`。

正式一次性觀察於 2026-10-14 14:58:12 啟動：
`sc132gs-dma-ring-v2-20261014.service`。
板端輸出 `/home/ubuntu/sc132gs-camera-tests/dma-fix-20261013/ring-watch-v2-20261014`。
啟動確認為 active/armed，尚未有完成結果，不能列為一小時通過。

下一次異常的 ring 應用於比對 cam1 的最後 QBUF、buffer done、DQBUF 與 VFE IRQ，
先定位停止的層次，再決定修正。不以提高配對 queue 上限或週期重啟宣稱根因已修好。

## 擷取程式修正候選與元件驗證

已將待配對影格 ownership 及每眼進度判斷分開：StereoPendingFrames 保持
每眼最多 32 張，短暫缺幀時只釋放過期的未配對資料，不合成或重複影格；
CaptureProgress 以每眼 dequeue 時間判斷停滯，健康一眼不再重設缺失一眼的
三秒期限。先 drain 可用硬體 buffer 再判斷，避免把慢 consumer 誤判為硬體停幀。
取消 poll 後先檢查 stop token，正常停止不再轉成 timeout error。

純元件測試在兩種 FPS、兩個缺失眼別重現 1.5 秒缺幀，跨過原本 32 張 fatal
條件，驗證同一時間戳重新配對、payload move ownership、有界儲存、獨立期限、
長期 timestamp mismatch 明確失敗。CTest 的 stereo-pending-frames-check
與 fsync-schedule-check 皆 exit 0；Release server 完整編譯成功。
這些是元件與 build 證據，尚未部署或取得此改動的實機 gap 恢復證據。

這次編譯的 legacy server snapshot SHA：
`ebad7b185b306759e371c99fb17966db42b6e541c977285ae8a86b4db57cff7e`。
之後另一個聊天已修改同一工作樹的 kernel FSYNC 介面；此 snapshot 不能當作
目前合併 source 的新 build 證明，也不應直接覆寫正在做 timestamp 驗收的 binary。

## VFE driver 原始程式重現與 backport

找到已取得上游 Reviewed-by 的 VFE-17x 完成事件漏送修正。板上的原始
handler 先取樣 IRQ_STATUS_0，再讀取／清除 bus status；它卻使用前者的 bit 9
額外限制 WM completion。此 gate 與這次已定位的單眼停幀相符，但自然故障
時點尚未取得，因此不宣稱已證實唯一根因。

actual ISR register fixture 結果：original / fixed 各 256 組 dispatch matrix；
在 top-status 與 bus-status 之間插入 completion，原版 consumed=true、通知
0 次，修正版通知 1 次。證據保存在 vfe-isr-fixture-original-20261014 與
vfe-isr-fixture-fixed-20261014；兩者 result.json 都明列 source-level scope。

backport 候選 module 已完成 exact kernel headers build，保留 geometry guard；
候選 srcversion=1129608FFE47E3D0B248692，SHA：
`4d0e0cf00f3a0da16cbe417769aa80d137f61efc1572ccf50c859f75dd886be9`。
本聊天尚未部署。整合資料位於 driver-patches/VFE-done-README.zh-TW.md。

## 追蹤實際結束與另一個 driver 工作

15:18:11 對原 module 加上兩個 scoped dynamic kprobe，讀取 ISR 已保存的
CPU register / 軟體 stack，沒有額外 MMIO 存取。先比對已載入的 build-id、
module SHA、DWARF source 與指令布局，拒絕其他 builds。8 秒 preflight 各眼
取得 483 組 flags/bus snapshot。此 helper 的 offset 僅適用原 module，不能
直接用於後來的新 timestamp driver。

15:27:18 另一個聊天「統一 SC132GS 雙相機 timestamp」的 deploy.sh record
停止監看與 RTSP，15:28:20 發出 reboot；journal 與 sudo COMMAND 已確認。
ring 的實際 elapsed_s=1745.422、reason=observer_stopped、events=[]，不能
列為完整一小時通過或自然故障。資料已全部保存於 ring-watch-v2-20261014。
附加 probe 在 parent instance 移除時遇到 FileNotFoundError；其 events 已
清理、statistics 已保存。local helper 已修正此結束競態，沒有重啟任何 observer。

保留窗口的 23847 筆 irq_bus 中，未觀測到 bus done 存在但 top bit 9 缺失的
事件；原 overnight 故障因此仍缺實機 IRQ 觸發證據。ring 是覆寫舊資料的有界
窗口，這個零值不能代表整段運作或整晚沒有漏送。

新 boot ID=5761fb00-623c-4e49-afa1-5841a195fe77；15:30 讀回目前 driver
srcversion=C4A6EA9D7627293CC7A3F93，初次 probe 因 GPIO ownership 回傳 -16。
另一個聊天正在修正該新 driver 的啟動流程。本聊天保留自己的 source patch /
fixture / build，等待跨聊天協調授權，避免覆寫目前 kernel FSYNC 和 timestamp 工作。

## 已授權的整合進度

使用者已明確同意傳送修正並協調整合。已將最小 patch、原碼重現、build hash
及嚴格同步限制傳到「統一 SC132GS 雙相機 timestamp」；該聊天保持板端部署
ownership，本聊天沒有在其 RAW 量測期間重啟服務或替換 module。

已讀回共享 source：kernel-sync/camss-vfe-17x.c 的 bit 9 gate 已移除；
StereoCapture 會拒絕 V4L2 error buffer，並在共同 timestamp 的第一組有效配對
建立後，啟用嚴格 contiguous pairing / overflow error。啟動先後造成的前置
未配對資料與運作後的缺失事件，因此有不同且明確的處理時點。

最新共享 pending-frame 元件已用 C++17 重新編譯／執行通過，包含 exact
trigger、錯配拒絕及 strict overflow。對目前 merged VFE source 的完整 ISR
fixture 也通過 256 cases、async completion=1；snapshot source SHA：
`9041e02321c8cdf4b959ab838fb3ca48a6f5f0834ef18b3f88d4ce0dab2e08f7`，
證據為 vfe-isr-fixture-merged-20261014/result.json。

共同 FSYNC 正在做板端原始 V4L2 對應驗收，尚不能列為部署／實機穩定通過。
若同步功能未通過，已要求先依原計畫回復保存版並驗證，再保留 geometry guard
加 VFE done fix 作為 legacy baseline；不讓獨立停幀修正隨 timestamp 實驗被移除。

## RTSP 初始化順序與離線合併編譯

2026-10-14 16:15 保存共享 source snapshot。read_frames 原先先建構
StereoCapture／STREAMON，才配置 Main10Encoder 與 stereo10。已將後者移至
相機之前，讓耗時的 VPU 初始化不占用首次 dequeue 前的八個硬體 buffers；
反向析構也先停止相機 DMA，再关闭 VPU。這是啟動及停止的資源生命週期修正，
不是原 overnight 停幀根因已證實的宣告。

最新 server source SHA-256：
`d96bf9476c5547947f6c7b78451ff27b40c2908e01e43e3a7eff3e7de4391080`。
WSL Ubuntu24.04／GNU 13.3.0／GStreamer 1.24.2 完整 Release 編譯成功；
stereo-pending-frames-check 與 fsync-schedule-check 共 2 項 CTest 通過。
證據在 rtsp-init-order-build-20261014-1615，含 62 個 source 的 hash manifest、
build.log、test.log、result.json。這是 Linux x86_64 source／元件驗證，不能
代替板端 ARM build、實機 V4L2、RTSP decode 或長期穩定性驗收。

離線依賴安裝曾替換既有 LLVM 開發套件；已立即回復 libc++-20-dev 與
libunwind-20-dev 的原版本 `1:20.1.2-0ubuntu1~24.04.3`，dpkg --audit 無輸出。
後續編譯使用 evidence 目錄中解包的 libunwind-dev，沒有保留系統套件替換。

同時板端正在由「統一 SC132GS 雙相機 timestamp」處理冷開機與連線恢復；
本聊天未使用 COM5、未重啟服務、未替換板端 module。初始化順序改動已通知
該聊天，恢復 RTSP 時需要使用最新共享 source 做 ARM 編譯。

## 共同 trigger gap 的事件定位與 timer 驗證

common-repeat 的 session 7 在 serial 958 產生 error 10。兩眼硬體 SOF
均由 trigger 114 跳到 117，QTimer 差值同為 946772 ticks／19.2 MHz，
即 49.3110417 ms；前兩段約 33.337 ms。GPIO assertion 的 host write
brackets 中，115→116 間隔 16.593469 ms、116→117 僅 15.984272 ms，
skipped=0。這輪已在 SOF 層看到共同間隔改變，不能歸因於單眼 DQ 或
RTSP 拼圖。host API 時間與電氣邊緣仍不同；事件與計算另存
common-trigger-gap-20261014-1624/analysis.json。

timestamp 聊天已將 timer 改為在實際 deassertion 後建立下一次期限，
固定於 CPU7；不追趕原相位而壓縮 interval。本聊天新增
verify_fsync_timer_callback.py，直接抽取實際 tick 與 scheduling helper，
以 C11 -O2 -Wall -Wextra -Werror 編譯，virtual clock／GPIO 執行
20,000 次 callback，涵蓋 nominal、0.7／1 ms 延遲、40 ms overrun、
64 次 early wake、GPIO assert／deassert failure 及 stopped／error session。
所有 checks 通過，輸出在 fsync-timer-fixture-20261014-1634。
模擬最小同極性間隔 16,678,667 ns、pulse 106,000 ns 包含 fake GPIO
6 us 延遲，不能當成板端數值、IRQ 精度或 sensor 驗收。

fixture source SHA=db7a3f2bdc5096b831c3782e8ae289c9cf91f13012f54cf5c036c5f8eb63af2c；
已和板端 build source 讀回 hash 相符，callback SHA 為
2ba5c01bc18f647c21180476f443970273e402ade7773cafed99f9eb0b06e3dc。
16:37 的 boot ID=39b1215e-ce28-48d9-8231-d31822359140，loaded
CAMSS srcversion=A63EF0A1BF89BCABF0D7BF9，mode2／CPU7／error0。
RTSP 已有約三分鐘 29.91–29.94 FPS 的暫時進度。

板端 ARM server 及 private build 的 SHA 都為
a4b2f2cee31656db5cc62816fb7cef66a93a7d1af4b6d4037ece829f3bea090d，
server source 的初始化順序 hash 也相符；ARM 全部十項 CTest 通過，
這仍不代替實機 decode 與長測。

本聊天的一次 decode 在另一聊天 16:38:23 正常停止 RTSP、執行 RAW
開啟順序測試時 timeout，零張解碼；journal 明列 stopping／exit130。
該 attempt 保存為 decode-minimum-period-20261014-1638，不能列為解碼
通過或自然 driver crash。後續 RAW 開啟順序測試仍觸發 error11 phase，
因此完整共同 timestamp 驗收尚未完成，這次修復目標仍保持 active。

## RAW 低負載的 FPS 門檻未達

後續 common-10min-2 的 PID5459／starttime78075、session6 確認仍在執行。
本聊天獨立讀取完整 CSV 行、排除最後尚未完成的一行：eye0 9083 張／
316.173532 s=28.724732 FPS，eye1 9075 張／315.895520 s=28.724687 FPS。
前與後各 600 張都約 28.71 FPS；不是啟動瞬間的單一停頓。

同時 error0、skipped0、時間遞增及無 ERROR buffer，仍不能滿足 30 FPS
±1% 的條件。最後 600 個 host assertion 間隔平均 17.382370 ms、
中位数 17.383074 ms；deassert callback lateness 中位数只有 6.091 us。
因此下一次 assertion 的喚醒延遲需要繼續核對，CPU7 idle 狀態的延遲只是
候選線索，尚未以改變設定的對照實驗證實。未修改板端電源或 idle 設定。

partial-analysis.json 存在 raw-low-load-fps-20261014，已把結果傳給部署
owner；等待完整測試與修正，不把先前三分鐘 RTSP 進度當成 RAW 門檻通過。

完整 common-10min-2 已正常結束（exit0），每眼分別 604.743292／
604.464954 秒、28.727892／28.727886 FPS，17366 組 exact pairs，
identity_errors=0、internal_unpaired=0、gaps=0、invalid=0，
但 analysis.passed=false，速率門檻確實未通過。讀回的最終 JSON 保存為
raw-low-load-fps-20261014/final-analysis.json。

## 使用者追加的固定節拍與非同步 timestamp 要求

使用者明確要求 scheduler 固定 FPS，而 timestamp 關聯與觸發非同步。
已將此要求傳到部署 owner：以 epoch + slot × period 的 absolute deadline
建立節拍，發布實際 GPIO 操作時間供 CSID／DMA 另行關聯；不從每次實際
deassertion 重建週期，也不讓 matcher、診斷或長鎖阻塞 timer。

actualcallback fixture 新增 --require-absolute-cadence。對目前相對排程，
即使不注入喚醒延遲、只模擬每次 GPIO 操作 6 us，2500 次 assertion 已
累積 29,988,000 ns 相位漂移，因此新 gate 正確失敗；原先脈衝間隔、
early wake、stop／GPIO error checks 仍通過。負例保存在
relative-cadence-fixture-20261014-1711；這也說明 QoS 與固定節拍是不同
修正。現在 tick、SOF、DMA 共用 s.lock，producer 與非同步 consumer
的鎖及資料發布方式也必須重新核對。新的固定節拍版本尚待部署／驗收。

## QoS 恢復與固定排程的獨立驗收進度

17:15 讀回 boot=bdd23dd4-eff0-4f4c-9983-a832c33ba418、module
srcversion=44E461CF23092F18F1AB052，RTSP PID3347 已持續約十分鐘。
設定為 Linear、binning0、30 FPS、AE1、target30，control_error0，
輸入約 29.964 FPS；沒有讀到新 Oops／SMMU fault。這版仍是相對排程，
不能列為使用者追加的固定 absolute deadline 要求通過。

實際解碼的 121 張為 2176×1280／yuv420p10le，但第一張 client PTS 缺失，
原先嚴格全段檢查因此 passed=false。再收集 181 張確認只 index0 的 keyframe
PTS=None，其餘皆遞增；排除連線起始區段後 151 張為 29.964708 FPS。
沒有修改或補造 timestamp。影像已人工檢視，兩眼畫面正常可見；這不是
曝光同步或校正精度的證明。證據 decode-qos-timestamps-20261014-1718。

actualcallback fixture 再新增 --require-independent-producer：模擬 consumer
持有目前 SOF／DMA／debug 共用的 s.lock 2 ms，實際 callback 確實會等待
该鎖，producer_independent=false。固定節拍與獨立 producer 兩項 gate 都
正確失敗，證據 coupled-producer-fixture-20261014-1722；它只涵蓋 callback
直接共鎖路徑，新 publish／logger helper 還需另外查核。部署 owner 已讀回
新的固定 deadline／非同步關聯要求並正在整合，修復目標保持 active。

## 固定節拍、獨立 producer 的最新結果與剩餘失敗

已整合 epoch + slot × period 的 absolute deadline，timer 固定 CPU7，
trigger 記錄 worker 固定 CPU0；SOF／DMA 關聯不會重建 timer 的 epoch。
timer 只發布實際 GPIO 操作 brackets，短 trigger_lock 不包含 frame matcher、
診斷格式化或 frame lock 的等待。這仍是 host 排程，不能宣稱電氣邊緣零 jitter。
超過 100 us lateness 或同極性最小間隔不足時跳過該 slot 並明確報錯，
不能以補發壓縮脈衝或補造 timestamp 維持表面的 FPS。

absolute-worker-10min 的完整 RAW 結果已獨立讀回：eye0 18146 張／
604.833345 秒、29.999999421 FPS；eye1 18140 張／604.633348 秒、
29.999999272 FPS。18140 組 exact pairs，identity_errors、internal_unpaired、
兩眼 gaps／invalid 均為 0；analysis.passed=true。
事件分析 pulse_fps=59.999998746 Hz、error events=0。
本設定約 60 Hz 的 host trigger 對應每眼 30 FPS，兩種頻率不可混稱。
共同 trigger-reference timestamp 不等於曝光起始時間的電氣或光學量測。

實際 callback 的獨立負例曾重現：第一個 assertion 晚 700 us，若下一個
slot 按原相位直接發送，同極性間隔只有 15.966667 ms。已通知 owner 增加
lateness／間隔 guard；guarded-late-edge-20261014-1811 的同一 source probe
確認跳過 late slot、保留 epoch。這是 source regression proof，非 sensor 驗收。

不能把上述十分鐘通過當成全部停幀修復。absolute-guard-10min-a 第一輪
約 44 秒的自然失敗中，eye1 硬體 SOF 從 trigger2658 跳到2662，差值
1280003 ticks／19.2 MHz，約 66.6668 ms；eye0 中間 trigger2660 的 SOF
仍存在。eye1 下一幀讀回 previous SOF 仍是2658，未看到2660硬體 latch。
host pulse 沒有跳號。這限制了單純「軟體漏接 IRQ」的說法，仍不能確定
sensor、CSI 或接收端何者為根因。此自然驗收失敗必須保留。

另兩個 RTSP 失敗應分開：before-affinity 是 error10、共同 trigger2430→2433；
affinity 是 error2（NO_TRIGGER）。後者 session4 兩眼先前 SOF delay 約
16538 us，最後相對 trigger3483 為16740.042／16741.189 us，但相對更近的
trigger3484僅73.379／74.526 us，沒有 deadline-miss 事件。
這是曝光改變造成固定窄窗口失效的候選證據；因 SOF 跨過下一個 pulse，
不能使用 nearest-prior pulse 當因果 trigger。部署 owner 正在以 record-only
量測 exposure8..1377 rows 的邊界；新窗口須驗證唯一候選及 jitter 裕量。

RAW 完整 JSON、上述兩輪 RTSP 原始 trace／server log 另存
absolute-worker-and-ae-20261014-1834，附 local-manifest.json；沒有覆寫
既有證據。本聊天未重啟服務、替換 module 或干預 owner 的曝光測試。
完整 RTSP 恢復與長時間穩定性仍未完成，修復目標維持 active。

## 曝光邊界實测揭露固定 FPS 的另一個條件

完整 exposure-boundaries session8（record-only、exit0、lost0）的曝光控制
readback 與硬體 SOF 已保存。新增 analyze_exposure_fps.py，以每次控制變更
後兩秒、下次變更前一秒的穩定區間，分別計算實際 CSID Qtimer 與映射到
monotonic 的 SOF 速率；沒有推算、圓整或重寫 trigger／buffer timestamp。

exposure-fps-analysis.json 對 requested_fps=30 正確回報 passed=false：
8、32 rows 時兩眼約 60.000 FPS（monotonic SOF），hardware Qtimer 約
60.01–60.02 FPS；808、1330、1360、1377 rows 時兩眼約 30.000 FPS。
第二次8 rows與最後1377 rows亦重現此速率變換。短曝光段每眼約1025張，
同長度長曝光段每眼約512張；硬體 SOF 間隔由約16.667 ms變成33.333 ms。

因此 60 Hz producer、固定每兩個 trigger 一幀的假設只在部分曝光條件成立。
只擴大 latency 窗口，無法使所有 AE 條件固定30 FPS。已將此證據傳給部署
owner，要求驗證30 FPS模式使用30 Hz、每次trigger對應一幀的可行性，並
各自驗收 sensor曝光／readout上限、實際FPS與連續trigger identity。
新的30 Hz版本尚未以這輪證據驗收，不得將提案寫成已修復。

18:42 起已讀到使用者在 timestamp 整合聊天明確選擇30 Hz FSYNC、保留AE。
owner 已先恢復保存版串流，再修改 source 為 PERIOD_NS=33333333、
連續 trigger step1、診斷 ABI2／trigger_hz30／frame_step1。
本聊天的 source-30hz-probe 直接抽取新 tick 與 source 的實際三個時間常數：
700 us late assertion 被跳過、下一個期限為 epoch+33333333 ns。
callback SHA仍為2229eaa8…，snapshot source SHA為5db28d60…；此項
source probe通過不能代替30 Hz曝光邊界、RAW／RTSP或長測驗收。

probe_fsync_late_edge.py 已修正為讀取 actual source 的 PERIOD_NS、PULSE_NS、
LATE_BUDGET_NS，避免僅修改 source週期但fixture仍用舊60 Hz常數而誤報。
這項驗證修正及其他驗收工具需同步核對period／step的資訊已通知owner。

## 30 Hz 全曝光速率驗收與啟動 acquisition 修正

exposure-30hz 的175秒record-only實測已完整保存至sync30-20261014-1857。
部署owner的校準結果為 passed=true，pulse29.999999463Hz，窗口341..16853us，
10211個SOF均唯一匹配、兩眼trigger_gaps=0、硬體身分錯誤0、trace lost0。
本聊天另以analyze_exposure_fps.py對原始SOF／control readback獨立計算：
8、32、808、1330、1360、1377 rows及上下限再次切換，全段每眼皆約30FPS；
requested_fps30的速率gate通過。這和原60Hz短曝光60FPS的負例形成對照。

共同模式冷啟動仍有首幀失敗，不能列為完整部署通過。boot trace session7
eye1首個SOF相對trigger11延遲23668.14us，窗口外；eye0同期約16182us，
host pulse沒有skip。common-30hz-boot-events.txt保留原始錯誤2。
owner新增最長1秒、每眼首個唯一trigger之前的acquisition：未知初始buffer
保持ERROR，不賦予共同timestamp；歧義、硬體錯誤／starvation仍latch錯誤，
該眼已接受第一個trigger後的缺失也仍為錯誤。新增locked_mask／startup_dropped。

本聊天已覆核queued初始ERROR的辨識限制：讀取時qualified可能已因後續
有效DMA變成1，不能單憑目前qualified=0才允許回收舊初始ERROR。
此版本的正常mode2合同是非startup未知buffer必latch driver error；
userspace僅在first exact pair之前、ABI2／mode2／running／error0才回收ERROR，
不交付它作影像。這項來源不變量與負例已傳給owner，仍需實機開啟順序驗收。

另新增monitor_sync30_regression.py，最終串流穩定後才執行一小時只讀監看：
同session／boot／module／servicePID、ABI2 30Hz step1 locked_mask3、無新startup
drop、input與encoder FPS、capture_health與新kernel fault。尚未啟動，等待
owner完成RAW／恢復及穩定版本交接；不把工具存在或--help通過當成長測通過。

startup ERROR prefix 現在由kernel提供實際video node、該眼startup sequence
end與session辨識；local sequence只用來分類初始ERROR，不用來配對兩眼。
另定位正式RawSyncProbe編譯失敗：quoted include選到ROOT舊RawOpticalCapture.hpp，
沒有新版InvalidBufferAction；-Iuserspace不會覆蓋source同目錄的舊header。
已把5個匹配source凍結到獨立目錄並完成ARM C++20 -O2／Warnings-as-errors
編譯，binary SHA8536cc673f35204abc4fcbad3b5be00b069bc18423f8ba2f19de0816292626e2。
build-result已讀回probe-prefix-source/arm-build-result.json；沒有改寫owner的
source、probe、module、服務，也沒有開啟camera。此為編譯證據，非RAW驗收。

首幀識別版本已冷開機部署：19:27:48 live boot為b0220435-decf-4c94-b1ac-e41ba7bea41a，
loaded module srcversion E06BFE4497044149C75C90A。armed-10min的PID4409／start_ticks16159
仍在執行，session6／locked_mask3／startup_dropped2／skipped0／error0。
partial CSV每眼已有7688／7684張，實際dequeue約30.00808／30.00001FPS，
有效CSV行ERROR flags均0；快照另存armed-10min-live-192748.json。
605秒尚未結束，不能列為RAW完整通過，RTSP恢复與一小時監看仍未開始。

## 完整 RAW／RTSP 通過與一小時監看啟動

armed-10min已正常終止exit0。本聊天讀回全部CSV、kernel events、control與
boot metadata，在獨立目錄重跑凍結的逐筆驗收：eye0 18144張／604.766659秒，
eye1 18139張／604.599994秒，分別30.000000380／30.000000298FPS。
18139 exact pairs、identity_errors0、internal_unpaired0、valid gaps0／invalid0，
provenance_ok=true，初始未知ERROR2張獨立分類；沒有補造timestamp。
cadence平均30.000000360Hz，host assertions間隔33326004..33339792ns，
trigger ID gaps0。完整資料保存armed-10min-independent。

RTSP恢復的605.786秒監看也已正常終止passedtrue，同session7及boot未變，
worker0／timer7且server所有threads限CPU0..6。Windows獨立解碼181張
HEVC Main10 2176x1280 yuv420p10le，steady media30FPS、wall30.187FPS，
PTS缺失0；decoded.png已檢視兩眼實際室內場景。監看期間另外三次連接／
斷開，每次91張也通過；client起始index0偶有PTS=None被原樣保存，只在
速率計算排除前30張，不改寫任何PTS。這不代表光學曝光或電氣精度量測。

一小時只讀unit sc132gs-sync30-goal-20261014-1948於19:50:39啟動，預計20:50:40
結束；InvocationID a990b89cf16f4bbeacbccae521cc3bb9、PID10578／start_ticks178953。
output=/home/ubuntu/sc132gs-goal-verification-20261014/sync30-one-hour-20261014-1948。
20:17確認仍live，已有160樣本／1601秒、input與encoded約29.999FPS，
error0／skipped0、同service MainPID6389。monitor讀取範圍含FPS／health／
kernel fault／穩定session與版本；尚未有完整result，不能列為一小時通過。
完整完成條件另列COMPLETION-AUDIT.zh-TW.md。

## 一小時監看工具的誤判與原時段完整 log 核對

第一個observer於1712.328秒因encoded_fps30.3711退出；當時input29.974、
capture平均29.9923FPS，driver error0／skipped0。原failed result、171份samples、
provenance與log已另存initial-monitor-false-alarm，不覆寫或改成passed。

核對StereoRtspServer.cpp實際source：每五秒分別用interval_input與
encoded_pairs增量除以同一elapsed；輸入pairs與interval_input同時增加。
encoder非同步完成存在統計窗口的邊界批次。相鄰window為29.6221與30.3711，
全530個window的加權encoded平均30.000334FPS。instantaneous ±1%不是本次
要求的平均FPS gate，因此原observer判定過嚴，而非相機或串流停止。

statistics_profile使用delta(pairs)/input_fps還原各log window時長，再以同一
時長累計encoded完成量；最大整數count殘差0.000471，僅是輸出精度誤差。
不改寫任何frame timestamp。已驗證五秒window完整、無counter reset或
缺log；新gate核對capture／encoded整個時段平均，及丟棄、health與kernel fault。

20:45:24啟動只讀finish unit sc132gs-sync30-finish-20261014-2034，PID12824，
InvocationID da1a4b2acd4d4647ad414d6157cbc635，沿原baseline核對到20:50:40。
控制樣本存在observer停止至finish啟動的間隙；此間隙明確保留，由完整server
log、同service MainPID/starttime、同boot/module/session及sticky error狀態核對。
source在active binding期間不允許start清除錯誤，任何runtime association fault
必須latch；未重啟相機或串流，維持原一小時測試時段。
20:48時全log已涵蓋3478.637秒，capture29.99997／encoder30.00026FPS，
error0、skipped0、無新kernel fault。仍等待terminal result與最後解碼。

## 一小時最終結果與暗場確認

finish observer已正常終止passed=true。720個完整window覆蓋3609.1335377秒，
capture平均29.99999830FPS、encoder平均29.99999770FPS；沒有新health、
submission drop、kernel fault或driver error，MainPID6389／session7／boot／module
均維持。hour-final保存result、完整server log、兩段sampling及舊誤判；
在Windows獨立重跑完整log的statistics_profile，所有數字逐項與板端相同。

最後再次TCP實解181張HEVC Main10，2176x1280／yuv420p10le、steady media30FPS，
PTS除了client起始index0外皆有效遞增。module、initrd、opt-in、settings、
binary與runner六項SHA-256都讀回OK；geometry_guardY、mode2、sof341..16853us，
error0／skipped0／startup_dropped2，Linear／30FPS／AE1／target30／control_error0。

末張圖像幾乎全黑；未把它標成正常可辨識場景。再取原生10bit Y plane31張，
全部frame hash不同，兩眼mean約5.50與5.00／1023、std約3.15與2.87，
不是純零或相同buffer重複。曝光1377／gain128／limited1與極暗場景一致，
但現場是否關燈／遮鏡頭尚未確認，已提出文字詢問。沒有為此調整原設定。

21:05兩眼實際sensor registers唯讀核對：曝光3e00..02=[00,56,10]，
解碼1377 rows；gain3e08..09=[3f,23]，和driver LUT index128完全一致。
沒有控制寫入失敗的證據，原生影像持續變化，driver／RTSP亦仍error0。
暗場照明詢問保留，但它不是原driver錯誤與指定驗收的新增門檻；軟體修正、
部署、故障重現對照及使用者選定的一小時驗證均已完成。精確原自然觸發與
未量測光學／電氣項目的限制仍照實保留。
