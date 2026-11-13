"""Filter Nav2 L1 returns by gravity-aligned height relative to the robot.

Do not feed the filtered cloud to RTAB-Map. Map z and odom z can change after
localization; the height gate must move with the standing robot instead.
"""
import copy
import math
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import PointCloud2, PointField
from tf2_ros import Buffer, TransformListener, TransformException


def filtered_cloud(msg, gravity_row, height_offset, minimum=-.20, maximum=1.20):
    """Keep all original fields, acquisition header and surviving point bytes."""
    fields = {f.name: f for f in msg.fields}
    if not all(k in fields for k in ('x', 'y', 'z')):
        raise ValueError('Cloud requires XYZ fields')
    formats = []
    for k in ('x', 'y', 'z'):
        f = fields[k]
        if f.datatype not in (PointField.FLOAT32, PointField.FLOAT64) or f.count != 1:
            raise ValueError('XYZ must be scalar floating point')
        formats.append(('>' if msg.is_bigendian else '<') +
                       ('f4' if f.datatype == PointField.FLOAT32 else 'f8'))
    dt = np.dtype({'names': ['x', 'y', 'z'], 'formats': formats,
                   'offsets': [fields[k].offset for k in ('x', 'y', 'z')],
                   'itemsize': msg.point_step})
    a = np.ndarray((msg.height, msg.width), dtype=dt, buffer=msg.data,
                   strides=(msg.row_step, msg.point_step))
    xyz = np.stack([a[k] for k in ('x', 'y', 'z')], axis=-1)
    heights = xyz @ np.asarray(gravity_row) + height_offset
    keep = np.isfinite(xyz).all(axis=-1) & (heights >= minimum) & (heights <= maximum)
    raw = np.ndarray((msg.height, msg.width, msg.point_step), dtype=np.uint8,
                     buffer=msg.data, strides=(msg.row_step, msg.point_step, 1))
    out = copy.copy(msg)
    out.height, out.width = 1, int(keep.sum())
    out.row_step, out.data = out.width * msg.point_step, raw[keep].tobytes()
    out.is_dense = True
    return out


class ObstacleCloudFilter(Node):
    def __init__(self):
        super().__init__('go2_obstacle_cloud_filter')
        self.declare_parameter('minimum_body_height', -.20)
        self.declare_parameter('maximum_body_height', 1.20)
        self.minimum = self.get_parameter('minimum_body_height').value
        self.maximum = self.get_parameter('maximum_body_height').value
        if not (math.isfinite(self.minimum) and math.isfinite(self.maximum) and
                self.minimum < self.maximum):
            raise ValueError('Invalid obstacle height range')
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        self.publisher = self.create_publisher(PointCloud2, '/go2_nav/obstacle_cloud', 10)
        self.create_subscription(PointCloud2, '/cloud_base_synced', self.callback,
                                 qos_profile_sensor_data)
        self.last_warning = -math.inf

    def callback(self, msg):
        try:
            stamp = Time.from_msg(msg.header.stamp)
            sensor = self.buffer.lookup_transform('odom', msg.header.frame_id, stamp).transform
            base = self.buffer.lookup_transform('odom', 'base_link', stamp).transform
            q = sensor.rotation
            if abs(q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w - 1.) > 1e-3:
                raise ValueError('Invalid sensor rotation')
            row = [2*(q.x*q.z-q.w*q.y), 2*(q.y*q.z+q.w*q.x),
                   1-2*(q.x*q.x+q.y*q.y)]
            out = filtered_cloud(msg, row, sensor.translation.z-base.translation.z,
                                 self.minimum, self.maximum)
            self.publisher.publish(out)
        except (TransformException, ValueError) as exc:
            now = time.monotonic()
            if now-self.last_warning > 2.:
                self.get_logger().warning('Obstacle cloud dropped: '+str(exc))
                self.last_warning = now


def main(args=None):
    rclpy.init(args=args)
    node = ObstacleCloudFilter()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
