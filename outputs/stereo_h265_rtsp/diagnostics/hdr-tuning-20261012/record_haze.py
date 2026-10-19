"""Record original RTSP access units and decoded snapshots during movement."""
import json
from pathlib import Path
import time
import gi
import numpy as np
from PIL import Image
gi.require_version('Gst','1.0')
gi.require_version('GstApp','1.0')
gi.require_version('GstVideo','1.0')
from gi.repository import Gst,GstApp,GstVideo
Gst.init(None)
out=Path('/home/ubuntu/hdr-tuning-20261012/haze-moving-20261012')
out.mkdir(exist_ok=False)
pipe=Gst.parse_launch('rtspsrc location=rtsp://192.168.137.226:8554/stereo protocols=tcp latency=100 '
    '! rtph265depay ! h265parse ! tee name=encoded '
    'encoded. ! queue ! matroskamux ! filesink location='+str(out/'moving.mkv')+' '
    'encoded. ! queue ! avdec_h265 ! appsink name=frames sync=false max-buffers=3 drop=true')
sink=pipe.get_by_name('frames')
records=[]
started=time.monotonic()
pipe.set_state(Gst.State.PLAYING)
try:
    deadline=time.monotonic()+15
    count=0
    while time.monotonic()<deadline:
        error=pipe.get_bus().pop_filtered(Gst.MessageType.ERROR)
        if error: raise RuntimeError(error.parse_error())
        sample=sink.try_pull_sample(300*Gst.MSECOND)
        if sample is None: continue
        info=GstVideo.VideoInfo.new_from_caps(sample.get_caps())
        if sample.get_caps().get_structure(0).get_value('format')!='I420_10LE':
            raise RuntimeError('Expected Main10 decoded samples')
        buf=sample.get_buffer()
        data=buf.extract_dup(0,buf.get_size())
        frame=np.ndarray((info.height,info.width),dtype='<u2',buffer=data,
            offset=info.offset[0],strides=(info.stride[0],2)).copy()
        if count%15==0:
            name=f'frame-{count:04d}'
            np.save(out/(name+'.npy'),frame)
            Image.fromarray(np.rint(frame*255.0/1023).clip(0,255).astype('uint8')).save(out/(name+'.png'))
            records.append(dict(frame=count,pts_ns=int(buf.pts),name=name,
                elapsed_seconds=time.monotonic()-started))
        count+=1
    pipe.send_event(Gst.Event.new_eos())
    pipe.get_bus().timed_pop_filtered(5*Gst.SECOND,Gst.MessageType.EOS|Gst.MessageType.ERROR)
    (out/'record.json').write_text(json.dumps(dict(decoded_count=count,frames=records),indent=2))
    print('Recorded movement:',count,'decoded frames')
finally:
    pipe.set_state(Gst.State.NULL)
