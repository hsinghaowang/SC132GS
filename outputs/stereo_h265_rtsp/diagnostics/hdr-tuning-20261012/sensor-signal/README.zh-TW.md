# 相同 target 的有效灰階校正與長曝光驗證

本階段已完成黑位校正、部署線性輸出、Linear 曝光預算修正與 HDR
低 FPS 長曝光。OpenVINS 三個套件成功建置後才重開板子，開機服務
自動復原 HDR30/AEon/target10/revision159，兩顆驅動範圍讀回4492。
本場景最後比較為 Linear30 與 HDR15、同 target30；結果與限制見下文。

黑位證據在 `../raw-black-calibration/`。鏡頭遮光時，Linear/HDR 各測 gain
index 0、11、21；每組每眼 60 個連續未編碼灰階影格約 30 FPS。
首張完整影像的中位數為 Linear 37/37、HDR 53/52（gain0），
其餘兩組為 Linear 37/37、HDR 53/53。採共用 B=37/53；沒有高 gain 或
其他讀出 profile 的完整黑位校準。量測後使用者已移開遮擋。

預設 unbinned Main10 使用固定線性校正：

```text
signal = round(1023 * clamp((gray10-B)/(1023-B), 0, 1))
AE signal target = round(1023 * target_percent / 100)
uncalibrated target = B + round((1023-B) * target_percent / 100)
```

gamma=1，沒有顯示曲線、逐幀拉伸或降噪。RAW buffer 不修改，亮部 clipping
仍看原始 RAW；兩模式以同一中央 80% ROI 的 P50 追蹤有效灰階。
校正只是固定黑位／範圍校準，不能把 HDR 的兩段感測器響應宣稱為完整輻射定標。

`../calibrated-signal10/assessment.json` 是真正兩模式 target=10 的 RTSP 比較。
中位數 Linear 102.5/104.7、HDR 99.8/104.1。固定相同空間 mask 排除 Linear
最亮 10% 後，HDR 平均差 -3.33%/-0.84%；整區平均仍低約 12～15%，
因 HDR 把 Linear 已截白的燈具保留下來。Linear 飽和比例約 2.76%，HDR 0。
四個解碼暗部 patch 的對比／殘差雜訊比提升約 4～35%，但
`../raw-noise-signal10/` 的相應未編碼結果仍低約 5～7%。不能只靠有損編碼
後的雜訊變小就宣稱真正暗部訊號增加。target15 的解碼暗部亦未全面改善。

Linear FPS 邊界在 `../linear-budget-probe/results.json`：設定 30 FPS 時，
1320、1377 rows 收到約 30 FPS；1480、1600 rows 約 15 FPS；回到 1377 恢復。
寄存器 3260/61 讀回 1334 rows。正式預算在 FPS<=30 預留 1350 rows，再取
剩餘時間 95%；30 FPS 上限為 1377。以 requested FPS 固定 deadline，實測
FPS 獨立回報，避免漏觸發後放大曝光上限的正回授。

使用者已同意降低 HDR FPS 換取長曝光。`../hdr-long20/long-exposure.json`
是 AE 關閉的可回復試驗；實際 I2C group tuple 讀回兩眼 TOTAL=1492、2492、
2992、3492、3629、1492，SECOND=1、gain0，皆約 20 FPS。每組保存 12 個
解碼影格及固定暗部 patch。3629 的中位數約 259/268，沒有解碼 clipping；
回到1492中位數約107/109。這證明更多曝光能實際提高訊號，尚不是相同
target／相同亮度的最終比較。

SC132GS 資料手冊 V2.6 頁29 說明 HDRC 要額外讀取一次 HDR point，讀取期間
不能曝光，30 FPS 範例為 33.33ms=2*11.11ms readout+11.11ms exposure。
這是手冊範例，沒有宣稱板上曝光起迄時間已物理量測。

