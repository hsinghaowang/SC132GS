#!/usr/bin/env python3
"""Decode real Main10/30-FPS RTSP frames and preserve unmodified observations."""
import argparse
import json
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dependencies', type=Path)
    parser.add_argument('--frames', type=int, default=181)
    args = parser.parse_args()
    if args.frames < 61:
        parser.error('--frames must be at least 61')
    if args.dependencies:
        sys.path.insert(0, str(args.dependencies.resolve()))
    import av
    args.output.mkdir(parents=True, exist_ok=False)
    observations = []
    snapshot = None
    codec = profile = None
    failure = None
    connection_start = time.monotonic()
    container = None
    try:
        container = av.open(args.url, options={'rtsp_transport': 'tcp'}, timeout=(5, 15))
        stream = container.streams.video[0]
        for frame in container.decode(stream):
            now = time.monotonic()
            observations.append({
                'index': len(observations), 'arrival_s': now-connection_start,
                'pts': frame.pts, 'time_base': str(frame.time_base),
                'media_s': float(frame.pts*frame.time_base) if frame.pts is not None else None,
                'width': frame.width, 'height': frame.height,
                'pixel_format': frame.format.name, 'key_frame': frame.key_frame})
            if len(observations) == 31:
                snapshot = frame.to_image()
            if len(observations) >= args.frames:
                break
            if now-connection_start > 30:
                raise TimeoutError('bounded decode exceeded 30 seconds')
        codec, profile = stream.codec_context.name, stream.codec_context.profile
    except Exception as error:
        failure = {'type': type(error).__name__, 'message': str(error)}
    finally:
        if container:
            container.close()
    (args.output/'frames.json').write_text(json.dumps(observations, indent=2)+'\n')
    if snapshot is not None:
        snapshot.save(args.output/'decoded.png')
    steady = observations[30:]
    points = [row['media_s'] for row in steady]
    monotonic = bool(points) and all(point is not None for point in points) and all(
        left < right for left, right in zip(points, points[1:]))
    media_fps = ((len(points)-1)/(points[-1]-points[0])
                 if monotonic and len(points) > 1 else None)
    wall_fps = ((len(steady)-1)/(steady[-1]['arrival_s']-steady[0]['arrival_s'])
                if len(steady) > 1 else None)
    correct_format = bool(observations) and all(
        row['width'] == 2176 and row['height'] == 1280 and
        row['pixel_format'] == 'yuv420p10le' for row in observations)
    correct_codec = codec == 'hevc' and str(profile).replace(' ', '').lower() == 'main10'
    result = {
        'passed': failure is None and len(observations) == args.frames and correct_codec and correct_format
                  and monotonic and 29.7 <= media_fps <= 30.3 and wall_fps >= 27,
        'failure': failure, 'codec': codec, 'profile': profile,
        'decoded_frames': len(observations), 'correct_main10_pixel_format': correct_format,
        'correct_codec_profile': correct_codec,
        'steady_pts_monotonic': monotonic, 'steady_media_fps': media_fps,
        'steady_wall_fps': wall_fps,
        'missing_pts_indices': [row['index'] for row in observations if row['pts'] is None],
        'scope': 'bounded real RTSP/TCP decode; first 30 client-startup frames excluded '
                 'only from rate calculation; no timestamps rewritten; no optical timing proof'}
    (args.output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
