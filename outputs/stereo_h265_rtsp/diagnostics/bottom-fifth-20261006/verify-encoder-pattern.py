import pathlib,gi
gi.require_version('Gst','1.0')
from gi.repository import Gst
Gst.init(None)
root=pathlib.Path('/home/ubuntu/sc132gs-bottom-fifth-20261006')
for pattern in ['solid-color','gradient']:
    pipeline=Gst.parse_launch(
        f'videotestsrc num-buffers=60 pattern={pattern} foreground-color=0xff808080 ! '
        'video/x-raw,format=NV12,width=2176,height=1280,framerate=30/1,colorimetry=bt709 ! '
        'v4l2h265enc output-io-mode=mmap capture-io-mode=mmap extra-controls="controls,vui_timing_info=1" ! '
        f'h265parse ! filesink location={root}/encoder-{pattern}.h265')
    pipeline.set_state(Gst.State.PLAYING)
    message=pipeline.get_bus().timed_pop_filtered(20*Gst.SECOND,Gst.MessageType.EOS|Gst.MessageType.ERROR)
    pipeline.set_state(Gst.State.NULL)
    if message is None: raise RuntimeError('encoder timed out')
    if message.type==Gst.MessageType.ERROR: raise RuntimeError(message.parse_error())
    print(pattern,'encoded')
