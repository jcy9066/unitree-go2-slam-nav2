"""Operator-enabled Nav2 Sport bridge with unconditional forward-only translation."""
import json
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from unitree_api.msg import Request

from go2_cmd_processor.motion_policy import bounded_command


class Go2CmdProcessor(Node):
    def __init__(self):
        super().__init__('go2_cmd_processor')
        self.declare_parameter('enabled', False)
        self.declare_parameter('rate', 200.0)
        self.declare_parameter('cmd_vel_timeout', 0.25)
        self.declare_parameter('max_linear_x', 0.3)
        self.declare_parameter('max_angular_z', 1.8)
        for key in ('rate', 'cmd_vel_timeout', 'max_linear_x', 'max_angular_z'):
            value = self.get_parameter(key).value
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'{key} must be finite and positive')
        self.publisher = self.create_publisher(Request, '/api/sport/request', 10)
        self.create_subscription(Twist, 'cmd_vel', self.cmd_vel_callback, 10)
        self.create_timer(1.0 / self.get_parameter('rate').value, self.timer_callback)
        self.last_command_time = None
        self.stopped = True

    def send(self, api_id, velocities=None):
        if not self.get_parameter('enabled').value:
            return
        req = Request()
        req.header.identity.api_id = api_id
        if velocities is not None:
            req.parameter = json.dumps(dict(zip(('x', 'y', 'z'), velocities)), allow_nan=False)
        self.publisher.publish(req)

    def stop(self):
        self.send(1003)  # Unitree StopMove, matching the current local bridge.
        self.stopped = True

    def cmd_vel_callback(self, msg):
        if not self.get_parameter('enabled').value:
            return
        velocities = bounded_command(msg.linear.x, msg.linear.y, msg.angular.z,
                                     self.get_parameter('max_linear_x').value,
                                     self.get_parameter('max_angular_z').value)
        self.last_command_time = time.monotonic()
        if velocities == (0.0, 0.0, 0.0):
            self.stop()
        else:
            self.send(1008, velocities)
            self.stopped = False

    def timer_callback(self):
        if (not self.stopped and self.last_command_time is not None and
                time.monotonic() - self.last_command_time >= self.get_parameter('cmd_vel_timeout').value):
            self.stop()


def main(args=None):
    rclpy.init(args=args)
    node = Go2CmdProcessor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if not node.stopped:
            node.stop()
        node.destroy_node()
        rclpy.try_shutdown()
