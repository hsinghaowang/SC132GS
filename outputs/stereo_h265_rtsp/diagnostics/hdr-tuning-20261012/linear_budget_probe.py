"""Measure Linear 30-FPS exposure/readout boundary; restore runtime controls."""
import fcntl
import json
from pathlib import Path
import sys
import time
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstApp', '1.0')
from gi.repository import Gst, GstApp
sys.path.insert(0, '/home/ubuntu/stereo-h265-rtsp')
import camera_platform as platform

out = Path('/home/ubuntu/hdr-tuning-20261012/linear-budget-probe')
out.mkdir(exist_ok=False)
Gst.init(None)
pipe = Gst.parse_launch('rtspsrc location=rtsp://192.168.137.226:8554/stereo protocols=tcp latency=100 ! rtph265depay ! h265parse ! avdec_h265 ! appsink name=frames sync=false max-buffers=2 drop=true')
sink = pipe.get_by_name('frames')
records = []
with open('/run/sc132gs-camera.lock', 'a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    before = platform.inspect()
    previous = platform.configuration_from_state(before)
    if previous['mode'] != 'linear' or previous['fps'] != 30 or previous['ae']:
        raise RuntimeError('Requires existing manual Linear 30-FPS stream')
    durable = platform.DURABLE.read_bytes()
    registers = {}
    for client in platform.CLIENTS:
        bus, address = client.split('-')
        registers[client] = {name: platform.run(['i2ctransfer','-f','-y',bus,'w2@0x'+address,'0x32',low,'r'+str(count)])
            for name,low,count in [('readout_rows','0x60',2),('reset_and_blank','0x26',4),('hts_vts','0x0c',4)]}
    pipe.set_state(Gst.State.PLAYING)
    try:
        for rows in (1320,1377,1440,1480,1600,1377):
            config = dict(previous, rows=rows, gain=0)
            platform.apply_exposure(config)
            time.sleep(2)
            pts = []
            deadline = time.monotonic()+8
            while time.monotonic()<deadline and len(pts)<60:
                error=pipe.get_bus().pop_filtered(Gst.MessageType.ERROR)
                if error: raise RuntimeError(error.parse_error())
                sample=sink.try_pull_sample(200*Gst.MSECOND)
                if sample is not None: pts.append(sample.get_buffer().pts)
            if len(pts)<30: raise RuntimeError('Missing decoded samples')
            result=dict(rows=rows, status=platform.request('status'), decoded_frames=len(pts),
                        pts_fps=(len(pts)-1)*1e9/(pts[-1]-pts[0]))
            records.append(result)
            (out/'results.json').write_text(json.dumps(dict(registers=registers,records=records),indent=2))
            print(json.dumps(result), flush=True)
    finally:
        pipe.set_state(Gst.State.NULL)
        platform.apply_exposure(previous)
        if platform.DURABLE.read_bytes()!=durable: raise RuntimeError('Durable policy changed')
