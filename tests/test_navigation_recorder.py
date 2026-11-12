"""Trace fidelity and bounded recording, without a ROS context or motor publisher."""
import gzip
import json
from types import SimpleNamespace
from dwb_msgs.msg import LocalPlanEvaluation, TrajectoryScore, CriticScore
from geometry_msgs.msg import Pose2D
from go2_slam_nav.navigation_recorder import (
    evaluation_record, obstacle_sensor_record, TraceWriter, NavigationRecorder)
from sensor_msgs.msg import LaserScan, PointCloud2, PointField
from rclpy.serialization import serialize_message, deserialize_message
import base64
import math
import struct
from unitree_api.msg import Request
from unittest.mock import Mock


def test_evaluation_preserves_invalid_reason_and_selected_trajectory():
    msg = LocalPlanEvaluation(); msg.best_index = 1
    bad = TrajectoryScore(); bad.total = -1.; bad.traj.velocity.x = .08
    score = CriticScore(); score.name = 'Go2WalkingSpeed'; score.raw_score = -1.; score.scale = 1.
    bad.scores = [score]
    good = TrajectoryScore(); good.total = 3.; good.traj.velocity.x = .2; good.traj.velocity.theta = .4
    pose = Pose2D(); pose.x = .3; pose.theta = .6; good.traj.poses = [pose]
    msg.twists = [bad, good]
    out = evaluation_record(msg)
    assert out['selected_index'] == 1 and out['invalid_count'] == 1
    assert out['candidates'][0]['critics'] == [['Go2WalkingSpeed', -1., 1.]]
    assert out['candidates'][1]['v'] == [.2, 0., .4]
    assert out['selected_poses'] == [[.3, 0., .6]]


def test_all_invalid_or_empty_evaluation_does_not_invent_selected_command():
    msg = LocalPlanEvaluation()
    assert evaluation_record(msg)['selected_index'] is None
    t = TrajectoryScore(); t.total = -1.; msg.twists = [t]
    assert evaluation_record(msg)['selected_index'] is None
    msg.best_index = 999
    assert evaluation_record(msg)['selected_poses'] == []


def test_trace_roundtrip_preserves_events_and_never_overwrites_previous_run(tmp_path):
    writer = TraceWriter(tmp_path)
    writer.emit('/evaluation', {'total': float('nan'), 'x': .2})
    writer.emit('/go2_nav/cmd_vel', {'x': .2, 'y': 0., 'yaw': .4})
    summary = writer.close()
    with gzip.open(writer.directory/'events.jsonl.gz', 'rt') as f:
        rows = [json.loads(line) for line in f]
    assert rows[0]['data']['total'] is None
    assert rows[1]['data']['x'] == .2
    assert rows[0]['monotonic_ns'] <= rows[1]['monotonic_ns']
    assert summary['evaluations_present'] and summary['write_error'] is None
    other = TraceWriter(tmp_path); other.close()
    assert other.directory != writer.directory
    assert (writer.directory/'summary.json').exists()


def test_overload_is_counted_instead_of_blocking_or_losing_trace_integrity(tmp_path):
    writer = TraceWriter(tmp_path, max_bytes=8)
    assert not writer.emit('/evaluation', {'too_large': 'record'})
    summary = writer.close()
    assert summary['dropped']['/evaluation'] == 1
    assert not summary['evaluations_present']
    with gzip.open(writer.directory/'events.jsonl.gz', 'rt') as f:
        assert f.read() == ''


def test_request_callback_accepts_humble_message_only_delivery():
    sink = SimpleNamespace(simple=Mock())
    request = Request(); request.header.identity.api_id = 99999
    NavigationRecorder.request(sink, request)
    sink.simple.assert_called_once_with('/api/sport/request', request, publisher_gid=None)


def test_runtime_errors_are_explicit_in_summary(tmp_path):
    writer = TraceWriter(tmp_path)
    writer.emit('recorder_error', {'type': 'TypeError', 'message': 'synthetic callback failure'})
    assert writer.close()['runtime_error_count'] == 1


def test_obstacle_scan_preserves_invalid_ranges_for_clearing_analysis():
    scan = LaserScan(); scan.header.frame_id = 'camera_scan'
    scan.header.stamp.sec = 123; scan.header.stamp.nanosec = 456
    scan.angle_min = -.5; scan.angle_increment = .25
    scan.range_min = .3; scan.range_max = 3.
    scan.ranges = [float('inf'), float('nan'), .8, float('-inf')]
    record = obstacle_sensor_record(scan)
    restored = deserialize_message(base64.b64decode(record['data']), LaserScan)
    assert record['message_type'] == 'sensor_msgs/msg/LaserScan'
    assert serialize_message(restored) == serialize_message(scan)
    assert math.isnan(restored.ranges[1]) and math.isinf(restored.ranges[0])
    assert restored.ranges[-1] < 0
    assert record['header']['stamp']['nanosec'] == 456


def test_obstacle_cloud_preserves_endianness_fields_and_row_padding():
    cloud = PointCloud2(); cloud.header.frame_id = 'base_link'
    cloud.height = 1; cloud.width = 1; cloud.is_bigendian = True
    cloud.point_step = 16; cloud.row_step = 20
    cloud.fields = [PointField(name=k, offset=i*4, datatype=PointField.FLOAT32, count=1)
                    for i, k in enumerate(['x', 'y', 'z'])]
    cloud.data = struct.pack('>fff', 1., 2., 3.) + b'padding!'
    record = obstacle_sensor_record(cloud)
    restored = deserialize_message(base64.b64decode(record['data']), PointCloud2)
    assert record['message_type'] == 'sensor_msgs/msg/PointCloud2'
    assert serialize_message(restored) == serialize_message(cloud)
    assert bytes(restored.data)[12:] == b'padding!'


def test_disabled_raw_obstacle_capture_does_not_serialize_or_write():
    sink = SimpleNamespace(record_obstacle_sensors=False, writer=Mock())
    NavigationRecorder.obstacle_sensor(sink, '/go2_nav/depth_scan', LaserScan())
    sink.writer.emit.assert_not_called()
