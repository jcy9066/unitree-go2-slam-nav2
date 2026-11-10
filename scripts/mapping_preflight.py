#!/usr/bin/env python3
"""Read-only startup checks and post-shutdown database validation. No motion API."""
import argparse
import json
from pathlib import Path
import sqlite3
import time


def validate_database(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file() or not path.stat().st_size:
        raise ValueError('No populated database was saved')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3) as db:
        check = db.execute('PRAGMA quick_check').fetchone()[0]
        if check != 'ok':
            raise ValueError('SQLite quick_check: ' + check)
        count = db.execute('SELECT COUNT(*) FROM Node').fetchone()[0]
        if count < 1:
            raise ValueError('Database contains no RTAB-Map nodes')
    return {'database': str(path), 'quick_check': check, 'nodes': count,
            'bytes': path.stat().st_size, 'physical_map_accuracy': 'NOT TESTED'}


def sensor_check(mode, timeout):
    # Import ROS only for live checks; database validation also works offline.
    import rclpy
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import Image, CameraInfo, PointCloud2
    from rclpy.qos import qos_profile_sensor_data

    topics = {
        '/camera/color/image_raw': Image,
        '/camera/aligned_depth_to_color/image_raw': Image,
        '/camera/color/camera_info': CameraInfo,
    }
    if mode == 'ready':
        topics.update({'/utlidar/cloud_base': PointCloud2,
                       '/utlidar/robot_odom': Odometry})
    if mode == 'idle':
        topics = {}
    received = {}; counts = {}
    rclpy.init()
    node = rclpy.create_node('go2_mapping_preflight')
    try:
        for topic, typ in topics.items():
            def callback(_message, topic=topic):
                received[topic] = time.monotonic()
                counts[topic] = counts.get(topic, 0) + 1
            node.create_subscription(typ, topic, callback, qos_profile_sensor_data, raw=True)
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            rclpy.spin_once(node, timeout_sec=0.1)
            # A second mapper/controller would own conflicting map/odom TFs.
            blockers = sorted({ns.rstrip('/') + '/' + name
                               for name, ns in node.get_node_names_and_namespaces()
                               if name in {'rtabmap', 'rtabmap_vo', 'sensor_time_sync',
                                           'controller_server', 'odom_tf_bridge',
                                           'bridge_node', 'rgbd_odometry', 'odom_to_tf',
                                           'odom_time_sync'}})
            if blockers:
                print(json.dumps({'status': 'BLOCKED', 'active_nodes': blockers}))
                return 2
            if mode == 'idle':
                if time.monotonic() - start >= 2:
                    print(json.dumps({'status': 'PASS', 'active_slam_nodes': []}))
                    return 0
            elif (time.monotonic() - start >= 2 and
                  all(counts.get(t, 0) >= 2 and time.monotonic() - received[t] < 2
                      for t in topics)):
                print(json.dumps({'status': 'PASS', 'received': counts,
                                  'note': 'Reception only; TF calibration and synchronization not validated'}))
                return 0
        publishers = {t: [p.node_name for p in node.get_publishers_info_by_topic(t)]
                      for t in topics}
        print(json.dumps({'status': 'BLOCKED', 'received': counts,
                          'publishers': publishers,
                          'missing_or_stale': [t for t in topics
                                               if counts.get(t, 0) < 2 or
                                               time.monotonic() - received.get(t, 0) >= 2]}))
        if mode == 'camera' and any(publishers.values()):
            return 3  # Existing/stale camera must not be started a second time.
        return 1
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['idle', 'camera', 'ready', 'validate-db'])
    parser.add_argument('database', nargs='?')
    parser.add_argument('--timeout', type=float, default=30.)
    args = parser.parse_args()
    try:
        if args.mode == 'validate-db':
            if not args.database:
                parser.error('validate-db requires a database path')
            print(json.dumps(validate_database(args.database)))
            return 0
        if not 2 <= args.timeout <= 180:
            parser.error('timeout must be between 2 and 180 seconds')
        return sensor_check(args.mode, args.timeout)
    except (ValueError, sqlite3.Error, OSError) as exc:
        print(json.dumps({'status': 'FAIL', 'error': str(exc)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
