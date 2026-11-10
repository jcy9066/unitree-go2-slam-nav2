"""Exercise the actual Sport encoder and watchdog without initializing ROS/DDS."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from geometry_msgs.msg import Twist
from go2_cmd_processor import sport_ctrl


class Bridge:
    send = sport_ctrl.Go2CmdProcessor.send
    stop = sport_ctrl.Go2CmdProcessor.stop
    cmd_vel_callback = sport_ctrl.Go2CmdProcessor.cmd_vel_callback
    timer_callback = sport_ctrl.Go2CmdProcessor.timer_callback

    def __init__(self, enabled=True):
        self.values = dict(enabled=enabled, max_linear_x=.3, max_angular_z=1.8, cmd_vel_timeout=.25)
        self.publisher = Mock()
        self.stopped = True
        self.last_command_time = None

    def get_parameter(self, name):
        return SimpleNamespace(value=self.values[name])


def command(x, y, yaw):
    msg = Twist()
    msg.linear.x, msg.linear.y, msg.angular.z = x, y, yaw
    return msg


@pytest.mark.parametrize('x,y,yaw,expected', [
    (-.3, .4, .2, (0., 0., .2)), (.4, -.3, -.9, (.3, 0., -.9)),
    (.1, .1, 0., (.1, 0., 0.)),
    (.25, -.2, .1, (.25, 0., .1)),
    (.1, .2, 2.4, (.1, 0., 1.8)),
    (0., -.2, -2.4, (0., 0., -1.8)),
])
def test_encoder_cannot_send_reverse_or_lateral_translation(x, y, yaw, expected):
    bridge = Bridge()
    bridge.cmd_vel_callback(command(x, y, yaw))
    request = bridge.publisher.publish.call_args.args[0]
    assert request.header.identity.api_id == 1008
    assert tuple(json.loads(request.parameter).values()) == expected


@pytest.mark.parametrize('values', [(-.3,.2,0.), (float('nan'),0.,.2),
                                  (0.,float('inf'),0.), (0.,0.,float('-inf'))])
def test_invalid_or_reverse_only_command_sends_stop(values):
    bridge = Bridge()
    bridge.cmd_vel_callback(command(*values))
    assert bridge.publisher.publish.call_args.args[0].header.identity.api_id == 1003


def test_disabled_bridge_never_publishes_sport():
    bridge = Bridge(enabled=False)
    bridge.cmd_vel_callback(command(.1,.1,.2))
    bridge.stop()
    bridge.timer_callback()
    bridge.publisher.publish.assert_not_called()


def test_watchdog_stops_once_after_command_timeout(monkeypatch):
    bridge = Bridge()
    monkeypatch.setattr(sport_ctrl.time, 'monotonic', lambda: 10.)
    bridge.cmd_vel_callback(command(.1,0.,0.))
    monkeypatch.setattr(sport_ctrl.time, 'monotonic', lambda: 10.2)
    bridge.timer_callback()
    assert bridge.publisher.publish.call_count == 1
    monkeypatch.setattr(sport_ctrl.time, 'monotonic', lambda: 10.3)
    bridge.timer_callback()
    bridge.timer_callback()
    assert bridge.publisher.publish.call_count == 2
    assert bridge.publisher.publish.call_args.args[0].header.identity.api_id == 1003
