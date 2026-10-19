# 雙目深度診斷預覽

`preview.png`：校正後實體左眼與深度對照。暖色近、冷色遠；黑色為無效，未補洞。
色尺為 0.2–3.0 m，超出範圍僅截斷顏色，不截斷數值。

`depth-m.npy`：float32，1088×1280（寬×高），公尺，無效為 NaN。
座標對齊 `rectified-left.png`，數值為校正後相機的光軸 Z，並非射線距離。
`valid-mask.png`：255 有效、0 無效。`disparity-px.npy`：原始浮點視差，
包含匹配器的無效值，使用時必須套用遮罩。`rectification.npz` 保存 R/P/Q。
`report.json` 記錄來源雜湊、參數、版本、有效比例及檢查結果。

目前品質：棋盤格有分段及疑似錯配，天花板亦有可疑近距離條紋。
左右一致性通過不等於真實深度正確；此圖不接受為測距結果。
兩眼未同時偵測到完整棋盤格，沒有本張影像的角點幾何驗證。
距離尺度依賴候選校正的 20 mm 方格假設，沒有距離真值驗證。

重現（在專案根目錄 PowerShell 執行，會覆寫此產出目錄內同名檔案）：

```powershell
outputs\slam_benchmark\depth-preview-venv\Scripts\python.exe outputs\slam_benchmark\generate-depth-preview.py
```

環境：Python 3.12、opencv-python-headless 5.0.0.93、numpy 2.5.4。
程式只讀取既有快照與校正，不存取板端或串流，不重新擬合參數。
