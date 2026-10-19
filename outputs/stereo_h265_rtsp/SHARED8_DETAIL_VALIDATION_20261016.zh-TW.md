# shared8 整流與 depth 細節量化驗證

日期：2026-10-16，Asia/Taipei。使用者確認本輪優先改善板端 `/depth`，不是 client 從 H.265 重新計算 depth。

## 實作

- shared8 支援既有 Q5 GPU stereo 校正圖，輸出 cam1|cam0、2176×1280、H.265 Main 8-bit。
- `--tone-map shared-detail` 從黑位校正 mono10 的雙眼合併直方圖直接量化到 0–255；全域 CDF 密度上限4、500ms時間平滑、近黑／低動態回退線性量化。兩眼共用同一張單調 LUT。
- depth 在壓縮前取得完整256階。視訊用 `--display-range limited`，只在 depth 完成同步複製後轉換顯示副本的範圍；AE仍使用10-bit。
- 保留原 `--tone-map shared`；shared-detail要求GPU校正圖，避免未整流路徑的範圍錯標。

## 元件與同一 RAW pair

本機完整WSL建置與板端各22項CTest通過。Adreno 635對獨立OpenCV整流fixture：identity差0、目前校正圖最大差1 code，涵蓋8/10-bit、full/limited邊界與眼序。

獨立NumPy LUT與C++輸出逐位元一致；整數CPU整流與保存的GPU匹配輸入一致。以下Census以校正有效區內5×5鄰域比較，相對10-bit整流訊號；disparity以三路都有效的相同像素比較。

| RAW pair | 原生使用階數（cam0／cam1） | 校正後Census位元差異（cam0／cam1） | 有效depth比例 | 相對10-bit參考平均disparity差異 |
|---|---|---|---|---|
| 目前目標10狀態下保存 | 219／219 → 256／256 | 5.888%／7.245% → 1.447%／2.207% | 16.116% → 16.651% | 0.1436 → 0.0420 px，41,198共同有效像素 |
| 歷史pair | 214／210 → 256／256 | 6.623%／6.888% → 4.062%／3.766% | 17.523% → 17.752% | 0.0877 → 0.0660 px，44,141共同有效像素 |

另保留clip2／4／8的試驗，依Census保留及參考一致性選擇clip4。10-bit是匹配參考，並非深度真值；新增有效點的真偽尚未證明。取新RAW時沒有AE actor，測前目標10不代表已驗證每幀曝光生效關聯。

## 板端驗證與保留狀態

- 測前備份20個程式／wrapper／設定／service／校正檔案，下載並逐檔驗證；備份archive SHA256：`388e5f947e92c6bed29305ac14a77637e7efe3733487d91c9d93c4b7e8b37174`。
- 獨立候選binary SHA256：`09dc5e0612de3658189790103d6cf6d219d03cc951acb274425233ee17bc6769`。
- 保留原校正、AE v3及FSYNC模組`E966374A47464C038D0632F`；編譯CPU1–3、相機CPU4–6、FSYNC CPU7。未修改其他工作的FSYNC修正或核心。
- 601.485秒板端監測：session25維持，error／error_count／skipped皆0；獨立事件重播無serial遺失、每眼trigger跳號或fault。
- PC兩路各實際解碼600秒：stereo 29.967 FPS、depth 29.252 FPS，PTS單調、無解碼錯誤。另通過65秒確認。
- 驗收後曾同時無法ping／SSH／RTSP。使用者重啟Windows熱點後恢復；相同程式PID/start_ticks、開機與FSYNC session25，未重啟相機程式。恢復後兩路再實際解碼65秒，均約30 FPS。
- 驗收後解除恢復timer，維持候選shared-detail、Main 8-bit、AE auto target10。所有測前保護檔案hash／owner／mode相同。

視訊full-range協商測試未通過此GStreamer路徑，limited對照成功；不能據此推定硬體絕對不支援full range。板端depth不經H.265，仍使用完整0–255。

## 證據與限制

完整資料保留在本機`contrast8-evidence-20261016/`：`REPORT.zh-TW.md`、`same-raw-analysis.json`、`validation-summary.json`、`board/`、原始RAW、depth f32、影片、逐影格時間戳、截圖與雜湊封存。大型資料未納入Git。

驗證使用當時工作樹的候選來源封存；其他工作的獨立depth precision benchmark目標不屬於本次提交，也未連結到串流程式。

暗部雜訊亦可能被保留／放大，未新增降噪。256階使用率、熵、Census一致性與有效點增加不能單獨證明真實精度；尚無真值、多場景準確度或長時間穩定性證明。
