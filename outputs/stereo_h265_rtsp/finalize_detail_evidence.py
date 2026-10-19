"""Produce a bounded-claim Traditional Chinese acceptance report."""
from pathlib import Path
import json,re,collections,statistics,hashlib
R=Path(__file__).resolve().parent/'contrast8-evidence-20261016';B=R/'board'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def fields(s):return dict(re.findall(r'([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)',s))
live=read(B/'live-600s/result.json');pc=read(R/'pc-live-600s/collection.json');post=read(R/'pc-final/collection.json');final=read(B/'final-state.json');analysis=read(R/'same-raw-analysis.json')
assert live['passed'] and pc['success'] and post['success'] and final['passed']
source=read(R/'source-sha256.json');audit=read(B/'final-source-audit.json');assert source==audit['source_manifest']==audit['actual']
assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==v for p,v in source.items())
samples=[json.loads(s) for s in (B/'live-600s/samples.jsonl').read_text().splitlines()];ae=[dict(t=s['elapsed_s'],**fields(s['ae'])) for s in samples if 'ae' in s]
assert all(s['mode']=='auto' and s['target_percent']=='10' and s['error_errno']=='0' for s in ae)
counts=collections.Counter();serial=None;last={};lost=0;fault=[];gaps=[]
for s in (B/'live-600s/events.txt').read_text().splitlines():
 e=list(map(int,s.split()));counts[str(e[2])]+=1
 if serial is not None and e[0]!=serial+1:lost+=e[0]-serial-1
 serial=e[0]
 if e[2]==4 and e[-1]:fault.append(e)
 if e[2]==3 and e[-1]==0:
  if e[3] in last and e[5]!=last[e[3]]+1:gaps.append(e)
  last[e[3]]=e[5]
