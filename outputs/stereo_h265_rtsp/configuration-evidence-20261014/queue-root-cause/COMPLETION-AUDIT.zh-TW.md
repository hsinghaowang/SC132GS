# SC132GS 修復完成審查

目前判定：**已識別的软件缺陷修正、部署與使用者指定的驗收已完成**。使用者選定的 Linear 30 FPS、AE on、30 Hz FSYNC 為本次設定；相機與串流持續運作，沒有重啟。末段暗場的現場照明尚未確認；兩眼曝光／增益已從硬體讀回與要求一致，31張原生Y資料均不同。照明詢問保留為附帶確認，不把它新增為原SMMU／停幀／scheduler修復的完成門檻。

| 要求 | 權威證據 | 目前判定 |
|---|---|---|
| RAW10 DMA 不越過協議配置的 buffer | 既有 `dma-fix/RESULT.zh-TW.md` 的 extra-row 故障重現與兩眼各300 frames受保護測試；`production-raw10-byte-proof/result.json` 全 bytes 一致；本版運行中 geometry_guard=Y | 幾何越界條件已修正，有實機故障注入證據；不把所有 IOMMU 故障等同此單一機制 |
| VFE completion 不被過早讀取的 TOP bit9 遮蔽 | actual ISR原版／修正版256組狀態及讀取間到達的WM0 completion負例；合併source保留 bus done bits 直接dispatch | 已修正該可重現race；原四小時自然事件没有故障當下IRQ trace，不能宣稱唯一因果已捕捉 |
| scheduler 固定FPS，timestamp處理與trigger獨立 | actual tick 40,000 callbacks、source時間常數；worker CPU0／timer CPU7；armed-10min cadence平均30.00000036Hz、trigger gaps0 | source及實機605秒通過；不是電氣零jitter保證 |
| AE範圍內實際幀率均為30 | exposure-30hz的8..1377 rows與上下限重複切換；獨立`exposure-fps-analysis.json` | 已通過；舊60Hz下短曝光60FPS的假設已撤除 |
| 同trigger兩眼原始DQBUF相同timestamp，不猜同幀 | 獨立重跑`armed-10min-independent/analyze_buffers.py`：18,139 exact pairs、identity errors0、internal unpaired0、有效sequence gaps0、lost0、boot/session不變 | 605秒實機通過 |
| 未知啟動buffer不得當有效影像，runtime錯誤仍可辨識 | arm前／首個post-arm ERROR prefix、session與實際node/sequence end分類；實際SOF/DMA27項；正反開啟、starvation與restart實機證據 | 已通過相應source及板端測試，初始ERROR與運行期缺失分開 |
| 資源與deadline合理 | Main10 encoder及工作記憶體先於STREAMON；析構先停camera再關encoder；每眼獨立deadline、有界payload所有權與strict配對 | source/component及指定實機時段驗證通過 |
| 保存的設定與RTSP內容恢復 | peer最終部署manifest，settings hash與備份相同；狀態Linear／AE1／target30；实际HEVC Main10 2176×1280 yuv420p10le前後各解碼181frames；結束後六項hash再次OK | 恢復與結束後核對均通過 |
| 接入／離開RTSP不造成停流 | reconnect-01/02/03各91frames，steady media30FPS，持續同一server/session | 三次有界案例通過；之後仍同一程序運行 |
| 一小時無新同步、queue、kernel故障，capture/encoder持續 | 原unit的瞬時encoder FPS gate過嚴，1712秒誤判已完整保存；finish結果與獨立重跑全部720個window，duration3609.1335s、capture29.9999983／encoder29.9999977FPS；同PID／boot／module／session，無health／drop／kernel fault | 完整log驗證通過；控制樣本間隙明確保留，不宣稱連續10秒sampling |
| 一小時結束後串流與設定仍正常 | 再解碼181張Main10／2176×1280／10bit，steady PTS30FPS；6個deployment hashes全部OK，geometry_guardY、mode2、error0／skipped0／session7、Linear／AE1／target30 | transport／設定通過；末張圖像幾乎全黑，現場照明待確認 |
| 最終圖像不是凍結或純零buffer | 原生10bit Y plane31張全數hash不同，兩眼平均約5／1023，gain128／exposure1377已到上限；沒有修改亮度或設定 | 證明影像資料持續變化且極暗；不能僅由此判斷現場是否關燈，已詢問使用者 |

本版loaded module srcversion為E06BFE4497044149C75C90A，RTSP binary SHA為ed8ed3e9c5739274d0959c58e41b0aa044761060193900c28ef628f09b190412。當前監看為session7、boot b0220435-decf-4c94-b1ac-e41ba7bea41a、service MainPID6389；監看只讀且限制CPU0..6。

最後審查已讀回實際terminal結果、完整samples/server log、最新kernel log、設定／source hash、再次解碼及兩眼硬體曝光／增益。兩個observer先後運作，未重啟相機或串流；舊observer退出及sample間隙保留，720個完整統計window已獨立重算一致。

這些證據涵蓋已識別軟體缺陷與使用者指定的驗收時長。未量測新電氣邊緣、曝光起始偏差或其他模式；不宣称任何硬體條件下永久零故障。
