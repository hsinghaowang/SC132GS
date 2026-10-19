# HDR Main10 切換驗證

2026-10-08，依使用者要求啟用 HDR。

- 使用既有相機控制器切換 HDR、full size、30 FPS、AE on、target 40%。
- 兩眼 hdr_enabled=1，hdr_ratio=256，曝光控制為 hdr_total_rows。
- 正式服務仍使用 Main10 binary，輸出 2176×1280、20 Mbps 設定。
- 10 秒 RTSP/TCP 接收 302 個 access units，約 30.10 FPS。
- h265parse 確認 Main10、luma/chroma 10-bit、30/1 FPS。
- VLC 實際顯示雙眼畫面，解碼格式為 Planar 4:2:0 YUV 10-bit LE。
- AE 實測亮度 14%／15%，曝光到上限 1492 行、gain_index=0、
  brightness_limited=1、error_errno=0。未達到線性碼值 target 40%。
- 沒有套用 HDR 預覽提亮曲線，沒有修改 gamma、HDR ratio 或增益上限。

本次是模式切換及短時間串流／解碼確認，沒有執行 HDR 五分鐘長測，
也沒有驗證 stereo 深度品質或螢幕面板位深。

證據：status.txt、rtsp.txt、caps.txt、vlc-live.png、vlc-codec.txt/png。
