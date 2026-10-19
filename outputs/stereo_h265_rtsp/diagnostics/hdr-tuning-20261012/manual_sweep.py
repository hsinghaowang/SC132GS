"""Fixed HDR profiles, decoded Main10 evidence; leaves AE disabled."""
import hashlib
import json
import pathlib
import subprocess
import time

import gi
import numpy as np
from PIL import Image, ImageDraw

gi.require_version('Gst', '1.0')
gi.require_version('GstApp', '1.0')
gi.require_version('GstVideo', '1.0')
from gi.repository import Gst, GstApp, GstVideo

OUT = pathlib.Path('/home/ubuntu/hdr-tuning-20261012')
Gst.init(None)

def run(*args):
    return subprocess.check_output(args, text=True, timeout=20).strip()

media = run('sc132gs-discover', 'media')
nodes = [run('media-ctl', '-d', media, '-e', 'sc132gs ' + name)
         for name in ('18-0032', '16-0030')]

def apply(gain, second):
    run('sc132gs-camera', 'apply', '--ae', 'off', '--hdr-total-rows', '1492',
        '--gain-index', str(gain))
    for node in nodes:
        run('v4l2-ctl', '-d', node,
            '--set-ctrl=hdr_total_nominal_rows=1492,hdr_total_second_ratio=256,'
            f'hdr_second_exposure_ticks={second}')
    time.sleep(1)

def capture():
    pipe = Gst.parse_launch('rtspsrc location=rtsp://192.168.137.226:8554/stereo '
        'protocols=tcp latency=100 ! rtph265depay ! h265parse ! avdec_h265 ! '
        'appsink name=frames sync=false max-buffers=2 drop=true')
    sink = pipe.get_by_name('frames')
    pipe.set_state(Gst.State.PLAYING)
    try:
        deadline = time.monotonic() + 15
        count = 0
        while time.monotonic() < deadline:
            error = pipe.get_bus().pop_filtered(Gst.MessageType.ERROR)
            if error:
                raise RuntimeError(error.parse_error())
            sample = sink.try_pull_sample(500 * Gst.MSECOND)
            if sample is None:
                continue
            count += 1
            if count < 45:
                continue
            info = GstVideo.VideoInfo.new_from_caps(sample.get_caps())
            assert sample.get_caps().get_structure(0).get_value('format') == 'I420_10LE'
            buffer = sample.get_buffer()
            data = buffer.extract_dup(0, buffer.get_size())
            luma = np.ndarray((info.height, info.width), dtype='<u2', buffer=data,
                              offset=info.offset[0], strides=(info.stride[0], 2)).copy()
            return luma, sample.get_caps().to_string()
        raise TimeoutError('No settled decoded frame')
    finally:
        pipe.set_state(Gst.State.NULL)

records = []
tiles = []
try:
    for gain, second in ((21, 93), (21, 1), (33, 1), (48, 1), (64, 1)):
        apply(gain, second)
        luma, caps = capture()
        name = f'total1492-gain{gain}-second{second}'
        payload = luma.tobytes()
        (OUT / (name + '.u16le')).write_bytes(payload)
        image = Image.fromarray(np.rint(luma * (255 / 1023)).clip(0,255).astype('uint8'))
        image.save(OUT / (name + '.png'))
        tile = Image.new('RGB', (1088, 670), 'white')
        tile.paste(image.resize((1088, 640)), (0, 30))
        ImageDraw.Draw(tile).text((8, 8), name, fill='black')
        tiles.append(tile)
        eyes = []
        for eye in np.hsplit(luma, 2):
            roi = eye[128:1152, 108:980]
            eyes.append({'p10': float(np.percentile(roi, 10)),
                         'p40': float(np.percentile(roi, 40)),
                         'p99': float(np.percentile(roi, 99)),
                         'clipped_percent': float(np.mean(roi >= 1020) * 100)})
        record = dict(profile=name, caps=caps, sha256=hashlib.sha256(payload).hexdigest(),
                      eyes=eyes, status=run('sc132gs-ctl', 'status'),
                      controls=[run('v4l2-ctl','-d',node,
                        '--get-ctrl=hdr_total_nominal_rows,hdr_total_second_ratio,'
                        'hdr_second_exposure_ticks,analogue_gain') for node in nodes])
        records.append(record)
        (OUT / 'manual-sweep.json').write_text(json.dumps(records, indent=2))
        print(json.dumps(record), flush=True)
finally:
    apply(21, 1)
    (OUT / 'manual-final-status.txt').write_text(run('sc132gs-ctl', 'status') + '\n')
if tiles:
    montage = Image.new('RGB', (1088, 670 * len(tiles)), 'white')
    for index, tile in enumerate(tiles):
        montage.paste(tile, (0, index * 670))
    montage.save(OUT / 'manual-comparison.png')
