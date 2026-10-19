# RTSP 與 Main10 編碼器生命週期驗證

2026-10-12，RUBIK Pi 3，SC132GS HDR / AE on / target10 / 30 FPS。

RTSP client 與硬體 V4L2 encoder 是不同的工作階段。Server 持有一個
Main10Encoder；client 的 media 只有 appsrc / parse / RTP packetizer。
播放器斷線不應為其他使用者重新開啟硬體編碼器。

本次修改：RTSP session timeout 明確設為30秒，沿用每秒pool cleanup
和stop_on_disconnect；停止server時先取消listener並關閉clients、
移除sessions。新增client/media與encoder開關日誌。
Main10Encoder release對STREAMOFF重試EINTR，檢查munmap結果，
munmap後以REQBUFS(count=0)釋放兩組buffer pools，最後close。
close不重試EINTR，避免其他執行緒重用fd後誤關閉。

## 實測

- 強制終止6次軟體解碼播放器：after-disconnect.log中每次client
  closed / media unprepared，整段只有一次encoder opened。
- 第一版只有STREAMOFF重試與close日誌：stop-1/2/3.log顯示close
  成功，但第三次restart失敗，kernel-before-recovery.log列出5個
  2176x1280 HEVCE instances，上限4。故RTSP cleanup及close成功
  不足以證明驅動已釋放instance。
- 加入REQBUFS(0)後，在無codec持有者時重載iris_vpu，清除先前
  累積狀態，再測5次停止/復原：全部通過；pool-stop-1..5.log每次
  closing/closed，沒有encoder_release錯誤。最後仍可編碼解碼。
- final-decode/decode.json：173個decoded frames，173個不同RGB
  hashes，2176x1280，PTS29.995 FPS；軟體解碼wall22.37 FPS。
  這證明串流時間戳約30FPS、影像持續更新，不能宣稱此軟解器wall30FPS。
- final-status.txt：HDR / AE on / target10 / measured_fps_x10=299，
  max_exposure_us0 / max_gain128 / revision137。
- 編譯成功，現有CTest7/7通過。這些單元測試不包含codec硬體生命週期。

這些結果支持明確釋放buffer pools改善此重現案例；尚未證明所有
driver/firmware洩漏原因，未驗證長時間運轉、網路黑洞session逾時、
多client同時播放或SIGKILL server。未加入自動重載kernel module。
部署前binary備份：/home/ubuntu/hdr-tuning-20261012/server-before-lifecycle。
HDR與Linear暗部細節改善的原始目標仍未完成。
