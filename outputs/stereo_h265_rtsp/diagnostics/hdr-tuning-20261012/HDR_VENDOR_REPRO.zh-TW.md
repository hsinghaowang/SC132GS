# SC132GS 長曝光 HDR 固定紋理重現與原廠確認事項

日期：2026-10-12。此文件只整理證據，尚未傳送給原廠。

## 問題

GS130WI 雙 SC132GS，RUBIK Pi 3，兩路 MIPI RAW10。HDR 較短曝光
時只有較小空間殘差，TOTAL 延長後大範圍受光區域出現固定霧狀／
顆粒紋理。兩眼皆可重現；紋理已存在於未經 Bayer 灰階重建、編碼、
RTSP 或顯示處理的 packed RAW。

前兩次修改涉及 slave trigger 設定：3225=04 改為 00，以及
external/free-run 的下方霧帶差異。此次 3225=00 仍有效；完整
sensor reset 後以原廠 HDR 初始化表進入 free-run，長曝光紋理仍在。
已補做真正停止 FSYNC 來源的測試，確認無外觸發的 4350/1 長曝光
仍有紋理；部分短曝光的下方霧帶則明顯改善，兩種現象須分開處理。

使用者後續自行切回 Linear，確認同場景不再看到霧狀。讀回狀態為
Linear60、AE target30、exposure1330、gain37、control_error0。
這是使用者視覺確認，與既有 Linear/HDR RAW 對照相符；因兩種模式
的時序／曝光不同，不把此結果當成已定位某個具體寄存器根因。

## 取得方式

- 1088x1280 Bayer RAW10，1740800 bytes/frame；每条件每眼 32 幀。
- 正式 AE 暫停，固定 gain index=0，HDR SECOND=1 tick。
- 暫停正式 RTSP，V4L2 mmap 直接保存完整 RAW；各幀 hash 不同。
- 遮光測試後再以均勻受光白色表面比較，最後返回原場景。
- 量測後恢復 HDR 15 FPS、AE target 30 並實際解碼；未更改持久設定。

## 關鍵控制與讀回

| 項目 | External HDR 長曝光 | 原廠表 reset 後 free-run 長曝光 |
|---|---|---|
| 模式 3220 | c3 | c3 |
| Trigger／HDR point read 3222 | 32 | 30 |
| 3225 | 00 | 00 |
| HDRC enable 5001 | 01 | 01 |
| 3226／3227 | 08／08 | 06／06 |
| TOTAL 3e00／3e01／3e02 | 01／0f／e0 | 01／0f／e0 |
| SECOND 3e31／3e32 | 00／01 | 00／01 |
| Gain 3e08／3e09 | 03／20 | 03／20 |
| HDRC ratio 5400 | ff | ff |
| HTS 320c／320d | 03／20 | 03／20 |
| VTS 320e／320f（此對照） | 23／28，即 9000 | 23／28，即 9000 |
| Readout 3260／3261 | 0a／72 | 0a／72 |

TOTAL=4350 nominal rows，寄存器值=4350*16=69600；SECOND=1/16
nominal row。不是兩路 DOL 輸出，而是感測器 single-frame HDR。
4350 只是目前能維持串流的軟體上限，尚未獲原廠影像品質驗證。
寄存器值不能代替已校準的物理曝光時間。

正式 external profile 的 VTS=4500。上述 external/free-run 對照
皆設定 VTS=9000，避免自由運行截短曝光造成亮度不一致。
原廠 30 FPS HDR 表在 reset 後另設定長 TOTAL／VTS，不代表原廠
已有驗證這個低 FPS profile。

上表的先前 generator 仍執行，並非完全無外部脈衝的比較。
最新無外觸發對照把 GPIO18/19 設為 INPUT、不執行 pulse generator；
完整 reset/init 下 1492/1 為 30 FPS、4350/1 + VTS9000 為 15 FPS。
後者紋理仍在。詳見 `FREE_RUN_30FPS.zh-TW.md`。

## 白色表面比較

各 CFA phase 分別扣除局部平滑背景；分析範圍 y=48..895、
x=80..1007，排除線材／表面邊界、低訊號、飽和及強梯度。
此為現場定位測試，並非認證的均勻輻射源或 PRNU 校正。

| 模式／曝光 nominal rows | 固定高頻 RAW RMS 左／右 | 相對有效訊號的紋理 RMS 左／右 |
|---|---|---|
| Linear／1377（30 FPS） | 3.309／3.356 | 1.240%／1.301% |
| HDR／1492（15 FPS） | 2.337／2.372 | 1.367%／1.441% |
| HDR／2560（15 FPS） | 9.141／7.508 | 2.449%／2.003% |
| HDR／3629（15 FPS） | 14.963／14.102 | 3.820%／3.363% |
| HDR／4350（15 FPS） | 17.956／17.764 | 4.555%／4.181% |
| HDR／4350 重測 | 18.097／17.974 | 4.585%／4.226% |

