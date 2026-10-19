"""Analyze saved replay timing. No device/config changes or new replay."""
import csv
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

STAGES=['tracking','propagation','msckf_update','slam_update','slam_init','retriangulation_marginalization']

def stats(values):
    values=np.asarray(values);values=values[np.isfinite(values)]
    return dict(zip(['mean','p50','p95','p99','max'],map(float,[np.mean(values),*np.percentile(values,[50,95,99]),np.max(values)]))) if len(values) else None

def analyze(directory, output):
    frames=np.genfromtxt(directory/'frames.csv',delimiter=',',names=True)
    internal=np.loadtxt(directory/'internal-timing.csv',delimiter=',',comments='#',ndmin=2)
    time=(frames['camera_timestamp']-frames['camera_timestamp'][0])
    service=frames['read_ms']+frames['imu_ms']+frames['estimator_ms']
    lag=frames['completion_lag_ms']
    start_lag=lag-service
    active=frames['initialized']==1
    # Internal timestamps use online-calibrated IMU time, not camera time.
    # Match within < half a camera period, preserving one-to-one order.
    camera=frames['camera_timestamp']
    candidate=np.clip(np.searchsorted(camera,internal[:,0]),1,len(camera)-1)
    previous=candidate-1
    indices=np.where(np.abs(camera[previous]-internal[:,0])<np.abs(camera[candidate]-internal[:,0]),previous,candidate)
    error=np.abs(camera[indices]-internal[:,0])
    assert np.all(error<.020) and len(np.unique(indices))==len(indices) and np.all(np.diff(indices)>0)
    assert np.all(frames['state_advanced'][indices]==1)
    parts=np.full((len(frames),6),np.nan)
    parts[indices]=internal[:,1:7]*1000
    residual=frames['estimator_ms'][indices]-internal[:,-1]*1000
    assert np.min(residual)>-.2, 'internal timing exceeds enclosing steady-clock span'
    peak=int(np.argmax(lag))
    # Trace backward through frames whose start was blocked by prior completion.
    first=peak
    while first>0 and lag[first-1]>(camera[first]-camera[first-1])*1000+1:
        first-=1
    last=peak
    while last+1<len(frames) and start_lag[last+1]>10:
        last+=1
    end=time+lag/1000
    start=end-service/1000
    previous_debt=np.maximum(0,lag[:-1]-np.diff(camera)*1000)
    extra=start_lag[1:]-previous_debt
    event_range=np.arange(first,peak+1)
    valid=event_range[np.isfinite(parts[event_range,0])]
    event_parts={name:float(np.sum(parts[valid,k])) for k,name in enumerate(STAGES)}
    frame_report=[]
    for i in range(first,min(last+1,len(frames))):
        row={'frame':i,'dataset_time_s':float(time[i]),'read_ms':float(frames['read_ms'][i]),'imu_ms':float(frames['imu_ms'][i]),'estimator_ms':float(frames['estimator_ms'][i]),'service_ms':float(service[i]),'start_lag_ms':float(start_lag[i]),'completion_lag_ms':float(lag[i])}
        row.update({name+'_ms':float(parts[i,k]) if np.isfinite(parts[i,k]) else None for k,name in enumerate(STAGES)})
        frame_report.append(row)
    summary=json.loads((directory/'summary.json').read_text())
    resources=json.loads((directory/'resources.json').read_text())
    # Wrapper's epoch starts before process spawn; runner's starts after setup.
    # End polling adds an unknown 0..~1s. Keep a conservative offset bound.
    offset_upper=max(0,resources['elapsed_wrapper_s']-summary['elapsed_s'])
    platform=[]
    with (directory/'platform-samples.csv').open() as stream:
        for row in csv.DictReader(stream):
            elapsed=float(row['elapsed_s'])
            if start[first]-1 <= elapsed <= end[last]+offset_upper+1:
                platform.append({'elapsed_wrapper_s':elapsed,'thermal_type':row['thermal_type'],'temperature_raw':int(row['temperature_raw']),'frequencies_khz':json.loads(row['cpu_frequencies_khz'])})
    freq={}; thermal={}
    for row in platform:
        for core,value in row['frequencies_khz'].items(): freq.setdefault(core,[]).append(int(value))
        if row['thermal_type'].startswith('cpu') and row['thermal_type'].endswith('-thermal'):
            thermal.setdefault(row['thermal_type'],[]).append(row['temperature_raw'])
    result={'run':directory.name,'initialized_frames':int(np.sum(active)), 'service_initialized_ms':stats(service[active]),'lag_initialized_ms':stats(lag[active]), 'stage_ms':{name:stats(parts[:,k]) for k,name in enumerate(STAGES)},'stage_share_of_recorded_total_percent':{name:float(np.nansum(parts[:,k])/np.nansum(parts)*100) for k,name in enumerate(STAGES)},'read_initialized_ms':stats(frames['read_ms'][active]),'estimator_initialized_ms':stats(frames['estimator_ms'][active]),'outside_internal_timing_ms':stats(residual), 'timing_match_max_offset_ms':float(np.max(error)*1000),'internal_rows':len(indices),'pose_frames_without_internal_timing':int(np.sum(frames['state_advanced'])-len(indices)), 'over_50ms_service_frames':int(np.sum(active&(service>50))),'over_50ms_service_percent':float(np.mean(service[active]>50)*100),'over_100ms_lag_frames':int(np.sum(active&(lag>100))), 'unaccounted_start_delay_ms':stats(extra[active[1:]]), 'peak':{'frame':peak,'dataset_time_s':float(time[peak]),'completion_lag_ms':float(lag[peak]),'service_ms':float(service[peak]),'start_lag_ms':float(start_lag[peak]),'read_ms':float(frames['read_ms'][peak]),'estimator_ms':float(frames['estimator_ms'][peak]),'stages_ms':dict(zip(STAGES,map(float,parts[peak])))},'peak_episode':{'first_frame':first,'peak_frame':peak,'recovered_through_frame':last,'frames_before_and_at_peak':peak-first+1,'service_sum_before_peak_ms':float(np.sum(service[event_range])),'interframe_budget_before_peak_ms':float((time[peak]-time[first])*1000),'stage_sum_before_peak_ms':event_parts,'rows':frame_report},'platform_near_peak':{'runner_to_wrapper_offset_bound_s':[0,offset_upper],'sampling_interval_s':1,'association':'approximate window only; no execution-core trace or per-frame clock timestamp','frequencies_khz_range':{core:[min(values),max(values)] for core,values in freq.items()},'cpu_thermal_raw_range':{zone:[min(values),max(values)] for zone,values in thermal.items()}}}
    (output/(directory.name+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    if directory.name=='MH_01_easy-paced-3':
        fig,axes=plt.subplots(3,1,figsize=(12,9),constrained_layout=True)
        axes[0].plot(time,lag,lw=.9,label='Completion lag')
        axes[0].axvline(time[peak],color='tab:red',ls='--',label=f'Peak: frame {peak}')
        axes[0].set(title='MH_01_easy: replay lag and worst backlog episode',ylabel='Lag (ms)');axes[0].legend()
        window=np.arange(max(0,first-8),min(len(frames),last+8))
        axes[1].plot(time[window],lag[window],label='Completion lag',color='tab:red')
        axes[1].plot(time[window],service[window],label='This frame service',color='tab:blue')
        axes[1].plot(time[window],start_lag[window],label='Lag at service start',color='tab:orange')
        axes[1].axhline(50,color='gray',ls='--',label='20 Hz frame period')
        axes[1].set(ylabel='Time (ms)');axes[1].legend(ncol=2)
        plot_parts=np.nan_to_num(parts[window])
        axes[2].stackplot(time[window],frames['read_ms'][window],*[plot_parts[:,k] for k in range(6)],labels=['Image load/decode',*STAGES],alpha=.85)
        axes[2].axhline(50,color='black',ls='--');axes[2].set(xlabel='Dataset camera time from start (s)',ylabel='Stage wall time (ms)')
        axes[2].legend(ncol=3,fontsize=8)
        fig.savefig(output/'MH-peak-analysis.png',dpi=160)
        fig.savefig(output/'MH-peak-analysis.svg')
        plt.close(fig)
    return result

def main():
    base,output=map(Path,sys.argv[1:3]);output.mkdir(parents=True,exist_ok=True)
    names=['MH_01_easy-paced-3',*[f'V2_02_medium-paced-{n}' for n in range(1,4)]]
    results=[analyze(base/name,output) for name in names]
    (output/'analysis.json').write_text(json.dumps({'scope':'saved logs only; no hardware changes or new replay','runs':results},indent=2),encoding='utf-8')
    for r in results:
        print(json.dumps({key:r[key] for key in ['run','peak','over_50ms_service_percent','stage_share_of_recorded_total_percent','outside_internal_timing_ms']},indent=2))

if __name__=='__main__': main()
