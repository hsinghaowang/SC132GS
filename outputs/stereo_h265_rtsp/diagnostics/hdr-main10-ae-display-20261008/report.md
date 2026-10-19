# HDR Main10 AE 與顯示修正

Main10 整合曾把 HDR AE 的 target 40% 改成 sensor gray 的 40%，同時移除
原本黑位 52、gamma 指數 0.38 的預覽曲線。原始灰階約 14% 的場景因此
看起來更暗，AE 也誤報達到曝光上限。先前 HDR 曝光校正本身沒有失效。

## 修正

- `StereoRtspServer` 選擇 HDR display 語意的 AE；Linear 模式仍直接量測。
- `process_luma10` 對 histogram 中位數套用既有 HDR 曲線，只改 AE 的
  量測值，不修改 R16 frame。Main10 編碼輸入仍為 0..1023 灰階。
- VLC Image adjust 保存 Gamma=2.63、Contrast=1.05、Brightness=0.97；
  Hue=0、Saturation=1、Brightness threshold off。這是接近舊曲線的
  顯示端近似，不是逐碼值完全相同的 LUT，也不會改寫 RTSP。
- VLC 設定為全域；觀看 Linear 或一般影片時應關閉 Image adjust。

## 實機結果

- HDR、ratio=256、AE auto、target=40%；左右眼實測 40%／41%。
- 記錄時曝光 1331 行，上限 1492，gain_index=0，brightness_limited=0。
  曝光會隨場景改變；初次收斂也觀察到 1409 行。
- RTSP 短測約 29.9 FPS，符合 HDR 30 FPS 模式，不是 Linear 60 FPS 驗證。
- VLC 顯示左右眼實際畫面，暗部提亮且仍可見燈管紋理。
- VLC Codec 資訊顯示 HEVC、2176x1280、30 FPS、Planar 4:2:0 YUV
  10-bit LE (I0AL)。未驗證 Windows compositor 或螢幕面板的 10-bit 輸出。
- Release 建置成功，六項 CTest 全部通過。這些既有測試主要驗證
  相機設定與像素轉換；HDR AE 的收斂證據來自實機 status。

正式服務已部署新版 binary。停止服務且確認 codec 無使用者後重新載入
iris_vpu，避開既知殘留 session 問題，再啟動並設定 AE 40%。
舊 binary 保留於板端 `main10-backup-20261008/before-hdr-ae-fix`。

證據：status.txt、tests.txt、rtsp.txt、vlc-before.jpg、vlc-live.jpg、
vlc-codec.jpg、vlc-adjust.txt、vlc-adjust.jpg。

VLC 顯示設定換算參考官方
[adjust.c](https://raw.githubusercontent.com/videolan/vlc/3.0.x/modules/video_filter/adjust.c)：
VLC gamma 的實際指數為設定值倒數，因此 2.63 接近原指數 0.38。

此修正不把有損 H.265 變成無損 RAW；保留的是 10-bit 灰階處理與傳輸。
