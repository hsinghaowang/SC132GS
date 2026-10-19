"""Compare measured autonomous cadence and spatial RAW residuals."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).parent
raw=json.loads((ROOT/'haze-free-static-means/comparison.json').read_text())
analysis=json.loads((ROOT/'haze-spatial-analysis.json').read_text())
cases={c['name']:c for c in analysis['cases'] if c['source']=='haze-free-static-means'}
summary=dict(method=analysis['method'], restored=raw['restored'], cases=[])
for c in raw['cases']:
    a=cases[c['name']]
    summary['cases'].append(dict(name=c['name'], mode=c['configuration']['mode'],
        total_nominal_rows=c['configuration']['rows'], second_ticks=c['second_ticks'],
        gain_index=c['configuration']['gain'], fsync_gpio_input_no_source=c['fsync_gpio_input_no_source'],
        eyes=[dict(eye=e['eye'], rate=e['rate'], sensor_luma_median=e['sensor_luma_median'],
            unique_frames=c['eyes'][e['eye']]['unique_frames'],
            bottom128_spatial_residual=e['bands'][-1]['spatial_residual'],
            bottom128_relative_residual_percent=e['bands'][-1]['relative_residual_percent']) for e in a['eyes']]))
(ROOT/'free-run-30fps-summary.json').write_text(json.dumps(summary,indent=2)+'\n')

plt.rcParams['font.family']='Microsoft JhengHei'
plt.rcParams['axes.unicode_minus']=False
fig,axes=plt.subplots(2,2,figsize=(12,8),sharex=True)
panels=(('1492 rows / SECOND=1：相同曝光',
    [('external-short30-repeat','外觸發 30 FPS'),('no-fsync-vendor-short30','無外觸發 30 FPS')]),
    ('1259 rows / SECOND=79：下方霧帶對照',
    [('external-safe30','外觸發 30 FPS'),('no-fsync-vendor-safe30','無外觸發 30 FPS')]))
for col,(title,series) in enumerate(panels):
    for eye in range(2):
        ax=axes[eye,col]
        for name,label in series:
            bands=cases[name]['eyes'][eye]['bands']
            ax.plot([b['row']+63.5 for b in bands],
                [b['spatial_residual'] for b in bands],'-o',label=label)
        ax.set_title(title+' / '+('左眼' if eye==0 else '右眼'))
        ax.set_ylabel('同 CFA 空間殘差中位數（RAW code）')
        ax.grid(alpha=.25)
        ax.legend()
        ax.set_ylim(bottom=0)
        if eye==1: ax.set_xlabel('影像列位置')
fig.suptitle('完整 HDR 初始化；無外觸發時 GPIO18/19 設為輸入\n'
    '每組每眼 32 幀平均；包含原場景紋理，並非純 FPN 或 SNR')
fig.tight_layout(rect=(0,0,1,.92))
fig.savefig(ROOT/'free-run-30fps-residuals.png',dpi=160)
plt.close(fig)

fig,axes=plt.subplots(2,3,figsize=(12,12))
for col,(name,label) in enumerate((('external-short30-repeat','外觸發 30 FPS / 1492 rows'),
    ('no-fsync-vendor-short30','無外觸發 30 FPS / 1492 rows'),
    ('no-fsync-vendor-long15','無外觸發 15 FPS / 4350 rows'))):
    for eye in range(2):
        path=ROOT/'haze-free-static-means'/name/f'eye{eye}.mean.luma.png'
        axes[eye,col].imshow(plt.imread(path),cmap='gray',vmin=0,vmax=1,interpolation='nearest')
        axes[eye,col].set_title(label+' / '+('左眼' if eye==0 else '右眼'))
        axes[eye,col].axis('off')
fig.suptitle('RAW 32 幀平均的線性灰階預覽；相同黑位校正，gamma=1\n'
    '右欄曝光較長、亮度較高；不能把其殘差倍數當成純雜訊倍數')
fig.subplots_adjust(top=.90,bottom=.02,left=.02,right=.98,wspace=.08,hspace=.20)
fig.savefig(ROOT/'free-run-30fps-previews.png',dpi=160)
plt.close(fig)
print('Saved summaries and plots:', len(summary['cases']), 'cases, restored=', summary['restored'])
