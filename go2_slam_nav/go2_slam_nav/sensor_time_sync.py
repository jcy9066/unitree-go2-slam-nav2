"""Approximate camera-clock alignment for the current Go2 L1/RGB-D setup.

This preserves the existing latest-RGB-stamp convention; it is not hardware
synchronization. Stale camera input stops output instead of reusing old stamps.
The RealSense driver supplies camera_link -> color/optical frame transforms.
"""
import copy
import time

import rclpy
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, PointCloud2
from tf2_ros import TransformBroadcaster


class SensorTimeSync(Node):
    def __init__(self):
        super().__init__('sensor_time_sync')
        self.declare_parameter('in_cloud', '/utlidar/cloud_base')
        self.declare_parameter('out_cloud', '/cloud_base_synced')
        self.declare_parameter('rgb_topic', '/camera/color/image_raw')
        self.declare_parameter('in_odom', '/utlidar/robot_odom')
        self.declare_parameter('out_odom', '/robot_odom_fixed')
        self.declare_parameter('publish_odom', True)
        self.declare_parameter('camera_timeout', 0.5)
        self.stamp = None
        self.last_rgb_time = None
        self.last_odom_stamp = None
        self.last_odom = None
        self.last_odom_time = None
        self.cloud_pub = self.create_publisher(PointCloud2, self.get_parameter('out_cloud').value, 10)
        self.odom_pub = self.create_publisher(Odometry, self.get_parameter('out_odom').value, 10)
        self.tf_pub = TransformBroadcaster(self)
        self.create_subscription(Image, self.get_parameter('rgb_topic').value,
                                 self.rgb_callback, qos_profile_sensor_data)
        self.create_subscription(PointCloud2, self.get_parameter('in_cloud').value,
                                 self.cloud_callback, qos_profile_sensor_data)
        if self.get_parameter('publish_odom').value:
            self.create_subscription(Odometry, self.get_parameter('in_odom').value,
                                     self.odom_callback, qos_profile_sensor_data)

    def rgb_callback(self, msg):
        self.stamp = msg.header.stamp
        self.last_rgb_time = time.monotonic()
        if (self.last_odom is not None and self.last_odom_time is not None and
                time.monotonic() - self.last_odom_time <= 0.5):
            self.publish_odom(self.last_odom)

    def fresh(self):
        return (self.stamp is not None and self.last_rgb_time is not None and
                time.monotonic() - self.last_rgb_time <= self.get_parameter('camera_timeout').value)

    def odom_callback(self, msg):
        self.last_odom = msg
        self.last_odom_time = time.monotonic()
        if self.fresh():
            self.publish_odom(msg)

    def publish_odom(self, msg):
        stamp_key = (self.stamp.sec, self.stamp.nanosec)
        if stamp_key == self.last_odom_stamp:
            return  # One odometry/TF sample per camera stamp; avoid TF duplicates.
        self.last_odom_stamp = stamp_key
        out = copy.deepcopy(msg)
        out.header.stamp = self.stamp
        out.header.frame_id = out.header.frame_id or 'odom'
        out.child_frame_id = out.child_frame_id or 'base_link'
        self.odom_pub.publish(out)
        tf = TransformStamped()
        tf.header = out.header
        tf.child_frame_id = out.child_frame_id
        tf.transform.translation.x = out.pose.pose.position.x
        tf.transform.translation.y = out.pose.pose.position.y
        tf.transform.translation.z = out.pose.pose.position.z
        tf.transform.rotation = out.pose.pose.orientation
        self.tf_pub.sendTransform(tf)

    def cloud_callback(self, msg):
        if self.fresh():
            out = copy.deepcopy(msg)
            out.header.stamp = self.stamp
            self.cloud_pub.publish(out)


def main(args=None):
    rclpy.init(args=args)
    node = SensorTimeSync()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
