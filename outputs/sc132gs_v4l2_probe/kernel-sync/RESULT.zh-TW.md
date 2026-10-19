# SC132GS 30 Hz 共同 FSYNC timestamp：完成與板端驗收

日期：2026-10-14。RUBIK Pi 3 / QCS6490，Ubuntu `6.8.0-1084-qcom`。**新版已重開機載入（未熱卸載 CAMSS），原始 V4L2 及恢復 AE／RTSP 後的 10 分鐘驗收均通過，串流持續運行。** 使用者已確認改採 30 Hz，一個 pulse 對應一幀；保留 Linear 30 FPS、兩個 video nodes 與 full-resolution RAW10。

## 原始 V4L2 驗收

run `armed-10min`，session 6，boot ID `b0220435-decf-4c94-b1ac-e41ba7bea41a`。每眼排除 1 張未知啟動 ERROR，不指派 trigger ID 或共同 timestamp。以下只計有效影像：

| 項目 | cam0 | cam1 |
|---|---:|---:|
| DQBUF 張數 | 18144 | 18139 |
| timestamp 跨度 (s) | 604.766659 | 604.599994 |
| 平均 FPS | 30.00000038031197 | 30.0000002977175 |
| sequence 缺口 | 0 | 0 |
| 無效影像 | 0 | 0 |

**18,139 組 exact pair 的 timestamp 差全部為 0 ns**；重疊區間未配對影像 0。cam0 啟動较早多 5 張，沒有跨 trigger 配對。時間嚴格遞增、逐筆 DQBUF 對 kernel trigger ID / GPIO-after（V4L2 timeval 微秒取整）一致。run exit=0、trace lost=0、同一 boot/session，無 fatal sync error 或 skipped pulse。

[逐筆驗收結果](evidence/30hz-final/armed-10min-raw/analysis.json)與[同 timestamp RAW10 內容預覽](evidence/armed-10min-raw/pair-preview.png)已保存；預覽只是 8-bit 灰階，原始 RAW10 及 hash 保留。

## AE／RTSP 恢復驗收

- 保存設定完整恢復：Linear、30 FPS、AE on、brightness target 30、gain cap 128；settings SHA-256 `4d5b0e100dbdab6550abb77094e50ad380ed298ac0fc3239a48566311aa0b6bd` 與備份相同。原有 Linear30 readout budget（8..1377 exposure rows）保留。
- RTSP session 7，狀態監測 605.786 秒、605 個樣本：同一 boot/session，locked mask=3，startup dropped=2 持續不變，error=0、skipped=0、服務重啟=0。producer CPU7、worker CPU0，所有 server threads 限於 CPU0..6。
- TCP client 在 605 秒接收 580,624 RTP packets / 18,152 H.265 access units，30.00 FPS。kernel trace lost=0，SOF trigger gaps=0、對應歧義=0、hardware buffer identity errors=0；各眼約 30.000000 FPS。
- 驗證前後各解碼 330 張：Main 10、2176×1280、`yuv420p10le`，有效 10-bit 低位資料，PTS 嚴格遞增、30.000033 FPS。左右畫面內容正常；[最後解碼畫面](evidence/rtsp-armed-decode-after/decoded.png)。
- server dropped FPS=0，未新增 queue overrun / backlog / capture gap；本次開機 dmesg 無 SMMU context fault、table walk failure 或 Oops。

[監測結果](evidence/30hz-final/rtsp-armed-10min-monitor/result.json)、[trace 核對](evidence/30hz-final/rtsp-armed-10min-trace/analysis.json)、[最終狀態](evidence/30hz-final/final-30hz-state-result.json)與[Main10 再次解碼](evidence/rtsp-armed-decode-after/result.json)可直接審閱。這是有界驗收，不宣稱永久零丟幀或已解決所有多小時自然故障。

## 實作與故障處理

CAMSS 元件獨占 GPIO18/19，active-low 100 µs，使用不 sleep 的 GPIO API 與固定 epoch 的 hrtimer。保存實際 GPIO 操作前後 bracket；延誤時跳過舊 slot、不補發密集 pulse。50 µs CPU latency QoS 只在運行期間持有；diagnostic worker 與 producer 分 CPU，避免 association lock 延誤 producer。

沿實際 media graph 綁定 CSID / VFE；hardware QTimer SOF 映射到 CLOCK_MONOTONIC，搜尋量測窗口內唯一實際 trigger，再核對 current / previous SOF / EOF 與 DMA buffer 身分。每眼原有 sequence 保留；sequence 不作 stereo pair 身分。buffer 交付前寫入共同 trigger reference。

上游 STREAMON 全部成功後才 arm；arm 前及 arm 後第一張未知硬體影像，一律 ERROR，即使恰好落在窗口也不指派 trigger。啟動辨識限 1 秒；consumer 僅在第一對有效影像前、同 session、global error=0 且位於診斷公布的 per-node ERROR sequence 前綴時丟棄。首次可信幀後缺失、重複、歧義、overflow、starvation 或 hardware identity 錯誤均鎖住 session，拒絕有效同步輸出，完整停止重啟才恢復。

