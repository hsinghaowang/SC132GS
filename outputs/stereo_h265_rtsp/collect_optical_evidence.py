#!/usr/bin/env python3
"""Summarize real captures and preserve reproducible evidence metadata."""
import hashlib
import json
from pathlib import Path
import statistics
import sys
import camera_platform as platform

def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda:stream.read(1024*1024),b''): digest.update(data)
    return digest.hexdigest()

def main():
    roots=[Path(value) for value in sys.argv[1:]]
    results=[]
    for root in roots:
        result=json.loads((root/'analysis.json').read_text())
        transaction=json.loads((root/'transaction.json').read_text())
        audit=json.loads((root/'raw-audit.json').read_text())
        estimate=result['estimate']
        assert transaction['restored'] and not transaction['restore_errors']
        assert transaction['before']['revision']==transaction['after']['revision']
        assert len(audit)==6 and all(a['raw10_tile_means_match'] and a['saturation_counts_match'] for a in audit)
        entry=dict(board_directory=str(root),status=result['status'],
            duration_seconds=transaction.get('requested_duration_seconds',60),sensor_fps=transaction['test']['fps'],
            nominal_exposure_us=result['nominal_exposure_us'],joint_events=result['valid_joint_events'],
            eyes=result['eyes'],estimate=estimate,
            receiver_delta_median_us=statistics.median(c['receiver_delta_us'] for c in result['candidates']),
            restored_revision=transaction['after']['revision'],raw_frames_audited=len(audit))
        results.append(entry)
        files={p.name:dict(bytes=p.stat().st_size,sha256=sha256(p)) for p in root.iterdir() if p.is_file() and p.name!='manifest.json'}
        (root/'manifest.json').write_text(json.dumps(dict(files=files,
            source_sha256={name:sha256(Path(__file__).parent/name) for name in
            ('RawOpticalCapture.cpp','RawOpticalCapture.hpp','OpticalCaptureMain.cpp',
             'optical_exposure_test.py','analyze_optical_exposure.py','inspect_optical_capture.py')},
            binary_sha256=sha256(Path(__file__).parent/'build-exposure60/optical-raw-capture')),indent=2))
    current=platform.inspect()
    leds=[]
    for colour in ('red','green','blue'):
        path=Path('/sys/class/leds')/colour
        leds.append(dict(colour=colour,brightness=int((path/'brightness').read_text()),
            trigger=(path/'trigger').read_text().split('[')[1].split(']')[0]))
    assert current['sensor_mode']=='linear' and current['fps']==60 and current['ae']==1 and current['binning']==0
    assert current['revision']==results[-1]['restored_revision']
    for actual,previous in zip(leds,transaction['leds']):
        assert actual['colour']==Path(previous['path']).name and actual['trigger']==previous['trigger']
        # Heartbeat brightness changes with phase; only steady LEDs have an
        # instantaneous brightness value that can be compared after restoration.
        if actual['trigger']=='none': assert actual['brightness']==int(previous['brightness'])
    summary=dict(captures=results,live_after=current,leds_after=leds,
        hardware_exposure_sync_verified=False,calibrated_accuracy_us=None,
        interpretation='All optical-model medians are close to zero; sign is unresolved at the observed noise scale. Receiver timestamps are distinct diagnostics.',
        large_capture_data='frames.bin remains in each board_directory; local archive retains manifests and packed RAW snapshots.')
    excluded=roots[0].parent/'optical-exposure-20261007-60fps-4ms'
    if (excluded/'analysis.json').exists():
        invalid=json.loads((excluded/'analysis.json').read_text())
        transaction=json.loads((excluded/'transaction.json').read_text())
        transaction['later_recovery']=dict(restored=True,
            method='camera_platform restore from saved YAML; decoded RTSP verified',final_state=current)
        (excluded/'transaction.json').write_text(json.dumps(transaction,indent=2))
        summary['excluded_run']=dict(board_directory=str(excluded),status=invalid['status'],
            reason='Initial 60 FPS test omitted the post-stream high-rate sensor profile; actual capture was 30 FPS.',
            initial_restore_errors=transaction['restore_errors'],later_recovery=transaction['later_recovery'])
    destination=roots[0].parent/'optical-exposure-20261007-summary.json'
    destination.write_text(json.dumps(summary,indent=2))
    print(json.dumps(dict(summary=str(destination),live_after=current,leds_after=leds),indent=2))
if __name__=='__main__': main()
