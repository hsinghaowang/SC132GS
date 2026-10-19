# 未提交修改分組紀錄（2026-10-16）

本輪依用途新增 12 個 commit，原有 `3a95ae7` GPU／Main10 RTSP 整合 commit 維持不變。
下表為功能、測試與實驗紀錄的 11 個 commit；本文件所在的第 12 個 commit 保存 Git 產物忽略規則與 binary attributes。

| Commit | 用途 |
| --- | --- |
| `eeea801` | IMU FSYNC、C++17、Linux transport |
| `a29d4e0` | 共用 owning stereo／IMU 擷取 library |
| `e5fb12b` | RTSP 可選共用擷取 adapter |
| `e26cd4c` | ROS 2 影像／IMU publisher |
| `3b427ce` | FSYNC 脈波限制與長測稽核 |
| `26a9840` | OpenVINS／ROS replay benchmark |
| `bcc845a` | 雙目校正擷取與驗證 |
| `ea86587` | 離線／板端 GPU 深度實驗 |
| `bd9e1ca` | 相機模式與時序實驗摘要 |
| `d6f5788` | 凍結校正與 rectification matrices |
| `0167803` | 凍結來源、建置定義與實驗 provenance |

原始碼、設定、校正參數、必要 IMU audit CSV 與精簡驗證紀錄已提交。
約 6.8 GB 初始未追蹤內容中的影像／影片、原始陣列、大型 trace、虛擬環境、下載的 SDK／library、編譯產物和執行中狀態檔留在本地，透過 `.gitignore` 排除，沒有刪除。
既有已追蹤的必要校正資產繼續追蹤。PDF／NPZ 使用 binary attributes，避免 checkout 的換行轉換破壞檔案。

本輪只在 Windows／WSL 進行 Git 與離線檢查，沒有接管板端硬體或重新部署。

## 本輪檢查

- IMU：WSL Ubuntu 24.04、GCC 13.3 Release build 與 `icm42688-fsync` CTest 通過。
- 共用 Capture library：Release build、probe link 與 `gs130wi-api-contract` CTest 通過。
- FSYNC：實際 callback 的虛擬時間／GPIO／IRQ fixture 通過 26,000 個完整脈波。
- 校正擷取：C++23 implementation build 與 C++17 public-header compile check 通過。
- PC 深度預覽：3 項 unittest 通過；測試不取得相機串流。
- 所選 Python／JSON 語法檢查與 53 支 shell 的 `bash -n` 通過。
- RTSP 完整本機重建停在 CMake configure：此 WSL 缺少 OpenCL include／library，不能宣稱本輪 RTSP build 通過。
- ROS 2 adapter 本輪未重建；原板端測試結果按歷史文件保留。

部分凍結 patch、compiler 輸出與繪圖 SVG 含原有 whitespace 警告，保留原有文字，不以格式整理改寫歷史證據。
歷史失敗與中止的長測仍保留為失敗／中止，不能把分段時間合併視為通過。

本輪沒有 push。
