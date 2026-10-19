# 編碼前暗部量測

2026-10-12，raw-noise-capture使用原有RawOpticalCapture與BayerLuma，
保存兩眼進入codec前相同算法的10-bit灰階。每眼8幀暖機後60幀，
兩暗區座標與RTSP每眼水平鏡射一致。未加gamma、黑位修正、denoise。
每組包含patches.bin、首幀完整luma10及各暗區npz序列。
raw_noise_test.py獨占相機鎖，從先前AE測試取曝光/gain作固定量測，
使用相同30Hz FSYNC。結束已由platform verify解碼RTSP確認復原，
保存的YAML與runtime設定逐byte未變。

noise_analysis.py額外估計每幀相對平均影像的gain及offset，只將
均勻波動從統計殘差中扣除，不改任何相機或显示輸出。合成已知
照明調變加單位高斯噪聲的檢查通過。數值是紋理p90-p10對時間
殘差之比，不是絕對sensor SNR，也不涵蓋固定圖樣噪聲或MTF。

## 相同原始target10

資料comparison.json：Linear612rows/gain0，HDR791rows/SECOND1/gain0。
兩眼各60連續sequence，receiver cadence約30FPS（不代表曝光同步）。

| eye / patch | Linear contrast/residual-noise | HDR | HDR相對變化 |
|---|---:|---:|---:|
|0 / 0|9.68|8.20|-15.2%|
|0 / 1|32.11|27.82|-13.3%|
|1 / 0|56.28|47.43|-15.7%|
|1 / 1|6.31|5.44|-13.8%|

扣除整體亮度波動前後接近，無法把這個案例的差距主要歸因於
燈光閃爍。差距已存在codec前，單純RTSP/encoder設定不足以解決。
../equal-target-detrended10另保留相同target的解碼暗區序列。

## 黑位相對target的原型比較

../raw-noise-black10/comparison.json使用先前黑位原型試算：
relative10對應Linear native13、HDR native15。固定Linear785rows，
HDR1492rows/SECOND1，均gain0；不是目前正式同target10行為。

| eye / patch | Linear contrast/residual-noise | HDR | HDR相對變化 |
|---|---:|---:|---:|
|0 / 0|11.005|12.124|+10.16%|
|0 / 1|32.185|35.729|+11.01%|
|1 / 0|63.147|73.854|+16.96%|
|1 / 1|6.551|7.864|+20.04%|

這支持校正模式黑位及AE有效訊號定義的方向，但尚未部署校正。
37/53原型黑位來自先前遮光時RTSP解碼；正式輸入校正仍需確認
codec前的黑位，不能將解碼黑位當成已驗證的RAW黑位。
本次沒有同幀RAW/HEVC像素對照，不能證明端到端暗部細節改善。
數據為固定背景靜態區域，尚未測運動/不同增益/更多target。

結束時HDR/AE on/target10/30FPS/SECOND1/max_exposure_us0/max_gain128，
gamma100/black0，設定revision145。編譯與現有CTest7/7通過；
CTest不涵蓋sensor画質或光學同步。
