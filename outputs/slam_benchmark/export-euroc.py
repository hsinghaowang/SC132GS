"""Export lossless mono8 images and header-clock IMU from a ROS1 EuRoC bag."""
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from rosbags.highlevel import AnyReader

bag, dest = map(Path, sys.argv[1:3])
dest.mkdir(parents=True, exist_ok=True)
handles, writers, counts = {}, {}, {}
for name in ('cam0', 'cam1', 'imu0'):
    (dest / name / 'data').mkdir(parents=True, exist_ok=True)
    handles[name] = (dest / name / 'data.csv').open('w', newline='')
    writers[name] = csv.writer(handles[name])
    writers[name].writerow(['#timestamp [ns]', 'filename' if name.startswith('cam') else 'wx,wy,wz,ax,ay,az'])
    counts[name] = 0
try:
    with AnyReader([bag]) as reader:
        topics = {'/cam0/image_raw': 'cam0', '/cam1/image_raw': 'cam1', '/imu0': 'imu0'}
        connections = [c for c in reader.connections if c.topic in topics]
        if {c.topic for c in connections} != set(topics):
            raise ValueError('missing required EuRoC topics')
        for connection, _, raw in reader.messages(connections=connections):
            msg = reader.deserialize(raw, connection.msgtype)
            stamp = msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec
            name = topics[connection.topic]
            if name == 'imu0':
                w, a = msg.angular_velocity, msg.linear_acceleration
                writers[name].writerow([stamp, w.x, w.y, w.z, a.x, a.y, a.z])
            else:
                if msg.encoding != 'mono8' or (msg.width, msg.height) != (752, 480):
                    raise ValueError(f'unexpected image {msg.encoding} {msg.width}x{msg.height}')
                image = np.frombuffer(msg.data, np.uint8).reshape(msg.height, msg.step)[:, :msg.width]
                filename = f'{stamp}.png'
                if not cv2.imwrite(str(dest/name/'data'/filename), image):
                    raise IOError('PNG export failed')
                writers[name].writerow([stamp, filename])
            counts[name] += 1
    (dest/'export-summary.json').write_text(json.dumps({'source_bag': str(bag), 'counts': counts, 'image_encoding':'lossless PNG mono8', 'timestamp':'message header stamp, not bag record time'}, indent=2))
    print(counts)
finally:
    for handle in handles.values():
        handle.close()
