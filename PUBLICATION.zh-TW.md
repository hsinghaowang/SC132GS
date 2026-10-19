# 相機程式與驗證紀錄發布（2026-10-19）

本次沿用 SC132GS 遠端 main 歷史，將來源工作區 `217901d68f7a9332019390c798db86019d9c3cc0`
的相機相關已提交快照匯入。來源工作區和獨立 repository 的 tree／parent 不同，因此 commit SHA 不同。
前一個遠端 commit 為 `f6db1b09e514ab18af1f9d23bd1a7e5a6163678f`。

匯入範圍包含 `sc132gs_v4l2_probe`、`sc132gs_hdr`、`stereo_h265_rtsp`、
`gs130wi_capture`、`gs130wi_imu`、`gs130wi_ros`、`slam_benchmark`、
`fsync-optimization-20261016`，以及已提交分組紀錄、attributes 和 ignore 規則。
保留原相對路徑，使 CMake sibling dependencies 及校正／驗證文件可以相互引用。

[PUBLICATION.json](PUBLICATION.json) 列出全部 2,795 個匯入檔案的原始 Git blob ID。
發布前已比對 staged tree，每個匯入檔案均與來源 commit 相同。
來源工作區未提交的修改、未追蹤實驗檔、下載的 vendor source 與本機建置產物沒有匯入。

## 最新按需取像驗證入口

- [設計與支援 profile](outputs/stereo_h265_rtsp/ON_DEMAND.zh-TW.md)
- [完整驗證紀錄](outputs/stereo_h265_rtsp/on-demand-evidence-20261016/README.zh-TW.md)
- [43 項 lifecycle 與重測來源](outputs/stereo_h265_rtsp/on-demand-evidence-20261016/lifecycle-completed/result.json)
- [兩路 PC 解碼](outputs/stereo_h265_rtsp/on-demand-evidence-20261016/pc-decode/collection.json)
- [板端資源釋放讀回](outputs/stereo_h265_rtsp/on-demand-evidence-20261016/board/final-state.json)

成功、失敗、中止、後續重測各自保留原紀錄；既有 kernel fault 不宣稱由按需取像修正。
2026-10-19 發布檢查只在 WSL Ubuntu24.04／GCC 13.3.0 重建 portable checks，9/9 CTest 通過；
沒有重新部署或接管板端。完整板端 22 項 CTest 與 runtime 結果是 2026-10-16 的驗證。

歷史 compiler 輸出、topology、patch 與凍結來源包含既有 whitespace 警告；本次保持來源 blob，沒有格式重寫驗證證據。