長曝光 HDR 重測紋理相關係數 0.9913／0.9891；與 Linear 紋理
相關係數 0.0079／0.0059。遮光時 HDR 黑位約 53，固定 RMS
約 0.61～0.83 RAW code，未見相同程度的全畫面抬黑。

## 已做的對照

- 相同曝光與相近輸出亮度下，external／free-run／external 重測：未消除。
- VTS 延到 9000：未消除。
- 完整 SW reset，原廠 HDR 初始化，無 slave overlay：未消除。
- HDRC 5001 bit0 及 HDR point read 一起關閉／開回：未消除。
- SECOND=1／16／64／272 ticks：未見明顯改善。
- SECOND=1024／4096／8192／16384：部分空間殘差略減，但 RAW
  飽和比例增加至約 0.7%～2.8%，不符合保留高光細節的需求。
- 縮短 TOTAL、加 gain 到相近中位亮度：部分紋理降低，但高光飽和
  增加，部分曝光還產生更明顯下方帶狀殘差。

完整 reset 的短曝光追加測試曾取得不足長度的 RAW；該組不計入
有效證據，復原成功。詳細紀錄保留，避免把失敗測試當成通過。

## 請原廠確認

1. 單幀 HDR + HDRC 下，TOTAL 可以從 1492 延長至 4350 nominal
   rows 嗎？15 FPS 所需的完整 timing／HDRC 初始化與有效曝光範圍為何？
2. HDRC 對 3e00 的高位是否完整支援？現有 datasheet 曝光比公式
   文字只列 3e01／3e02，請確認 TOTAL 超過 4095 rows 時的規則。
   2560／3629 rows 已有紋理，不能只用高位問題解釋全部現象。
3. SECOND 的最小有效值、建議 TOTAL/SECOND 比，以及 5400=ff
   的意義為何？曝光比公式的取整方式與合法邊界為何？
4. 受光時 HDR knee／固定響應差異是否需額外校正？請提供 HDRC
   0x54xx 設定語意、校正流程，或對應文件的正確名稱／版本。
5. 外部 TRIGL 模式在 15 FPS 長曝光下，HDR point read／reset／
   readout blanking 應如何設定？有無已驗證的寄存器表？
6. 是否有相同 SC132GS revision／GS130WI 模組的已知問題或更新設定？
7. V2.6 p23 所列短曝光 gain 3e10..13 是否適用 single-frame HDR？
   目前 3e03[3:0]=b，嘗試 group hold 寫入 00 80 03 20 後，讀回仍全
   為 00。請確認可讀性、有效模式、gain 編码及更新規則。不能因 ACK
   就認定設定生效。原廠程式只有 DOL2_M 分支寫這組 gain。

新增 BLC 對照：3902=c5、auto BLC bit6 已啟用；只切換 bit6
off→on 後受光紋理仍在。原廠表中 301f、320c..f、3250..55、36xx、
39xx、5401..5418 共 47 個相關設定在兩眼讀回均符合。
補充核對及測試限制見 `IMAGE_REGISTER_AUDIT.zh-TW.md`。

不希望以影像去霧、任意平場補償或顯示曲線掩蓋問題；需要感測器
本身提供穩定 RAW，並保留亮部與暗部資訊。

## 證據索引

- `HAZE_RESULT.zh-TW.md`：完整調查及恢復狀態。
- `haze-flat-analysis.json`、`haze-flat-row-profiles.png`：白色表面統計。
- `haze-flat-means/comparison.json`：每条件寄存器、逐幀 hash。
- `haze-vendor-reset-means/comparison.json`：完整 reset 對照及失敗紀錄。
- `haze-second-wide-means/comparison.json`：SECOND／HDRC 比例掃描。
- `haze-spatial-analysis.json`：原場景比較；包含真實場景紋理，不當成純 FPN。
- `image-register-audit-20261012.json`：原廠相關設定的兩眼實讀。
- `haze-register-claims-means/comparison.json`：BLC／短 gain 診斷及復原。
- `FREE_RUN_30FPS.zh-TW.md`、`free-run-30fps-summary.json`：無 FSYNC
  來源的完整 reset 對照、實測 cadence 與下方霧帶差異。
- `haze-free-static-means/comparison.json`：六組有效 RAW 的讀回與 hash。
- `haze-free30-attempt-logs/`：先前只关位元再停 generator 的失敗紀錄。
- `linear-user-visual-confirmation-20261012.json`：使用者切回 Linear
  後確認看不到霧狀，及當時唯讀取得的模式／曝光／增益／寄存器。
- 板上 `/home/ubuntu/hdr-tuning-20261012/haze-*-20261012/` 保存完整
  packed RAW；Windows `haze-*-means/` 保存均值／時間變異及日誌。

![均勻受光表面的曝光與固定紋理](haze-flat-row-profiles.png)
