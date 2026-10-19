# HDR 下方固定霧帶診斷

## 已定位範圍

下方霧帶已存在於 V4L2 擷取的 packed RAW10，未經 Bayer/灰階轉換、
H.265、VLC。直接將 RAW 像素作共同顯示曲線即可看見；Main10 解碼
影像也保留相同區域。因此後端轉換、編碼與 VLC 不是產生這條霧帶
的必要條件。問題集中在 HDR 外部觸發的讀出路徑。

## 固定曝光 A/B 與回復確認

各條件兩眼都是 TOTAL=0x004eb0、SECOND=0x004f、nominal exposure
1259 行、gain index 0、HDR mode=0xc3、0x3225=0。每眼記錄 12 幀
1740800-byte RAW，各幀 SHA256 不同並與 evidence.json 驗證一致。

| 條件 | 0x3222 | 最後 128 列空間殘差，左／右 RAW10 碼值 |
|---|---|---|
| 外部觸發 30 Hz，初次 | 0x32 | 7.23 / 8.77 |
| HDR vendor 自由運行，FSYNC generator 仍為 30 Hz | 0x30 | 1.46 / 1.38 |
| 外部觸發 25 Hz | 0x32 | 7.21 / 8.79 |
| 外部觸發 30 Hz，再測 | 0x32 | 7.21 / 8.79 |

殘差算法與 2026-10-06 的調查相同：時間平均圖的同 CFA phase
二像素距離高通，在 x=320..831、y=1152..1279、RAW=40..950 上
取絕對值中位數。此區含實際場景，數值不是經校準的 FPN/SNR。
自由運行最後 128 列時間雜訊約 2.89 / 3.09；外部觸發約 3.04 / 3.28，
空間偏差的變化遠大於逐幀隨機雜訊變化。

首次自由運行試驗沒有鎖成同曝光，不能直接作因果比較；已用固定
1259 行重新擷取覆蓋該條件。最後切回 0x32 可重現原霧帶。
25 Hz 仍有霧帶，故降低觸發頻率在此次設定下不是有效修正。

## 與舊修正的關係

舊修正把 0x3225 從 0x04 改為 0x00。此次實際 STREAMON 時兩眼皆為
0x00，所以舊修正未回退。但舊紀錄本來仍有約 5.9 / 5.5 的下方殘差，
舊場景、曝光及增益不同，不能把當時的改善視為消除所有固定偏差。

自由運行雖明顯改善，目前沒有證明雙眼物理曝光同步；不能直接把它
當成 stereo 的正式修正。尚未確定 HDR 外部觸發需要修改哪個時序欄位，
不修改 driver，也不加入會改寫 RAW 值的去霧或列補償。
遮住兩顆鏡頭的 dark-frame 測試尚待使用者配合，可進一步分辨黑位偏差
與受光時才出現的讀出／HDR 行為。

## 串流與恢復

初次相同曝光的 Main10 解碼取得 155 幀，PTS cadence=29.9986 FPS，
I420_10LE、2176x1280、749 個灰階值、低二位存在。
RAW 與解碼是相鄰時段的順序擷取，不是同一幀，不能作逐像素壓縮誤差比較。

每次診斷使用 finally 清理擷取與 FSYNC 程序，重啟正式相機服務，
恢復 HDR 30 FPS、外部觸發 0x3222=0x32、0x3225=0、AE target 40%。
VLC 重新連線並沿用既有顯示提亮設定。正式 10-bit 灰階路徑未改動。

## 證據

- `board/evidence.json` 與 `board/cam0.raw`、`cam1.raw`：初次 external30。
- `board/free/`、`board/external25/`、`board/external30/`：各條件 RAW、寄存器及 hashes。
- `analysis.json` 與各條件 `analysis.json`：空間／時間統計。
- `raw-direct-preview.png`、`decoded-preview.png`：原始與解碼預覽。
- `free/raw-direct-preview.png`：固定曝光自由運行預覽。
- `restore-status.txt`、`restore-rtsp.txt`、`vlc-restored.jpg`：最終恢復狀態。
