# 使用者提供的 HDR 暫存器排查圖片：核對結果

2026-10-12。將四張圖片視為待驗證的建議，對照 SC132GS V2.6
datasheet、D-Robotics 原廠 HDR 表、目前驅動及實機讀回。圖片未附
FAE 文件或位元定義，因此不能將其中的寄存器標籤直接當成規格。

## 結論

完整 HDR 初始化、自動黑位校正及時脈設定都值得檢查；但目前並非
只把 Linear 的曝光值改成 HDR。驅動在 STREAMON 載入完整原廠
HDR 表，再加外部觸發設定；兩眼此次核對的 47 個原廠表設定全數
相符。這證明設定載入／讀回，不能證明 15 FPS 長曝光影像品質合格。

遮光時固定偏差小，受光並拉長 HDR TOTAL 後固定紋理明顯增大。
目前較支持 HDR 受光響應／校正問題；未找到具體內部根因。

## 各項說法與證據

| 圖片的說法 | 核對結果 |
|---|---|
| 3933／3934 是自動 FPN／BLC 開關，需寫魔術數字 | 現有 SC132GS 文件沒有這兩個位址的位元定義。實讀為 1f／ff；非零不代表已啟用，也不能據此決定寫入值。原廠 HDR 表未設定這兩個位址。 |
| 強制開啟自動 BLC 可以修復 | V2.6 p32 明確定義 3902[6]。兩眼都是 c5，bit6 已為 1。補做 off→on 對照後，受光紋理未消除；此 toggle 不等於已證實能清除全部內部校正狀態。 |
| 3220～3225 是長短曝光比控制 | 不正確。3220[6] 是 HDR enable，3222[1] 是 trigger enable、[5:4] 是 HDR point read。曝光使用 3e00..02／3e31..32，HDRC 比例用 5400（p19、21、29）。3225 在本板有既往霧帶 A/B 證據，仍維持 00。 |
| 3e08／3e09 同時是 analogue／digital gain | 不精確。p23 長曝光 analogue／fine 是 3e08／09，digital／fine 是 3e06／07；表中另列 HDR 短曝光 3e12／13 及 3e10／11。是否適用目前 single-frame 路徑仍需確認。 |
| 3250～3255 是 DPC／網格修正；HDR 可能沿用 Linear | 尚無資料支持 DPC 這個功能標籤。實讀 cc 02 11 8f 0a 73，與原廠 HDR 表一致；目前 Linear 表是 cc 02 05 73 05 3b，並未沿用。V2.6 修訂紀錄還記載刪除舊 DPC 章節，不能由舊通用位址猜測。 |
| 36xx 類比設定直接抄 Linear、只改曝光 | 驅動有獨立完整 HDR 表，原廠表中 36xx 設定此次全數讀回相符。3630=5c、3638=2a。原廠 HDR 表沒有設定 3640；實讀 00，不代表失效。各位元的 VREF／比較器語意未在现有文件中找到。 |
| 301f 時脈分頻可能偏離原廠設定 | 實读 e0，與原廠 HDR 表一致；Linear 表是 45。降低外部觸發頻率時沒有改這個值。讀回不能代替實際時脈／供電的電氣量測，也沒有資料支持把該 byte 直接換算成某個分頻數。 |
| 因降低 FPS 而放大 VTS，導致霧紋 | 正式 HDR 15 FPS 的 VTS 仍為 4500（11 94），與原廠 30 FPS HDR 表一致；降低 FPS 靠 FSYNC cadence。先前 VTS=9000 僅為 external/free-run 等亮度診斷，4500／9000 的長曝光皆有紋理。 |
| 改成固定 VTS 的 60／45 FPS profile，再加 Dummy Line | 圖片未提供 SC132GS 對應完整 profile 或有效寄存器定義；目前依據是原廠 30 FPS HDR 表，不能從這個建議直接推導可用設定。 |
| ISP 合成兩張曝光時對不齊，造成格狀 | 本管線使用感測器 single-frame HDR RAW，沒有 ISP 合成長短兩張圖的步驟。異常已存在於完整 packed RAW，不能歸因於本管線沒有執行的 ISP 重構。 |

## 新增的實機 RAW 對照

四組條件均為 external HDR 15 FPS、TOTAL=4350、SECOND=1、
gain index=0、VTS=4500，每眼各 32 幀完整 RAW，所有幀 hash 不同。
依序為 baseline／BLC off→on／短曝光 gain 1x 嘗試／baseline 重測。
量測後復原原 HDR AE target=30，durable/runtime 設定不變，實際
解碼驗證通過，紀錄 `restored=true`、無 capture error。

### BLC 重新啟用

只切換 datasheet 定義的 3902[6]：c5→85→c5，保留其他位元。
跳過前 32 幀後取得 32 幀；兩眼最後讀回 c5，未消除原場景紋理。
左眼 RAW 中位數 baseline=275.53、重啟 BLC=276.38、重測=276.66；
右眼 289.11／289.00／289.34。空間殘差也沒有消失。
這是原場景對照，包含場景自身細節，不當成均勻平場 PRNU。

### 短曝光專用增益

3e03[3:0] 讀回 b，符合 p23～26 LUT 控制方法。按文件嘗試
3e10..13 = 00 80 03 20（digital／fine／analogue／fine 1x），
使用 group hold 後讀回仍全為 00。尚未確認值生效，因此該組不能
稱為有效的短曝光 1x 品質 A/B，更不能宣稱已驗證獨立短曝光 gain。
RAW 未見霧紋消失，但這不能證明所要求的 gain 變更真的套用。

原廠程式僅在 `DOL2_M` 分支寫這四個 gain 位址；其單幀 HDR
`NORMAL_M + extra_mode=1` 路徑沒有這項寫入。需原廠確認目前晶片
revision 的 register 可讀性、模式適用性及更新規則，不能只因
I2C ACK 就宣稱增益控制成功。

## 來源與證據

- 原廠 HDR 表：
  https://github.com/D-Robotics/x5-libcam-sensor/blob/main/sc132gs/inc/sc132gs_setting.h
- 原廠 gain 控制分支：
  https://github.com/D-Robotics/x5-libcam-sensor/blob/main/sc132gs/sc132gs_utility.c
- 本地 datasheet 文字：`../../../../tmp/pdfs/sc132gs-v2-register-audit/full-text.txt`，
  p19、21、23～26、29、32 與修訂紀錄。
- 驅動：`../../../sc132gs_v4l2_probe/sc132gs.c` 的 `sc132gs_write_mode()`。
- `image-register-audit-20261012.json`：兩眼逐位址讀回、47 個原廠值比較。
- `haze-register-claims-means/comparison.json`：四組 RAW、hash、寄存器、復原。
- `haze-spatial-analysis.json`：同 CFA 殘差與 RAW／luma 飽和比例。
- 板上 `/home/ubuntu/hdr-tuning-20261012/haze-register-claims-20261012/`
  保存完整 packed RAW；Windows 保留均值、變異、日誌。

未修改 3933／3934、3640 或其他缺乏定義的類比位元。
沒有將這些未證實的建議併入正式驅動；霧狀問題仍未修復。

後續已補測真正停止 FSYNC generator、GPIO18/19 INPUT 的完整
reset/init 自由運行。可維持 30 FPS，特定下方霧帶有明顯差異；
15 FPS 長曝光整片紋理仍在。見 `FREE_RUN_30FPS.zh-TW.md`。
