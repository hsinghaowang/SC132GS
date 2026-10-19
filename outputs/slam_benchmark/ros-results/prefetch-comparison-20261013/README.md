# 提前解碼候選：未通過

2026-10-13，Windows 離線分析；本次接續工作沒有連線或增加板上負載。另一個工作正在長時間測試，保留板上串流與設定。

完整回放都正常退出且初始化後位姿完整，但 IMU 漏收：MH 526／448 筆，V2 308／332 筆。最後 MH 第 2 次與相機重新啟動重疊；前三次已漏收。沒有合格候選效能比較，零漏收原發布器仍為基準。

- `report.html`：結論、逐次資料與限制。
- `comparison.json`：分段時間、背景重疊、輸入完整性與逐筆診斷。
- `../*-paced-prefetch-*/imu-receipt-audit.csv`／`.json`：各次漏收索引、時間與連續区段。
- `raw-sha256.json`：90 份原始板上證據，保持原內容。
- `tested-sources/`：雜湊相符的受測發布器來源。同期早期版本保存在 `../publisher-comparison-20261013/tested-sources/`。
- `verification.json`：原始證據／来源驗證與本機分析器雜湊。

離線重新產生資料時，依序執行 `analyze-ros-replay.py`、`analyze-prefetch.py`、`audit-prefetch-imu.py`、`analyze-publisher-comparison.py`、`finalize-publisher-audit.py`，皆位於 `outputs/slam_benchmark`。需 NumPy，不需要連線板子；最後一步保存來源並重建本機證據清單。

後續板上驗證待長時間測試完成後進行：先驗證 IMU 零漏收與精度，再比較延遲。先檢查與影像同時發布的 IMU best-effort 傳輸；若比較 reliable 傳輸或不同發布排程，必須把 QoS／排程變更列為獨立變因，保留目前受測來源與原始資料。僅依單筆漏收模式不能確認根因。提前解碼量測起點也已變更，不是實體曝光到位姿的證明。
