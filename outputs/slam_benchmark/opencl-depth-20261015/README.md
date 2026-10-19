# QCS6490 OpenCL 雙目深度可行性測試

最新合併 GPU 校正／縮放實作與驗證見 [RECTIFICATION.zh-TW.md](RECTIFICATION.zh-TW.md)。
本文件以下 501／270 ms 為第一輪歷史結果；後續匹配最佳化的 600 次結果保存在
`wide-active-600/benchmark.json`（中位 29.646 ms、p95 31.532 ms，不含校正）。
目前含 GPU 校正與全尺寸上傳的 30 次結果為中位 33.354 ms、p95 35.285 ms，
仍未宣稱完整即時管線達到 30 FPS。

板端 OpenCL 枚舉並執行 GPU 成功。執行階段回報名稱為 `QUALCOMM Adreno(TM) 635`，
驅動為 OpenCL 3.0 Qualcomm 0855.3；這是驅動原樣回報，沒有用產品規格中的名稱覆寫。
沒有安裝套件、切換 GPU 驅動、重啟相機或修改校正。

## 測試內容與結果

- 固定使用離線深度預覽的同一張 2176×1280 RTSP 快照與候選校正。
- PC 還原逐眼鏡像、校正到 544×640／眼，將灰階資料傳到板端測試目錄。
- C++17／RAII 測試程式僅選取 `CL_DEVICE_TYPE_GPU`，沒有 CPU OpenCL 備援。
- GPU 實作為 5×5 Census、5×5 Hamming 箱型成本、128 視差、整數 WTA、
  唯一性 10%、雙向一致性 1 像素。這是 Census BM 原型，並非 SGM/SGBM。
- 每次上傳兩眼到 GPU，執行雙向匹配與一致性，讀回視差；5 次暖機後量測 30 次。
- 初版中位數 500.717 ms；調整 winner 核心，讓 32 個 lane 協作一個像素、
  合併視差方向記憶體讀取後，中位數 270.475 ms，p95 271.875 ms。
- 改良版 GPU 核心總時間中位數 266.826 ms；這不是 GPU 最佳效能或硬體上限。
- 兩版有效比例皆約 14.28%；整張 348,160 個左眼 Census 描述子與 CPU 參考一致，
  182 個跨視野樣本的視差／唯一性判定與獨立 scalar CPU 參考一致。
- 時間包含 CPU→GPU 資料上傳及視差讀回，不含 PC 校正、SSH 傳輸、深度換算、
  編碼、網路或即時擷取。固定影像反覆測試不等於完整即時管線效能。
- 相機原有服務維持 active 且 MainPID=2752 未變，設定檔 SHA256 未變；
  測試後另行解碼 31 張原始 RTSP，PTS 速率約 30 FPS。

## 判斷

已證明板上 GPU 可以執行實際雙向匹配，不僅是存在 OpenCL 函式庫。
尚未達到 30 FPS：單張匹配已約 270 ms，離 33.3 ms 預算仍遠。
此原型與目前 PC SGBM 演算法不同，不能將時間視為等品質的加速比較。
未將原型取代目前即時串流，未驗證深度準確度。

主要瓶頸是成本產生／彙整與記憶體存取，而非 Census 特徵或左右一致性。
目前成本暫存約 85 MiB。後續若採此路線，應改為 tiled／向量化成本處理、
減少外部記憶體往返，再評估具路徑成本的 SGM 與校正／擷取整合；
不能藉由這個 BM 原型宣稱已加速原本 SGBM。

## 檔案與重現

`before.json`／`after.json` 為唯讀板端盤點；`benchmark-baseline.json` 與
`stereo_bench-baseline.cpp` 保留初版；`benchmark.json` 與 `stereo_bench.cpp` 為改良版。
`gpu-preview.png`、`depth-m.npy`、`valid-mask.png` 為此固定影像的診斷結果，無補洞。
深度單位公尺、無效 NaN，尺度仍依賴候選校正的 20 mm 方格假設。

專案根目錄 PowerShell：

```powershell
python outputs\slam_benchmark\opencl-depth-20261015\run.py before
outputs\slam_benchmark\depth-preview-venv\Scripts\python.exe outputs\slam_benchmark\opencl-depth-20261015\benchmark.py
python outputs\slam_benchmark\opencl-depth-20261015\run.py after
```

使用既有 SSH `ubuntu@192.168.137.226`；只在板端
`/home/ubuntu/opencl-depth-20261015` 寫入測試輸入、原始碼與可執行檔。
以 `g++ -std=c++17 -O3 ... -lOpenCL` 編譯。重跑會覆寫本次實驗的同名輸出。
各 GPU stage 的中位時間與輸入／程式 SHA256 記錄於 `benchmark.json`。
