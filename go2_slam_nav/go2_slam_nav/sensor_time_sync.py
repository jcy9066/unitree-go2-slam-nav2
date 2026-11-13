"""Approximate camera-clock alignment for the current Go2 L1/RGB-D setup.

The default preserves the legacy latest-RGB-stamp convention; it is not hardware
synchronization. Opt-in source mode retains acquisition times for TF interpolation.
Stale camera input stops output instead of reusing old stamps.
The RealSense driver supplies camera_link -> color/optical frame transforms.
"""
import math
import copy
import time

import rclpy
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, PointCloud2
from tf2_ros import TransformBroadcaster
from go2_slam_nav.heading_fusion import HeadingFusion


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
        self.declare_parameter('visual_heading', False)
        self.declare_parameter('stamp_mode', 'latest_rgb')
        self.declare_parameter('max_source_stamp_skew', 1.0)
        mode = self.get_parameter('stamp_mode').value
        if mode not in ('latest_rgb', 'source'):
            raise ValueError('stamp_mode must be latest_rgb or source')
        self.use_source_stamps = mode == 'source'
        self.max_source_stamp_skew = float(self.get_parameter('max_source_stamp_skew').value)
        if not math.isfinite(self.max_source_stamp_skew) or self.max_source_stamp_skew <= 0:
            raise ValueError('max_source_stamp_skew must be positive and finite')
        self.declare_parameter('visual_odom_topic', '/go2_heading/odom')
        self.heading_fusion = HeadingFusion() if self.get_parameter('visual_heading').value else None
        if self.heading_fusion is not None:
            self.create_subscription(Odometry, self.get_parameter('visual_odom_topic').value,
                                     self.visual_callback, qos_profile_sensor_data)
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
        if (not getattr(self, 'use_source_stamps', False) and
                self.last_odom is not None and self.last_odom_time is not None and
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
        source_mode = getattr(self, 'use_source_stamps', False)
        stamp = msg.header.stamp if source_mode else self.stamp
        if source_mode and not compatible_stamp(stamp, self.stamp, self.max_source_stamp_skew):
            self.get_logger().warning('Dropping odometry: source and camera clocks differ')
            return
        stamp_key = (stamp.sec, stamp.nanosec)
        if (self.last_odom_stamp is not None and
                (stamp_key <= self.last_odom_stamp if source_mode else stamp_key == self.last_odom_stamp)):
            return  # One odometry/TF sample per camera stamp; avoid TF duplicates.
        self.last_odom_stamp = stamp_key
        out = copy.deepcopy(msg)
        out.header.stamp = copy.deepcopy(stamp)
        out.header.frame_id = out.header.frame_id or 'odom'
        out.child_frame_id = out.child_frame_id or 'base_link'
        fusion = getattr(self, 'heading_fusion', None)
        if fusion is not None:
            q = out.pose.pose.orientation
            yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
            try:
                x, y, _ = fusion.native(out.header.stamp.sec+out.header.stamp.nanosec*1e-9,
                                        out.pose.pose.position.x, out.pose.pose.position.y, yaw)
            except ValueError as exc:
                self.get_logger().error(str(exc))
                return
            out.pose.pose.position.x, out.pose.pose.position.y = x, y
            c, s = math.cos(fusion.offset/2), math.sin(fusion.offset/2)
            q.x, q.y, q.z, q.w = c*q.x-s*q.y, c*q.y+s*q.x, c*q.z+s*q.w, c*q.w-s*q.z
        self.odom_pub.publish(out)
        tf = TransformStamped()
        tf.header = out.header
        tf.child_frame_id = out.child_frame_id
        tf.transform.translation.x = out.pose.pose.position.x
        tf.transform.translation.y = out.pose.pose.position.y
        tf.transform.translation.z = out.pose.pose.position.z
        tf.transform.rotation = out.pose.pose.orientation
        self.tf_pub.sendTransform(tf)

    def visual_callback(self, msg):
        q = msg.pose.pose.orientation
        norm = q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w
        covariance = msg.pose.covariance[35] if abs(norm-1.) < 1e-3 else math.inf
        yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
        self.heading_fusion.observe(msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,
                                    yaw, covariance, msg.header.frame_id)

    def cloud_callback(self, msg):
        if self.fresh():
            source_mode = getattr(self, 'use_source_stamps', False)
            if source_mode and not compatible_stamp(
                    msg.header.stamp, self.stamp, self.max_source_stamp_skew):
                self.get_logger().warning('Dropping cloud: source and camera clocks differ')
                return
            out = copy.deepcopy(msg)
            if not source_mode:
                out.header.stamp = self.stamp
            self.cloud_pub.publish(out)


def compatible_stamp(source, camera, max_skew):
    """Reject missing or unrelated clock epochs; never invent acquisition times."""
    stamp_ns = source.sec * 1_000_000_000 + source.nanosec
    camera_ns = camera.sec * 1_000_000_000 + camera.nanosec
    return stamp_ns > 0 and camera_ns > 0 and abs(stamp_ns-camera_ns) <= max_skew*1e9


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