assert not lost and not fault and not gaps and dict(counts)==live['event_counts']
log=(B/'live-600s/after-server.log').read_text()
def lastlog(prefix):return fields([s for s in log.splitlines() if s.startswith(prefix)][-1])
depth=lastlog('depth_mono8 ');timing=lastlog('processing_timing ');capture=lastlog('capture_timing ');gpu=lastlog('gpu_rectification active=')
assert depth['failed']=='0'
metrics=dict(passed=True,scope='board /depth, before H265',live=live,pc=pc,post=post,final=final,same_raw=analysis,source_match=True,ae_samples=len(ae),ae_command_generation_delta=int(ae[-1]['command_generation'])-int(ae[0]['command_generation']),ae_last60_exposure_range=[min(int(s['exposure_lines']) for s in ae if s['t']>=540),max(int(s['exposure_lines']) for s in ae if s['t']>=540)],depth=depth,timing=timing,capture=capture,gpu=gpu,event_replay=dict(lost=lost,gaps=gaps,faults=fault))
(R/'validation-summary.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
backup=read(R/'backup-download.json');state=read(R/'backup/state.json');binary=audit['binary_sha256'];raw=analysis['replay-current10'];historic=analysis['replay-final-history']
def streamrow(name,c):
 s=c['streams'][name];return f"| {name} | {s['observed_seconds']:.3f} | {s['frame_count']} | {s['decode_fps']:.3f} | {s['pts_gap_max_seconds']*1000:.3f} |"
def rawrow(label,x):return f"| {label} | {x['old_valid_fraction']*100:.3f}% → {x['new_valid_fraction']*100:.3f}% | {x['common_valid_pixels']} | {x['old_disparity_difference_px']:.4f} → {x['new_disparity_difference_px']:.4f} | {x['old_halfpx_fraction']*100:.3f}% → {x['new_halfpx_fraction']*100:.3f}% |"
def censusrows(label,x):
 return '\n'.join(f"| {label} cam{e['cam']} | {e['native_old']['distinct']} → {e['native_new']['distinct']} | {e['rectified_old']['census_bit_change_fraction']*100:.3f}% → {e['rectified_new']['census_bit_change_fraction']*100:.3f}% |" for e in x['eyes'])
report=f'''# 板端 depth 的 10-bit → 8-bit 細節量化驗證

2026-10-16，Asia/Taipei。有限條件驗證通過，保留 shared-detail 候選；AE auto、目標 10、既有校正與 FSYNC 版本不變。使用者已確認本輪優先改善板端 `/depth`，不包含 client 從 H.265 重新計算 depth 的驗收。

## 設計本質與結果

8-bit 無法無損保留全部 1024 個輸入階。目標是把有限 256 階分配給實際出現、對 Census 排序有用的訊號，而非維持真實明暗或只讓直方圖鋪滿。原 shared 模式的 BT.709 limited Y8 兼顧顯示，新 `shared-detail` 直接由黑位校正 mono10 合併兩眼 1024-bin 直方圖，使用有界全域 CDF 量化到完整 0–255。

兩眼同一張單調 LUT；density cap=4 倍均勻分佈，溢出只分配到未達上限的 bin，strength=1，時間平滑 500ms。端點固定 0／255，不在 percentile 硬截白；近黑／低動態回退線性量化。RAW10 與 AE 未修改；沒有新增 spatial CLAHE 或左右各自拉伸。

```mermaid
sequenceDiagram
    participant C as RAW10 Capture
    participant A as AE v3
    participant T as StereoDetailMapper
    participant D as Board DepthPipeline
    participant R as Stereo Worker
    participant E as H.265 Main
    C->>A: 校正後 mono10 與完整 RAW 高光統計
    C->>T: 雙眼 mono10、同一時間戳
    T->>D: 共用 LUT 的 0–255 bytes，submit8 同步複製
    D->>D: 既有整流、Census、立體匹配
    T->>R: move 唯一擁有的 pair
    R->>R: 僅顯示副本轉 Y16–235，GPU 整流
    R->>E: NV12 與 limited metadata
```

`StereoDetailMapper` 公開介面 C++17、move-only、PIMPL、借用 buffer 僅於呼叫期間有效；錯誤保留輸出及時間歷史。DepthPipeline 的複製與 worker 的唯一 ownership 分開，H.265 的範圍轉換與壓縮不會回寫 depth 輸入。保留舊 `--tone-map shared`；新模式要求既有 GPU map，未整流備援不會誤標範圍。

## 同一 RAW pair 的比較

歷史 RAW pair 先完成本機 NumPy 試算，再於備份後使用板端 production GPU matcher 離線重播。另在測前 AE 目標 10 狀態保存第二組 RAW，對兩組使用相同校正、相同 8-bit 匹配精度，另開相同演算法的 10-bit 精度參考。新 RAW 擷取時沒有 AE actor，保留 `exposure_association_validated=false`；測前目標 10 不能視為已證明的每幀曝光生效關聯。

獨立 NumPy LUT 與 C++ 新映射兩眼最大差均為 0；獨立整數 bilinear remap 與 GPU 保存的匹配影像逐位元相同，包含 10-bit 參考的預覽量化。以下 Census 是 5×5 的 24 個比較，排除影像邊界與校正無效區（含鄰域），相對 10-bit 整流訊號的位元差異：

| 輸入 | 原生使用階數：舊 → 新 | 整流後 Census 位元差異：舊 → 新 |
|---|---:|---:|
{censusrows('目前目標10',raw)}
{censusrows('歷史pair',historic)}

真實 GPU depth 結果（有效比例分母為完整 544×640，包含校正無效邊界）：

| RAW pair | 有效 depth 比例 | 三路共同有效像素 | 相對10-bit參考平均 disparity 差異 px | 差異超過0.5px比例 |
|---|---:|---:|---:|---:|
{rawrow('目前目標10',raw)}
{rawrow('歷史pair',historic)}

disparity 差異的前後比較使用各組相同的三路共同有效像素，避免拿不同有效集合直接比較。10-bit 是一致性參考，**不是深度真值**。目前 pair 新增 {raw['new_gained_unverified']} 個有效點、失去 {raw['new_lost']} 個舊有效點；新增點的真偽未證明，不能宣稱準確度提升或各點均無退化。

歷史 pair 也保留 clip2、clip4、clip8 的所有試驗。clip4 的原生 Census 保留與同像素參考一致性較佳，故用作候選；沒有依畫面美觀選擇。受限於兩組同一室內場景，本輪不是多場景泛化測試。完整量化不等於全域 RAW 數值 RMSE 一定下降；本設計優先保留匹配排序。

同一 RAW pair 的影像比較（左：舊 shared，右：新 detail；舊 Y16–235 僅為預覽展開到 0–255，原 bytes 另保存）：

![same RAW comparison]({(R/'replay-current10-comparison.png').as_posix()})

![same RAW depth]({(R/'replay-current10-depth-comparison.png').as_posix()})

## 板端運作驗證

本機完整 WSL 建置及板端各 22 項測試通過。實際 Adreno 635 對獨立 OpenCV fixture：identity 8/10-bit 差 0，現有 map 8/10-bit 最大差 1 code；新增 full-range Y8 的 fractional／border／眼序檢查也通過。未把編譯成功當成實機故障排除。

候選完整監測 {live['duration_s']:.3f} 秒，FSYNC session {live['session']}，雙眼約 30 FPS，error=0、error_count=0、skipped=0，沒有 session 更換。獨立重播保存事件，serial 遺失、每眼 trigger 跳號與 fault event 都是 0。事件數包含同 session 的監測前前綴，不能直接除以 600；event type=9／14 不代表 error=9／14。

PC 端實際解碼、錄影與 PTS 驗證：

| 串流 | 觀測秒數 | 解碼影格 | FPS | 最大PTS間隔 ms |
|---|---:|---:|---:|---:|
{streamrow('stereo',pc)}
{streamrow('depth',pc)}

兩路 PTS 單調、無解碼錯誤；最大間隔如表，不宣稱逐張零丟幀。stereo 為 2176×1280、Main/yuv420p、limited BT.709；depth 為 544×640。depth failed={depth['failed']}，曝光控制等待略過 {depth['withheld_transition']} pairs；故 depth 吞吐不必等於 30。原始影格時間戳、Y NPY、直方圖、截圖與兩路影片都保留。

AE {len(ae)} 份樣本全為 auto、target10、error_errno0；command_generation 增量 {metrics['ae_command_generation_delta']}，最後60秒 exposure rows 範圍 {metrics['ae_last60_exposure_range']}。目標沒有自動步階；場景有變化，不能從此宣稱固定場景的 settling time 或完全無亮度波動。現有高光保護語意與三組 pair holdoff 保留。

觀測中 tone CPU 平均 {timing['tone_mean_ms']}ms、GPU stereo remap 平均 {gpu['mean_gpu_ms']}ms，buffer 最長持有 cam0={capture['held_max_ms0']}ms、cam1={capture['held_max_ms1']}ms。期間有證據封裝背景 I/O，這些是運作觀測而非隔離效能 benchmark。

最後獨立確認：

| 串流 | 觀測秒數 | 解碼影格 | FPS | 最大PTS間隔 ms |
|---|---:|---:|---:|---:|
{streamrow('stereo',post)}
{streamrow('depth',post)}

## 範圍、備份與最終狀態

full-range 顯示測試初次 rawvideoparse 未明確設定 colour range，協商失敗；明確設定 colorimetry 後仍未通過此 GStreamer 編碼路徑，limited 對照成功。全部失敗紀錄保留，不據此推定硬體絕對不支援 full range。本次板端 depth 不經 H.265，因此獨立使用 256 階；影像端維持已驗證的 limited range。full/limited 是不同的格式契約，可參考 [FFmpeg 官方範圍說明](https://www.ffmpeg.org/ffmpeg-filters.html#scale)。

測前備份 {backup['files_verified']} 檔，包含原程式、wrapper、service/drop-in、設定、環境、校正及 owner；已下載驗證 archive 與各檔案。備份 SHA256 `{backup['sha256']}`。啟用獨立恢復 timer 後才暫停服務；測試前後仍沿用原 stereo/depth 校正，所有保護檔案 hash／owner／mode 相同。

候選 binary SHA256 `{binary}`；114 來源檔的本機 manifest、板端實檔及最終 source audit 相同。初版 source archive 與 final-source-update 分別保留，沒有在原版目錄覆寫 binary。編譯 CPU1–3、相機 CPU4–6、FSYNC CPU7。

開機 `{live['boot_id']}`、FSYNC srcversion `{state['software']['camss_srcversion']}` 未變；AE v3 policy SHA256 保持 `2885f8e582af12dce972b413c9e5e9753c6908d822642bf522444e4567a822fc`，未擴大修改 error=9／14 或回退核心。

完整驗收後解除本輪 25 分鐘恢復 timer。保留 `/etc/systemd/system/sc132gs-camera-rtsp.service.d/98-shared8-detail.conf` 指向獨立候選，舊95 drop-in與原 binary保留；單一候選 owner持有 video0/video3，AE10、既有map與Main 8-bit持續運作。出錯時的還原目標是測前已校正 shared8，不是早期未校正或 Main10 版本。

## 限制與證據

暗部雜訊也會被保留／放大，未新增降噪；256 階使用率、熵、Census 一致性及有效點增加均不足以證明真實深度精度。尚無深度真值、移動物體／室外／低照度多場景準確度與長期穩定性驗證。本輪證明的是兩組 RAW 的量化及匹配參考改善，加上有限時間運作正常。

`same-raw-analysis.json`、`offline-static/replay-*/` 保留來源、原生 mono10、Y8、實際 depth f32與比較；`board/live-600s/` 保存完整樣本、事件、server log、dmesg；`board/final-accepted/` 保存最終 owner/configuration。`pc-before/` 與 live 影片不同時間拍攝，不用作逐像素畫質證明。

初次離線證據封裝包含正在追加的 monitor 檔，逐檔雜湊失敗，已標為不接受並保留 `offline-fetch-failure.json`；之後對靜態資料重新下載並全部驗證。最終 board archive亦驗證所有檔案。未將中斷或失敗嘗試列為通過。
'''
if (R/'network-incident.json').exists():
 incident=read(R/'network-incident.json');reconnected=read(R/'pc-after-hotspot/collection.json')
 assert all(incident['checks'].values()) and reconnected['success']
 metrics.update(network_incident=incident,pc_after_hotspot=reconnected)
 (R/'validation-summary.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
 report+='''
## 驗收後的熱點連線中斷與恢復

完成原驗收與封存後，SSH 22、RTSP 8554 與 ping 同時逾時。使用者重啟 Windows 熱點後恢復；WLAN 紀錄保留 18:04:55 中斷、18:04:59 啟動及 18:05:05 板子 MAC 重新關聯事件。這段期間本工作沒有重啟相機程式、板子或更動網路設定。

恢復後獨立核對：相同相機 owner（含 PID/start_ticks）、同一開機與 FSYNC session25，error=0、skipped=0，AE auto target10、原校正與所有保護檔案仍相同，恢復 timer 已解除。證據支持熱點／連線問題；失聯期間沒有遠端觀測，不能保證每個 RTSP frame 曾送達。

恢復後再做65秒實際解碼與錄影：

| 串流 | 觀測秒數 | 解碼影格 | FPS | 最大PTS間隔 ms |
|---|---:|---:|---:|---:|
'''+streamrow('stereo',reconnected)+'\n'+streamrow('depth',reconnected)+'\n\n證據：`network-incident.json`、`host-wlan-events.json`、`final-independent-health.json`、`pc-after-hotspot/`。\n'
(R/'REPORT.zh-TW.md').write_text(report,encoding='utf-8');print(json.dumps(dict(passed=True,report=str(R/'REPORT.zh-TW.md'))))
