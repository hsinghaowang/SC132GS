# Linear 60 FPS 預設與提交檢查（2026-10-12）

使用者決定：預設 Linear、全解析度、60 FPS，HDR 調校暫停。
AE on、target30，顯示曲線保持 gamma=1。感測器模組預設明確為
`external_trigger=1 hdr=0`；`sc132gs-camera reset` 使用相同設定並保存。
開機服務仍恢復最後保存的設定，使用者之後保存 HDR 會覆蓋這個選擇。

Release 建置完成，8/8 CTest 通過，CameraConfiguration API 另以 C++17
編譯與執行通過。Python 保存檔驗證、reset、保存 YAML、開機服務使用的
restore 入口皆已實機通過。本次未重開板子，未重新載入 CAMSS 或感測器驅動。

復原後 Windows/PyAV 實際解碼 482 張、2176×1280、HEVC 10-bit，
PTS=60.0018 FPS，16 張取樣影像 hash 不同。見
`linear60-default-restored/decode.json`、`decoded.png`。
板上設定、部署檔 SHA256、CTest 紀錄、編碼／短段解碼及保存檔見
`linear60-default-proof/`。

首次部署時，板上持續軟體解碼 8 秒造成驗證降速，部署腳本回復原程式。
其失敗紀錄仍保留於板上 sc132gs-camera-tests。Windows 對原程式實際
解碼 60.0018 FPS。第二次部署後首次 viewer 測試為 52.62 FPS，後續
穩定測試為 59.9994 FPS；沒有刪除失敗證據或把它算成通過。
復原驗證改為先確認 8 秒編碼 AU cadence，再解碼 5 張確認尺寸及內容，
不以板上軟體解碼吞吐率代替相機實際 FPS。Windows 完整解碼仍獨立驗證。

HDR 固定霧狀尚未修復，RAW、寄存器審核與真正無外部觸發的 30 FPS
量測保留，詳見 HAZE_RESULT、FREE_RUN_30FPS、HDR_VENDOR_REPRO。
`HDR_VENDOR_EVIDENCE_20261012.zip` 提供原廠討論用精選證據；大型
RAW／均值壓縮檔保留於原板子和本機，沒有加入 Git。
