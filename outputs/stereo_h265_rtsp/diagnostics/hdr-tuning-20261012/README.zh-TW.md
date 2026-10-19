# 本場景 HDR 手動調校（2026-10-12）

最新進度：B 顯示曲線已依使用者要求取消。正式 sensor profile 使用
模式黑位的固定線性校正及相同有效灰階 P50 target。使用者確認
切回 Linear 看不到霧狀，選定預設 **Linear 60 FPS、AE target30**，
HDR 調校暫時停止。先前 HDR 診斷為 15 FPS、TOTAL 上限 4350。暗部的逐幀
雜訊改善未涵蓋固定霧狀紋理，使用者已回報長曝光下的畫面問題。
第三次調查、前兩次修正核對及尚未解決的限制見
[HAZE_RESULT.zh-TW.md](HAZE_RESULT.zh-TW.md)。以下「最終結果」是
較早的 B 顯示曲線階段歷史記錄，不代表目前串流設定或畫質已完成。

## 最終結果

使用者已選 B。B 曲線已實際部署至 Main10 HDR 直播，AE 已開啟，
本場景 target=30%（B 顯示曲線後的暗部取樣亮度）；對應原始 RAW10
target=139。百分比不再乘以前的 80%，也不沿用原先 40% 目標。
暗部較暗 80%／亮部最亮 20% 的取樣分组則維持既有定義。

原始 RAW10 統計在 B 曲線之前計算；曲線只作用於編碼用 R16 灰階。
啟用 AE 時改為讀取現行 SECOND 控制，避免帶回過時的手動快取。
B 策略使用 RAW10 ±5 的控制死區；較舊路徑仍使用原先 ±10。

ae-convergence-b.json 保存最後版本的兩項板上收斂驗證：
TOTAL=800/gain=0 與 TOTAL=1492/gain=64，兩者都 SECOND=1。
兩項各量測 36 秒，最後八秒皆符合兩眼暗部 30±1%、感測器飽和
組比例不超過既有上限、SECOND=1、零控制錯誤、接收 FPS>=29。
最後分別收斂到 gain=19 與 gain=21，TOTAL 都為1492。
不同增益仍可落在控制死區內；未聲稱唯一參數解。

最終板上設定保存於 final-settings.yaml：HDR、30 FPS、AE=true、
brightness=30、TOTAL 起始值1492、gain 起始值21。
final-status.txt 證實當下 SECOND=1、兩眼暗部29%/30%、零錯誤。
live-b-ae-final.png 是真正解碼後的直播畫面，不是離線曲線預覽。
test-final.log 保存 Release 建置的7/7 CTest結果。

Windows RTSP/TCP 在八秒內收到241個H.265 access units，約30.06 FPS。
板上軟體解碼實際吞吐約24 FPS，连续 PTS 對應約30 FPS，未發現
大於45ms的PTS缺口；此解碼器吞吐限制不作為30-FPS解碼證明。
尚未測試換場景或物理照明改變，此次收斂驗證範圍為目前場景。

部署前 binary 備份：板上 `/home/ubuntu/hdr-tuning-20261012/server-before-b`。
新 binary SHA256：`26e02e05e82e408ea22009437b95e2a8dbc0309342b8a6c64112b8d4cc7e2de1`。
首次未最佳化的建置造成掉幀，已改為 Release；其診斷證據保留於板上。

以下記錄為前階段的手動調校與離線預覽。

已連上板子並停用 AE，固定 HDR 30 FPS，兩眼 TOTAL=1492。
基準設定保存於 baseline-settings.yaml，基準即時狀態保存於
baseline-status.txt。原本即時 AE gain=21、SECOND=1，持久化種子 gain=33。

manual_sweep.py 實際套用五組參數並各取一张解碼 Main10 畫面。
每組均讀回兩眼 V4L2 控制；結果記錄於 manual-sweep.json。
影像為全範圍 I420_10LE，2176×1280；分析區域為每眼中央約 80%。
下表為解碼亮度 >=1020 的比例，不是感測器原始 RAW 的量測。

| gain index | SECOND ticks | 左眼飽和 % | 右眼飽和 % |
| --- | --- | --- | --- |
| 21 | 93 | 0.574 | 0.977 |
| 21 | 1 | 0.229 | 0.629 |
| 33 | 1 | 2.710 | 3.712 |
| 48 | 1 | 3.926 | 4.351 |
| 64 | 1 | 4.411 | 6.885 |

掃描後兩眼留在 AE off、TOTAL=1492、gain=21、SECOND=1；
manual-final-status.txt 保存此即時狀態。TOTAL/gain/AE 經既有控制器
持久化，獨立 SECOND 尚未持久化，重啟可能回到 ratio=256 推導值。

直接提高增益會讓燈管細節消失。compare_display.py 使用同一張
gain21/SECOND1 的解碼影像產生顯示曲線候選：
`clamp((decoded_luma10-52)/(1023-52),0,1)^gamma`。
gamma=0.65 為 A、0.5 為 B，52 是既有量測的候選黑位準。
這是離線預覽，尚未改動直播的顯示轉換，也尚未修改 AE。
它不能恢復原本已飽和或未取得的細節。

display-comparison.png 由上到下是原圖、A、B。使用者後續選定 B，
部署、AE 修改及本場景驗證結果見本文件最上方。

原始解碼 u16le 與所有掃描 PNG 也保留在板子
`/home/ubuntu/hdr-tuning-20261012/`，不需停止相機取得。
