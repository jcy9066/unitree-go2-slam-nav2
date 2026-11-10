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
