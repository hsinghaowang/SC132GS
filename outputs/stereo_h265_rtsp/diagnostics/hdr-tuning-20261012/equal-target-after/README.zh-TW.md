# 同 target 的 Linear／HDR 實測（2026-10-12）

已部署：兩種模式直接使用同一個0..100的感測器灰階target；取消Linear舊顯示曲線反算。
Main10 HDR使用與Linear相同的中央80%區域灰階P50；RAW clipping仍獨立限制曝光。
切換模式不再把target重設為40。沒有加入板端提亮曲線。
Release build與7項CTest通過，詳見equal-target-tests.log。

comparison.json與原始PNG是解碼Main10的證據，不是模擬顯示曲線。
第一次baseline只有10/40；新版after的10/20完成，40模式交易失敗後恢復HDR target10，
因此不宣稱新版40完成。切換期間有iris_vpu STREAMON記憶體配置失敗；
只在確認編碼器沒有使用者後重置iris_vpu，沒有重載sensor或CAMSS。

target20第一次比較：Linear左右中位數194/201，HDR195/200；
平均258.98/265.81與242.54/249.45，相差約6%；
Linear clipping3.35/3.75%，HDR0/0.00022%。

第二次12幀暗部量測在../equal-target-noise/comparison.json：
固定左眼區域(30,80)-(160,220)的對比/時間雜訊：Linear34.72，HDR22.18；
區域(500,470)-(660,620)：Linear113.78，HDR92.06。
這是解碼端量測，不能代表RAW噪聲或感測器動態範圍。
兩次AE死區與場景變動使亮度數值略有差異；移動人物未用來評估暗部。

完成證據尚不足：已確認target語意一致與本場景亮部保留改善；
目前暗部量測沒有證明HDR更清楚。需要遮住雙鏡頭量測黑位／雜訊，
再決定曝光策略或必要感測器校正；不以抬升黑位冒充暗部細節。
