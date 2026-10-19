# Binning 60 FPS AE 已啟用

2026-10-07，整合在 RTSP capture owner 內，未啟動第二個相機擷取程序。

## 現行設定

- 544×640 / eye，1088×640 合成，Linear binning 60 FPS。
- AE 使用顯示轉換前的線性 luma，中央 80% 區域中位數。
- target_percent=18 為線性亮度；本場景最終解碼中位數約 102/255。
- 兩眼共用曝光及增益。優先延長曝光，達上限後才加增益；變亮時先減增益。
- 透過建構子注入 LinearTiming{162000, 2560}；原模式維持預設 84000 rows/sec。
- 60 FPS 曝光上限 2560 rows，依時序換算約 15.80 ms，不改 FPS。
- 控制測試完成時兩眼曝光 2531 rows，約 15.62 ms；gain_index=2，實際 code 0x0321。這些是當時讀值，AE 會持續調整。
- 最終 mode=auto，brightness_limited=0，error_errno=0。
- sc132gs-binning60-rtsp.service ACTIVE，AUTO_EXPOSURE=1、AE_TARGET=18。
- RTSP：rtsp://192.168.137.226:8554/stereo。

實驗程式仍要求以 auto-exposure=off 啟動；runner 先套用且讀回 VTS 2700、曝光與增益，最後才透過控制 socket 啟用 AE，避免在初始 120 FPS 表格時序下使用 60 FPS 曝光上限。

## 硬體驗證

1. AE 暫停後設曝光 300 rows / 最低增益，實際解碼中位數 46、平均 54.66，PTS 59.9959 FPS。
2. 重新啟用 target 18：control trace 約 1.04 秒內依序 300 → 505 → 1011 → 2020 → 2560 rows，增益保持 0；兩眼線性量測由約 5% 回升到 17/18%。恢復後解碼中位數 99、平均 111.59，PTS 59.9980 FPS。
3. target 改為 8：曝光降到 855 rows、增益維持 0，兩眼量測收斂到 8%。
4. target 恢復 18，max-exposure-us=1000：曝光上限正確轉成 162 rows，先將曝光降至此上限，再增加增益到 index 126，兩眼量測達 17/18%。
5. 解除時間限制後，AE 增加曝光並降低增益，最終 2531 rows / gain 2；兩眼 V4L2 與 I2C 寄存器讀回一致（00/9e/30，03/21）。
6. 最終 15 秒 RTSP 軟體解碼：896 frames，896 個不同 RGB hashes，PTS 59.999821 FPS，解碼中位數 102、平均 112.61。既有及新顯示轉換 CTest 5/5 通過。

此次驗證用感測器曝光調整製造暗畫面，以及 target / exposure cap 切換測試控制反應；沒有宣稱測過自然照明大幅變化或遮光恢復。較亮場景與無法達標的上限情況仍未另做現場測試。

後續現場讀值曾變成 2560 rows / gain 79，稍後再讀為 gain 4；未量測造成變化的外部光源。追加實際解碼證據在 ../ae60-live-final：293 frames / 5 秒，PTS 59.9967 FPS，畫面有室內細節、解碼中位數 104，AE 仍 active 且 error_errno=0。

亮窗仍局部過曝；目前以室內細節為主。AE 沒有解決長曝光的移動模糊。服務與實驗模組仍不是開機持久配置。

## 操作

在板上可用 sudo sc132gs-ctl status 查看；sudo sc132gs-ctl set-brightness 18 啟用；sudo sc132gs-ctl auto off 暫停。這個 target 數值為線性量測百分比，與 RTSP 解碼的顯示百分比不同。