新增 C++17 `StatusReader` 是 move-only / PIMPL / RAII，回傳版本化 `Status` / 結構化 `Error`；只讀診斷，不擁有 FSYNC lifecycle。RTSP 在共同模式只接受 timestamp 完全相等的有效影像，仍保留有界 queue 和逾時診斷。Main10 encoder 與工作記憶體在 STREAMON 前準備。保留現有 RAW10 DMA geometry guard，另包含 VFE17x done-event gate 與早期 media pads NULL 防護。

## 驗證層級

| 項目 | 結果及範圍 |
|---|---|
| ARM64 kernel build | board headers 編譯、modpost、link 通過；缺少 vmlinux，未產生 BTF |
| ARM64 userspace | Release build、11/11 CTest 通過；新增 public API 另以 C++17 / Wall / Wextra / Werror 編譯與執行 |
| 實際 timer callback fixture | 40,000 callbacks：固定 30 Hz、early/late、700 µs pulse 延誤、overrun、跳 slot、GPIO failure、stop |
| 實際 publication / worker fixture | 異步紀錄、256 筆 queue overflow、producer / association lock 分離 |
| 實際 arm / SOF / DMA fixture | 27 項：node ownership、未知首幀、取得／逾時、單眼丟幀、重複、延遲／合併 DMA、停止、歧義、32 幀 overflow、重啟 |
| 板端正向／反向啟動 | 各 20 秒，約 30 FPS、exact timestamps、identity errors=0、internal unpaired=0 |
| 板端 starvation / restart | 暫停 capture 1 秒，error 9 並拒絕有效輸出，producer 持續；新 session 20 秒恢復通過 |
| 板端 exposure calibration | 30 Hz 下 8、32、808、1330、1360、1377 rows 與反覆切換通過，唯一對應、各眼 30 FPS |
| Patch 可套用性 | 對保存的 exact guarded source，全部 10 個檔案 dry-run 通過 |

fixture 抽出實際 kernel 函式配合虛擬 GPIO / clock / MMIO；不能代替板端故障注入、電氣邊緣或光學曝光量測。VFE done ISR 的 256 狀態組合與 early media graph fixture 另在歷史驗證資料保留。

## 部署、證據與回復

module srcversion `E06BFE4497044149C75C90A`；SHA-256 `0b84b5fbb379b05d2e5362726864c78a4ab20e033064f12bc588854b87705dec`。啟用參數為 `geometry_guard=1 fsync_mode=2 sof_min_us=341 sof_max_us=16853`，預設未設定時仍 off。

[部署 manifest](evidence/30hz-final/final-30hz-deployed.sha256)包含 module、initrd、opt-in、settings、binary、runner；[source manifest](evidence/30hz-final/final-30hz-source.sha256)與 fixture hash 可核對。完整新版證據為 `evidence/final-30hz-evidence.tar.gz`，已下載並驗證 SHA-256。舊 60 Hz 試驗不作本版驗收，保存於 [HISTORY-60hz.zh-TW.md](HISTORY-60hz.zh-TW.md)與既有 archive。

工作開始前 module、initrd、設定、runner、binary 與服務資料仍在板端 `/home/ubuntu/sc132gs-kernel-sync-20261014/backup`；原始 backup hash 已再次全部核對通過。回復工具先驗證備份，再準備保存版本；之後需重開機載入，不熱卸載 CAMSS。操作與 UML 預覽见 [README.zh-TW.md](README.zh-TW.md)。

同 timestamp 的承諾是**同一共同 FSYNC host reference**，不是已量測的電氣邊緣或曝光開始時間。未設定／宣稱標準 `SOE`，未驗證 HDR、其他解析度或其他 FPS；[V4L2 timestamp 定義](https://www.kernel.org/doc/html/v4.20/media/uapi/v4l/buffer.html)與本 ABI 私有時間来源分開描述。


## 後續一小時補充證據（2026-10-15 整理）

本次整理已讀取另一驗證流程保存的 [hour-final/result.json](../../stereo_h265_rtsp/configuration-evidence-20261014/queue-root-cause/sync30-20261014-1857/hour-final/result.json)及[獨立重算結果](../../stereo_h265_rtsp/configuration-evidence-20261014/queue-root-cause/sync30-20261014-1857/hour-final/independent-verification.json)：720 個完整統計窗口覆蓋 3609.1335377 秒，capture 平均 29.99999830 FPS、encoder 平均 29.99999770 FPS，保存結果為 passed=true。

原 observer 在約 1712 秒因瞬時 encoder FPS 30.3711 判定失敗，原 failed 資料保留。後續完整 log 重算使用各窗口時長加權；非同步 encoder 的完成批次跨越五秒邊界，瞬時 29.62／30.38 不等於整段平均 FPS 異常。控制狀態取樣有中斷，使用完整 server log、前後相同 service／boot／module／session 與 sticky error 狀態補核對。這項補充證據不代表連續一小時控制取樣，也不代替前述逐筆 raw timestamp 的 605 秒驗收。

一小時後的影像另有極暗場景，保存的 register readback 與 AE 上限 1377 rows／gain 128 一致；當時現場照明未確認，沒有將暗圖標成可辨識的正常場景。詳細範圍見 [queue-root-cause 驗證紀錄](../../stereo_h265_rtsp/configuration-evidence-20261014/queue-root-cause/RESULT.zh-TW.md)。本段僅整合本機已保存證據，未重連或變更板端。
