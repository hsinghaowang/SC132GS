# 遮光量測與後續比較狀態

2026-10-12，使用者確認遮住雙鏡頭後取得6组完整Main10解碼量測：
Linear/HDR各gain index 0、11、21，每组12幀。所有covered_check通過。
原始結果在black-calibration.json。Linear手動8ms，HDR TOTAL1492、SECOND1；
這些時間不能視為相同物理積分時間。

解碼灰階黑位中位數：

| gain | Linear 左/右 | HDR 左/右 |
|---|---|---|
|0|37/37|53/52.92|
|11|37/37|53.33/53.42|
|21|37.08/37.25|53.92/53.67|

因此較高HDR暗部像素值有一部分是黑位，不能直接代表細節。
HEVC、灰階轉換與12幀平均影響噪聲數值；這不是RAW噪聲或絕對動態範圍量測。

量測後AE-on與手動gain併用的復原命令被CLI正確拒絕。隨後獨立重新
套用HDR、AE on、target10、30FPS成功，使用者確認已移開遮擋。
calibrate_black.py已修正：只有原始AE-off時復原手動曝光與gain，
並保存/恢復HDR SECOND及曝光上限。

後續僅在測試腳本換算扣除黑位的相對target：
raw_percent=round(100*(black+(1023-black)*target/100)/1023)。
參考target20對應Linear23、HDR24。正式AE沒有部署這個換算。
Linear23在未限制曝光時解碼PTS為15FPS，故交易verification errno34並回復。
試調Linear30FPS VTS2800仍未通過，已撤回run-camera-profile.sh的試改。

另一次暫時限制Linear曝光16ms（1344rows）測試曾讀到約30FPS、gain9、
target23，但設定交易超過50秒，原platform helper PID36642仍曾存活。
之後SSH banner與RTSP DESCRIBE逾時，ping正常；復原HDR命令未完成。
此刻實際狀態未確認，不能宣稱已恢復HDR或串流。
需要恢復板端操作，檢查原交易與服務後恢復原HDR、AE on、target10、
max_fps30、max_exposure_us0、max_gain_index128。原SECOND1。

完整目標尚未達成；黑位校正與暗部改善的有效性尚待原場景實測。

後續短暫恢復SSH時，已確認PID36642不再存在，串流服務為failed，
設定檔已回到HDR / AE on / target10 / 30FPS / max_exposure_us0 /
max_gain_index128（revision137）。設定檔復原不等於串流復原。
核心日誌指出msm_vidc_check_max_sessions：5個2176x1280@30 HEVCE
工作階段超過上限4，接著input STREAMON回傳-12。這證實有編碼器
工作階段數量問題，但尚未證明其殘留原因或與SSH失效的因果關係。
確認/dev/video32與/dev/video33無fuser擁有者後，發起停止服務、
重載iris_vpu並由camera_platform restore復原；該程序尚未回傳，
新SSH再次逾時。使用者確認原Ubuntu終端仍可操作，已請其提供
程序狀態/wchan與最新核心日誌，避免在未辨明卡住位置前重複復原。

後續板端已恢復連線與HDR原設定。另已重現並改善編碼器重啟時
工作階段累積案例：明確REQBUFS(0)釋放buffer pools後通過5次
停止/復原，最後173幀持續更新的RTSP解碼驗證成功。詳見
../lifecycle/README.zh-TW.md。這不代表黑位校正或暗部改善完成。
