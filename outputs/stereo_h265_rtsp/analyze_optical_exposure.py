#!/usr/bin/env python3
"""Conditional exposure-skew estimate from common optical step events."""
import argparse
import json
from pathlib import Path
import struct
import numpy as np

def read_frames(path):
    with path.open('rb') as stream:
        if stream.read(8)!=b'SCOP001\0': raise ValueError('invalid capture magic')
        width,height,step=struct.unpack('<III',stream.read(12))
    if width%step or height%step: raise ValueError('invalid tile geometry')
    count=width//step*(height//step)
    dtype=np.dtype([('eye','<u4'),('sequence','<u4'),('flags','<u4'),('count','<u4'),
        ('receiver_ns','<i8'),('dequeue_ns','<i8'),('tiles','<u2',(count,)),('saturated','u1',(count,))])
    size=path.stat().st_size-20
    if size%dtype.itemsize: raise ValueError('truncated RAW statistics')
    frames=np.memmap(path,dtype=dtype,mode='r',offset=20,shape=(size//dtype.itemsize,))
    if np.any(frames['count']!=count) or np.any(frames['eye']>1): raise ValueError('invalid frame record')
    return frames,width//step,height//step,step

def write_pgm(path,image):
    pixels=np.clip(image/4,0,255).astype(np.uint8)
    path.write_bytes(f'P5\n{pixels.shape[1]} {pixels.shape[0]}\n255\n'.encode()+pixels.tobytes())

def analyze(root):
    transaction=json.loads((root/'transaction.json').read_text())
    exposure=transaction['nominal_exposure_us']
    events=[json.loads(line) for line in (root/'led-events.jsonl').read_text().splitlines()]
    frames,width,height,step=read_frames(root/'frames.bin')
    eye_results=[]
    for eye in (0,1):
        eye_frames=frames[frames['eye']==eye]
        times=eye_frames['dequeue_ns']
        calibration={}
        for index,event in enumerate(events):
            stage=event['stage']
            if not stage.startswith('calibration'): continue
            next_time=events[index+1]['before_ns']
            mask=(times>event['after_ns']+300_000_000)&(times<next_time-150_000_000)
            calibration[stage]=eye_frames[mask]
        if any(len(calibration.get(stage,()))<10 for stage in ('calibration_dark','calibration_light','calibration_dark2')):
            raise ValueError('insufficient calibration frames')
        dark=np.median(calibration['calibration_dark']['tiles'],axis=0)
        light=np.median(calibration['calibration_light']['tiles'],axis=0)
        dark2=np.median(calibration['calibration_dark2']['tiles'],axis=0)
        difference=light-dark
        source_peak=int(np.argmax(difference))
        source_y,source_x=divmod(source_peak,width)
        grid=np.arange(width*height).reshape(height,width)
        neighbourhood=grid[max(0,source_y-8):min(height,source_y+9),
            max(0,source_x-8):min(width,source_x+9)].ravel()
        # A bright LED core may clip while its optical halo remains linear.
        # Select only tiles with no saturated pixel in any calibration frame.
        clipped=np.max(calibration['calibration_light']['saturated'],axis=0)>0
        usable=neighbourhood[(~clipped[neighbourhood])&(difference[neighbourhood]>=20)]
        peak=int(usable[np.argmax(difference[usable])]) if len(usable) else source_peak
        y,x=divmod(peak,width)
        # Select responsive tiles near the brightest optical change independently
        # for each eye. Normalize each eye against its own dark/light reference.
        local=grid[max(0,y-2):min(height,y+3),max(0,x-2):min(width,x+3)].ravel()
        roi=local[(~clipped[local])&(difference[local]>=max(12,difference[peak]*.35))]
        if not len(roi): roi=np.array([peak])
        dark_level=float(np.mean(dark[roi])); light_level=float(np.mean(light[roi]))
        amplitude=light_level-dark_level
        means=np.mean(eye_frames['tiles'][:,roi],axis=1)
        fractions=(means-dark_level)/max(amplitude,1)
        calibration_noise=max(float(np.std(np.mean(calibration[stage]['tiles'][:,roi],axis=1),ddof=1))
            for stage in ('calibration_dark','calibration_light','calibration_dark2'))
        saturation=float(np.max(np.mean(calibration['calibration_light']['saturated'][:,roi],axis=1))/64)
        drift=float(abs(np.mean(dark2[roi])-dark_level)/max(amplitude,1))
        failures=[]
        receive_fps=float((len(eye_frames)-1)*1e9/
            (int(eye_frames[-1]['receiver_ns'])-int(eye_frames[0]['receiver_ns'])))
        requested_fps=transaction.get('test',{}).get('fps',30)
        if abs(receive_fps-requested_fps)>requested_fps*.05:
            failures.append('capture_cadence_does_not_match_requested_FPS')
        if amplitude<20: failures.append('LED_not_visible_or_too_weak')
        if saturation>.001: failures.append('LED_pixels_saturated')
        if calibration_noise>max(3,amplitude*.04): failures.append('unstable_light_or_background')
        if drift>.04: failures.append('background_changed')
        sequence_gaps=int(np.sum(np.maximum(0,np.diff(eye_frames['sequence'].astype(np.int64))-1)))
        write_pgm(root/f'eye{eye}-dark.pgm',dark.reshape(height,width))
        write_pgm(root/f'eye{eye}-light.pgm',light.reshape(height,width))
        trace=[dict(sequence=int(frame['sequence']),receiver_ns=int(frame['receiver_ns']),
            dequeue_ns=int(frame['dequeue_ns']),fraction=float(fraction))
            for frame,fraction in zip(eye_frames,fractions)]
        (root/f'eye{eye}-trace.json').write_text(json.dumps(trace))
        eye_results.append(dict(eye=eye,frames=len(eye_frames),sequence_gaps=sequence_gaps,
            measured_receive_fps=receive_fps,
            source_peak_tile=source_peak,excluded_clipped_tiles=int(np.sum(clipped[neighbourhood])),
            roi_tiles=roi.tolist(),roi_pixel_bounds=[max(0,x-2)*step,max(0,y-2)*step,
                min(width,x+3)*step,min(height,y+3)*step],dark_raw10=dark_level,light_raw10=light_level,
            amplitude_raw10=amplitude,noise_raw10=calibration_noise,
            saturation_fraction=saturation,dark_drift_fraction=drift,failures=failures,
            trace=trace))
    candidates=[]
    rejected=[]
    for index,event in enumerate(events):
        if event['stage']!='transition' or index+1>=len(events): continue
        rising=event['value']>0
        selected=[]
        for eye in eye_results:
            # Software write times only associate one isolated light event.
            # They are not used in the optical skew calculation.
            trace=[sample for sample in eye['trace']
                if event['before_ns']-30_000_000<sample['dequeue_ns']<events[index+1]['before_ns']]
            partial=[sample for sample in trace if .10<sample['fraction']<.90]
            if len(partial)!=1: selected=[]; break
            sample=partial[0]
            all_trace=eye['trace']; position=next(i for i,s in enumerate(all_trace) if s is sample)
            if position==0 or position+1>=len(all_trace): selected=[]; break
            before,after=all_trace[position-1],all_trace[position+1]
            if before['sequence']+1!=sample['sequence'] or after['sequence']!=sample['sequence']+1:
                selected=[]; break
            if rising and not (before['fraction']<.10 and after['fraction']>.90): selected=[]; break
            if not rising and not (before['fraction']>.90 and after['fraction']<.10): selected=[]; break
            selected.append(sample)
        if len(selected)!=2: rejected.append(index); continue
        a,b=selected
        estimate=exposure*(b['fraction']-a['fraction'])*(1 if rising else -1)
        candidates.append(dict(event=index,rising=rising,eye0=a,eye1=b,
            estimated_start_skew_us=estimate,
            receiver_delta_us=(b['receiver_ns']-a['receiver_ns'])/1000))
    values=np.array([candidate['estimated_start_skew_us'] for candidate in candidates])
    checks=[reason for eye in eye_results for reason in eye['failures']]
    if len(values)<8: checks.append('insufficient_joint_partial_events')
    estimate=None
    if len(values):
        median=float(np.median(values)); mad=float(np.median(abs(values-median)))
        rising_values=[c['estimated_start_skew_us'] for c in candidates if c['rising']]
        falling_values=[c['estimated_start_skew_us'] for c in candidates if not c['rising']]
        noise_bound=exposure*sum(eye['noise_raw10']/max(eye['amplitude_raw10'],1) for eye in eye_results)
        if len(rising_values)<3 or len(falling_values)<3: checks.append('insufficient_both_edge_polarities')
        if len(rising_values)>=3 and len(falling_values)>=3:
            edge_mad=max(float(np.median(abs(np.array(v)-np.median(v))))
                for v in (rising_values,falling_values))
            if abs(np.median(rising_values)-np.median(falling_values))>max(100,4*noise_bound,4*edge_mad):
                checks.append('rising_falling_inconsistent')
        estimate=dict(median_start_skew_us=median,mad_us=mad,p10_us=float(np.percentile(values,10)),
            p90_us=float(np.percentile(values,90)),normalized_noise_scale_us=noise_bound,
            rising_count=len(rising_values),falling_count=len(falling_values),
            rising_median_us=float(np.median(rising_values)) if rising_values else None,
            falling_median_us=float(np.median(falling_values)) if falling_values else None,
            sign='positive means second eye exposure starts later',
            assumptions='equal fixed exposure, linear unsaturated RAW, common fast optical step; LED edge speed is not independently measured')
    result=dict(status='conditional_estimate' if not checks else 'inconclusive',
        nominal_exposure_us=exposure,valid_joint_events=len(candidates),rejected_events=len(rejected),
        eyes=[{key:value for key,value in eye.items() if key!='trace'} for eye in eye_results],
        failed_checks=checks,candidates=candidates,
        estimate=estimate if not checks else None,
        raw_candidate_statistics=estimate,
        calibrated_accuracy_us=None,exposure_sync_verified=False,
        note='This estimates relative optical exposure timing, not GPIO edge timing or absolute exposure timestamp.')
    (root/'analysis.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({key:value for key,value in result.items() if key not in ('candidates','eyes')},indent=2))
    return result

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    try: analyze(args.directory)
    except (ValueError,OSError,KeyError) as error:
        result=dict(status='inconclusive',failure=str(error),estimate=None,
            calibrated_accuracy_us=None,exposure_sync_verified=False)
        (args.directory/'analysis.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2))
if __name__=='__main__': main()
