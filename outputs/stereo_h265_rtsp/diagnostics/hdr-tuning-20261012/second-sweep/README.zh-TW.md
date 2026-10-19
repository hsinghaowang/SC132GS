# 短曝光掃描與黑位相對亮度比較

2026-10-12，原場景，Main10 sensor profile，無顯示曲線。
程式sweep_second.py固定HDR TOTAL1492 / gain0 / 30FPS，
依序SECOND=1、16、64、128、256、512、1；每組12幀解碼。
比較數據在comparison.json，平均影像與10-bit陣列保留。

| SECOND ticks | 左眼ROI平均 | 左眼截白% | 暗區1 contrast/noise | 暗區2 contrast/noise |
|---|---:|---:|---:|---:|
|1 (開始)|196.75|0|79.04|64.05|
|16|196.64|0|54.40|60.21|
|64|197.47|0|61.66|60.70|
|128|198.25|0|61.53|59.51|
|256|199.95|0|63.88|62.43|
|512|201.98|0.1153|52.61|62.36|
|1 (結束)|196.75|0|83.40|58.15|

短曝光變長至512使亮部出現截白；暗部指标沒有穩定優勢。
開始/結束SECOND1的指标也有變化，因此不能把這些解碼時序噪聲
直接視為sensor讀出噪聲。可能含燈光閃爍、場景變動與codec影響。
未修改正式short-exposure策略，已恢復HDR/AE on/target10/
max_fps30/max_exposure_us0/max_gain128/SECOND1。

## 黑位相對target10

../equal-target-black10/comparison.json使用量測黑位Linear37、HDR53，
試算relative10對應native13、15，僅實驗腳本，未部署target換算。
左眼原平均181.617/196.617，扣除各模式黑位並除以剩餘量程後，
Linear14.667% / HDR14.791%；右眼15.176% /15.327%。
平均訊號亮度相當接近，Linear截白2.46%/2.64%，HDR兩眼0%。
但左眼兩暗區contrast/noise Linear97.18/80.06，HDR65.95/60.99，
沒有證明暗部細節改善。尚需分離閃爍與codec對指标的影響，並
驗證右眼暗部，不能宣稱完整目標達成。

## 另行修正亮部保護取樣

sc132gs-hdr-ae-policy.hpp原來stride8只取單一Bayer phase，已改成
每個取樣點取2x2完整CFA cell，避免漏掉其他通道過曝；luma P50
meter及顯示輸出保持原本定義。四個phase分別飽和的回歸測試通過，
整體CTest7/7通過。新版已部署，platform restore包含RTSP解碼驗證，
實測約30FPS、AE target10、gamma100、black0。這項修正加強亮部
保護，但不代表暗部改善。Binary備份server-before-cfa。
