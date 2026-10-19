#!/usr/bin/env python3
"""Bounded real DDS subscriber; checks content and clock-domain declarations."""
import argparse
import json
import math
from pathlib import Path
import time

import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from gs130wi_ros.msg import ImuBatch, StereoMetadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=16)
    parser.add_argument('--minimum-active-seconds', type=float, default=0)
    parser.add_argument('--maximum-gap-seconds', type=float, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rclpy.init()
    node = rclpy.create_node('gs130wi_live_verifier')
    images = [set(), set()]
    metadata = set()
    counts = [0, 0]
    sample_count = markers = index_gaps = 0
    last_index = None
    previous_stamps = [None, None]
    errors = []
    sources = set()
    acquisition_ids = set()
    last_image = [None, None]
    delivery = {}

    def arrived(topic):
        now = time.monotonic()
        state = delivery.setdefault(topic, {'first': now, 'last': now, 'maximum_gap_s': 0})
        state['maximum_gap_s'] = max(state['maximum_gap_s'], now - state['last'])
        state['last'] = now

    def image(message, eye):
        arrived('left' if eye == 0 else 'right')
        stamp = message.header.stamp.sec * 10**9 + message.header.stamp.nanosec
        if abs(time.time_ns() - stamp) > 5 * 10**9:
            errors.append('camera stamp is not current system ROS time')
        if previous_stamps[eye] is not None and stamp <= previous_stamps[eye]:
            errors.append('camera timestamp regression')
        previous_stamps[eye] = stamp
        if len(message.data) != message.step * message.height or message.encoding not in ('mono8', 'mono16'):
            errors.append('invalid image geometry/encoding')
        if not message.header.frame_id:
            errors.append('missing camera frame ID')
        counts[eye] += 1
        images[eye].add(stamp)
        if last_image[eye] is None:
            last_image[eye] = {
                'width': message.width, 'height': message.height,
                'encoding': message.encoding, 'frame_id': message.header.frame_id,
                'pixel_min': min(message.data), 'pixel_max': max(message.data)}
            # mono8 first frame preview; this is captured sensor output, not a rendered mock.
            if message.encoding == 'mono8':
                args.output.with_name(f'left.pgm' if eye == 0 else 'right.pgm').write_bytes(
                    f'P5\n{message.width} {message.height}\n255\n'.encode() + bytes(message.data))

    def inertial(message):
        nonlocal sample_count, markers, last_index, index_gaps
        arrived('imu')
        acquisition_ids.add(message.acquisition_id)
        if message.host_sample_time_validated or message.frame_association_validated:
            errors.append('unverified IMU association promoted to valid')
        if message.host_read_end_ns < message.host_read_begin_ns:
            errors.append('transport timestamps reversed')
        for sample in message.samples:
            if last_index is not None:
                if sample.sample_index <= last_index:
                    errors.append('IMU index regression')
                elif sample.sample_index != last_index + 1:
                    index_gaps += sample.sample_index - last_index - 1
            last_index = sample.sample_index
            sample_count += 1
            if not sample.valid:
                errors.append('invalid sensor sample')
            if sample.sensor_time_valid == sample.fsync_valid:
                errors.append('ambiguous FIFO timestamp kind')
            if sample.fsync_valid:
                markers += 1
                if sample.fsync_offset_ns != sample.timestamp_raw * 32000 // 30:
                    errors.append('FSYNC conversion mismatch')
            values = [sample.linear_acceleration.x, sample.linear_acceleration.y,
                      sample.linear_acceleration.z, sample.angular_velocity.x,
                      sample.angular_velocity.y, sample.angular_velocity.z]
            if not all(math.isfinite(value) for value in values):
                errors.append('non-finite SI measurement')

    def sync(message):
        arrived('metadata')
        acquisition_ids.add(message.acquisition_id)
        if message.imu_association_validated:
            errors.append('unverified stereo/IMU association promoted to valid')
        sources.add((message.timestamp_source, message.timestamp_offset_ns))
        metadata.add(message.header.stamp.sec * 10**9 + message.header.stamp.nanosec)

    subscriptions = [
        node.create_subscription(Image, 'stereo/left/image_mono', lambda m: image(m, 0), qos_profile_sensor_data),
        node.create_subscription(Image, 'stereo/right/image_mono', lambda m: image(m, 1), qos_profile_sensor_data),
        node.create_subscription(ImuBatch, 'gs130wi/imu_samples', inertial, qos_profile_sensor_data),
        node.create_subscription(StereoMetadata, 'stereo/metadata', sync, qos_profile_sensor_data)]
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
    matched = images[0] & images[1] & metadata
    if min(counts) < 60 or len(matched) < 60 or sample_count < 400 or markers < 60:
        errors.append('insufficient real subscribed data')
    if len(acquisition_ids) != 1:
        errors.append('missing or inconsistent acquisition identity')
    spans = {topic: {'active_span_s': value['last'] - value['first'],
                     'maximum_gap_s': value['maximum_gap_s']} for topic, value in delivery.items()}
    for topic in ('left', 'right', 'imu', 'metadata'):
        state = spans.get(topic)
        if state is None or state['active_span_s'] < args.minimum_active_seconds:
            errors.append(f'insufficient subscribed duration: {topic}')
        elif state['maximum_gap_s'] > args.maximum_gap_seconds:
            errors.append(f'subscribed stream stalled: {topic}')
    report = {
        'passed': not errors, 'errors': sorted(set(errors)), 'image_counts': counts,
        'matching_stereo_and_metadata_stamps': len(matched), 'imu_samples_received': sample_count,
        'fsync_packets_received': markers, 'imu_sample_index_gaps': index_gaps,
        'timestamp_sources_and_offsets': sorted(sources), 'first_images': last_image,
        'delivery': spans,
        'frame_association_validated': False, 'host_sample_time_validated': False,
        'scope': 'real ROS/DDS image + raw IMU delivery, not frame-interval association or VIO readiness'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    node.destroy_node()
    rclpy.shutdown()
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