新驅動寄存器範圍為 VTS4500-8=4492；15 FPS 手動 TOTAL4492 的實際
試驗在送出15個 pairs後停流，交易回復亦曾失敗。保留失敗日誌，之後
使用既有 restore 恢復並解碼確認。不能只用寄存器範圍保證可用曝光。
正式 owner 改採已驗證4350的保守限制，30/24/20/15 FPS 為
1492/2560/3629/4350。4350的手動 ratio256（SECOND272）及 AE SECOND1
皆已出圖，AE RAW 試驗每眼60個連續 frames 約15FPS。
降 FPS 已達 target 時也會逐步用曝光取代 gain。kernel module 與 Release
C++ 建置完成，8/8 CTest 通過。`stage_long_hdr_boot.py` 預先檢查測試、kernel
版本、OpenVINS 建置是否仍在執行與開機復原服務；備份後原子替換檔案，
不熱卸載 CAMSS。舊的 `deploy_long_hdr.py` 已停用，先前嘗試未換檔，服務已復原。

`../calibrated-budget20/` 已驗證 Linear 30 FPS 修正後 target20 可用：
曝光1377、gain13、實際約30FPS，中位數200/205、飽和3.96%/3.77%。
HDR30 的 target20 被亮部保護限制，中位數157/160，TOTAL1492、gain19，
`brightness_limited=1 highlight_limited=1`。保護確實優先，但目前無法達到
同 target 的亮度；後續已完成的低 FPS 比較如下。

`../long-hdr-assessment.json` 彙整兩個真正同 target 的比較：

- Linear30/HDR20、target20：中位數196.8/199.8對197.6/201.1，HDR gain0、
  TOTAL2830、SECOND1；HDR解碼無飽和，Linear約3.92%/3.75%。RAW 四區
  對比／殘差雜訊比提升3～11%，但 RTSP 解碼後下降5～17%，沒有全面改善。
- Linear30/HDR15、target30：Linear1377rows/gain30，HDR4350rows/gain0/SECOND1；
  中位數299.4/306.4對293.4/302.0，差-2.0%/-1.4%。Linear解碼飽和
  4.48%/4.20%，HDR0。RAW四區對比／殘差雜訊比提升33.7/37.6/36.6/36.0%，
  時間雜訊下降24.8/34.8/27.6/33.0%，RTSP解碼後提升27.9/38.5/27.2/34.5%。

每模式 RAW 每眼60個連續frames，RTSP分析12個frames；所有patch座標固定，
沒有影像降噪或新顯示曲線。ROI各亮度分位的共同空間位置都保留在assessment：
target30的0～50百分位區間平均接近，但較亮區間因HDR兩段響應而下降，
整區平均由396.8/405.5降至290.7/311.6（約-27%/-23%），不能宣稱整張平均
相同，也不外推為所有target、場景、相同FPS或運動模糊均更好。

重啟前在 STREAMOFF 寫入已驗證曝光seed，使較低FPS的長曝光不會以舊值
帶到新較高FPS的第一幀。C++參數檢查對15FPS的4351及30FPS的1493在backend
修改前拒絕；8/8 CTest通過。邊界與gain替代測試見`../long-hdr-owner-check*/`。

最後的gain替代實測（v3）：target15由HDR30/TOTAL1492/gain16切到
HDR20/TOTAL2135/gain0，兩眼有效灰階約15%，無亮部限制與control error。
v3的診斷復原原先只還原mode/FPS/AE/target，漏了手動rows，臨時設定
4350被保留為2135；之後已明確還原4350/gain0，並修正診斷的手動復原
與readback檢查。原始check.json/log保留，不回寫成較好的結果。

最終保存 HDR15、AEon、target30、TOTAL4350、SECOND1、gain0，revision176；
YAML與runtime紀錄相同。`../final-hdr15-target30/proof.json`記錄兩眼控制讀回、
安裝檔案雜湊與boot ID。12秒RTSP解碼得到177個不同影格、2176×1280，
PTS14.9998FPS、software wall14.93FPS；`decoded.png`為單張實際解碼擷取，
未加入顯示提亮或平均多幀。預設gamma1，只做前述黑位線性校正。
