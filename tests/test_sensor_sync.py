"""Synthetic messages, no ROS context, DDS, or robot publisher."""
from types import SimpleNamespace
from unittest.mock import Mock
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Image, PointCloud2
from go2_slam_nav import sensor_time_sync as sync


class Sensor:
    fresh = sync.SensorTimeSync.fresh
    cloud_callback = sync.SensorTimeSync.cloud_callback
    odom_callback = sync.SensorTimeSync.odom_callback
    rgb_callback = sync.SensorTimeSync.rgb_callback
    publish_odom = sync.SensorTimeSync.publish_odom

    def __init__(self):
        self.stamp = self.last_rgb_time = self.last_odom_stamp = None
        self.last_odom = self.last_odom_time = None
        self.cloud_pub, self.odom_pub, self.tf_pub = Mock(), Mock(), Mock()

    def get_parameter(self, name):
        return SimpleNamespace(value=.5)


def test_camera_gates_cloud_and_preserves_original(monkeypatch):
    sensor = Sensor()
    cloud = PointCloud2()
    cloud.header.frame_id = 'base_link'
    cloud.header.stamp.sec = 123
    sensor.cloud_callback(cloud)
    sensor.cloud_pub.publish.assert_not_called()
    monkeypatch.setattr(sync.time, 'monotonic', lambda: 10.)
    rgb = Image(); rgb.header.stamp.sec = 999
    sensor.rgb_callback(rgb)
    sensor.cloud_callback(cloud)
    output = sensor.cloud_pub.publish.call_args.args[0]
    assert output.header.stamp.sec == 999 and output.header.frame_id == 'base_link'
    assert cloud.header.stamp.sec == 123
    monkeypatch.setattr(sync.time, 'monotonic', lambda: 11.)
    sensor.cloud_callback(cloud)
    assert sensor.cloud_pub.publish.call_count == 1


def test_odom_tf_once_per_rgb_stamp_and_stale_odom_not_reused(monkeypatch):
    sensor = Sensor()
    monkeypatch.setattr(sync.time, 'monotonic', lambda: 10.)
    odom = Odometry(); odom.header.frame_id = 'odom'; odom.child_frame_id = 'base_link'
    sensor.odom_callback(odom)
    sensor.odom_pub.publish.assert_not_called()
    rgb = Image(); rgb.header.stamp.sec = 20
    sensor.rgb_callback(rgb)
    sensor.odom_callback(odom)
    assert sensor.odom_pub.publish.call_count == sensor.tf_pub.sendTransform.call_count == 1
    tf = sensor.tf_pub.sendTransform.call_args.args[0]
    assert tf.header.frame_id == 'odom' and tf.child_frame_id == 'base_link'
    assert tf.header.stamp.sec == 20
    monkeypatch.setattr(sync.time, 'monotonic', lambda: 11.)
    rgb.header.stamp.sec = 21
    sensor.rgb_callback(rgb)
    assert sensor.odom_pub.publish.call_count == 1


def test_visual_yaw_updates_pose_and_tf_identically_without_mutating_native(monkeypatch):
    import math
    from go2_slam_nav.heading_fusion import HeadingFusion
    sensor = Sensor(); sensor.heading_fusion = HeadingFusion(); sensor.get_logger = Mock()
    monkeypatch.setattr(sync.time, 'monotonic', lambda: 10.)
    odom = Odometry(); odom.pose.pose.orientation.w = 1.; odom.pose.pose.position.x = 1.
    sensor.last_odom, sensor.last_odom_time = odom, 10.
    image = Image(); image.header.stamp.sec = 20; sensor.rgb_callback(image)
    sensor.heading_fusion.offset = .1
    image.header.stamp.nanosec = 100000000; sensor.rgb_callback(image)
    out = sensor.odom_pub.publish.call_args.args[0]; tf = sensor.tf_pub.sendTransform.call_args.args[0]
    assert abs(out.pose.pose.orientation.z-math.sin(.05)) < 1e-8
    assert tf.transform.rotation == out.pose.pose.orientation
    assert tf.transform.translation.x == out.pose.pose.position.x
    assert odom.pose.pose.orientation.z == 0. and odom.pose.pose.orientation.w == 1.


def source_sensor():
    sensor = Sensor()
    sensor.use_source_stamps = True
    sensor.max_source_stamp_skew = 1.
    sensor.get_logger = Mock()
    return sensor


def test_delayed_rgb_does_not_relabel_or_repeat_native_odometry(monkeypatch):
    sensor = source_sensor()
    monkeypatch.setattr(sync.time, 'monotonic', lambda: 10.)
    rgb = Image(); rgb.header.stamp.sec = 100
    sensor.rgb_callback(rgb)
    odom = Odometry(); odom.header.stamp.sec = 100
    odom.header.stamp.nanosec = 150_000_000
    odom.pose.pose.position.x = 1.5
    odom.pose.pose.orientation.w = 1.
    sensor.odom_callback(odom)
    first = sensor.odom_pub.publish.call_args.args[0]
    assert first.header.stamp == odom.header.stamp
    assert first.pose == odom.pose
    assert sensor.tf_pub.sendTransform.call_args.args[0].header.stamp == odom.header.stamp
    odom.header.stamp.nanosec = 156_666_667
    sensor.odom_callback(odom)
    assert sensor.odom_pub.publish.call_count == 2  # preserve 150 Hz between images
    rgb.header.stamp.nanosec = 66_666_667
    sensor.rgb_callback(rgb)
    assert sensor.odom_pub.publish.call_count == 2  # no cached pose on camera tick
    assert first.header.stamp.nanosec == 150_000_000  # output is not aliased


def test_source_cloud_keeps_acquisition_time_and_rejects_other_epoch(monkeypatch):
    sensor = source_sensor()
    monkeypatch.setattr(sync.time, 'monotonic', lambda: 10.)
    rgb = Image(); rgb.header.stamp.sec = 100
    sensor.rgb_callback(rgb)
    cloud = PointCloud2(); cloud.header.frame_id = 'base_link'
    cloud.header.stamp.sec = 100; cloud.header.stamp.nanosec = 120_000_000
    sensor.cloud_callback(cloud)
    output = sensor.cloud_pub.publish.call_args.args[0]
    assert output.header == cloud.header
    cloud.header.stamp.sec = 900
    sensor.cloud_callback(cloud)
    assert sensor.cloud_pub.publish.call_count == 1
    cloud.header.stamp.sec = 0; cloud.header.stamp.nanosec = 0
    sensor.cloud_callback(cloud)
    assert sensor.cloud_pub.publish.call_count == 1


def test_source_odom_drops_reverse_time_and_stale_camera(monkeypatch):
    sensor = source_sensor()
    monkeypatch.setattr(sync.time, 'monotonic', lambda: 10.)
    rgb = Image(); rgb.header.stamp.sec = 100
    sensor.rgb_callback(rgb)
    odom = Odometry(); odom.header.stamp.sec = 100
    odom.header.stamp.nanosec = 100_000_000
    sensor.odom_callback(odom)
    sensor.odom_callback(odom)
    odom.header.stamp.nanosec = 90_000_000
    sensor.odom_callback(odom)
    assert sensor.odom_pub.publish.call_count == 1
    monkeypatch.setattr(sync.time, 'monotonic', lambda: 11.)
    odom.header.stamp.nanosec = 200_000_000
    sensor.odom_callback(odom)
    assert sensor.odom_pub.publish.call_count == 1
