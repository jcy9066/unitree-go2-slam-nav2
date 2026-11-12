"""Read-only navigation trace. Subscribes and reads parameters; never sends motion."""
import base64
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
import math
from pathlib import Path
import queue
import threading
import time
import uuid

import rclpy
from rclpy.node import Node
from rclpy.parameter import parameter_value_to_python
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from rclpy.executors import ExternalShutdownException
from rclpy.serialization import serialize_message
from rosidl_runtime_py.convert import message_to_ordereddict
from action_msgs.msg import GoalStatusArray
from dwb_msgs.msg import LocalPlanEvaluation
from geometry_msgs.msg import Twist, PolygonStamped, PoseWithCovarianceStamped
from nav_msgs.msg import Odometry, Path as NavPath
from nav2_msgs.msg import Costmap
from rcl_interfaces.msg import Log
from rcl_interfaces.srv import GetParameters
from sensor_msgs.msg import CameraInfo, LaserScan, PointCloud2
from rtabmap_msgs.msg import Info
from tf2_msgs.msg import TFMessage
from unitree_api.msg import Request, Response
from unitree_go.msg import SportModeState


def clean(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def obstacle_sensor_record(msg):
    """Lossless CDR preserves cloud layouts, scan NaN/Inf, frames and stamps."""
    return {'encoding': 'base64-cdr',
            'message_type': 'sensor_msgs/msg/' + type(msg).__name__,
            'header': message_to_ordereddict(msg.header),
            'data': base64.b64encode(serialize_message(msg)).decode('ascii')}


def evaluation_record(msg):
    """Keep every candidate velocity/cost; retain the chosen predicted poses."""
    candidates = []
    for t in msg.twists:
        candidates.append({'v': [t.traj.velocity.x, t.traj.velocity.y, t.traj.velocity.theta],
                           'total': t.total,
                           'critics': [[s.name, s.raw_score, s.scale] for s in t.scores]})
    i = int(msg.best_index)
    valid = 0 <= i < len(msg.twists) and math.isfinite(msg.twists[i].total) and msg.twists[i].total >= 0
    return clean({'header': message_to_ordereddict(msg.header), 'candidates': candidates,
                  'publisher_best_index': i, 'selected_index': i if valid else None,
                  'selected_poses': [[p.x, p.y, p.theta] for p in msg.twists[i].traj.poses] if valid else [],
                  'invalid_count': sum(not math.isfinite(t.total) or t.total < 0 for t in msg.twists)})


class TraceWriter:
    """Bound memory and disk work; overload drops diagnostics, never blocks control."""
    def __init__(self, base_dir, max_bytes=32 * 1024 * 1024):
        self.directory = Path(base_dir).expanduser() / (datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
        self.directory.mkdir(parents=True, exist_ok=False)
        self.stream = gzip.open(self.directory/'events.jsonl.gz', 'xt', encoding='utf-8', compresslevel=1)
        self.queue = queue.Queue(maxsize=1024)
        self.max_bytes, self.pending_bytes = max_bytes, 0
        self.lock = threading.Lock()
        self.counts, self.dropped = Counter(), Counter()
        self.error = None
        self.started_ns = time.time_ns()
        self.last_flush = time.monotonic()
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    def emit(self, topic, value, **extra):
        record = {'topic': topic, 'wall_time_ns': time.time_ns(), 'monotonic_ns': time.monotonic_ns(),
                  'data': value, **extra}
        line = json.dumps(clean(record), ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n'
        size = len(line.encode('utf-8'))
        with self.lock:
            if self.error or self.pending_bytes + size > self.max_bytes:
                self.dropped[topic] += 1
                return False
            self.pending_bytes += size
        try:
            self.queue.put_nowait((topic, line, size))
            return True
        except queue.Full:
            with self.lock:
                self.pending_bytes -= size
                self.dropped[topic] += 1
            return False

    def _write(self):
        while True:
            item = self.queue.get()
            if item is None:
                self.queue.task_done()
                break
            topic, line, size = item
            try:
                if not self.error:
                    self.stream.write(line)
                    self.counts[topic] += 1
                    if time.monotonic() - self.last_flush >= 1.:
                        self.stream.flush()
                        self.last_flush = time.monotonic()
            except OSError as exc:
                self.error = str(exc)
            finally:
                with self.lock:
                    self.pending_bytes -= size
                self.queue.task_done()
        try:
            self.stream.close()
        except OSError as exc:
            self.error = str(exc)

    def close(self):
        self.queue.put(None)
        self.thread.join()
        summary = {'started_wall_ns': self.started_ns, 'finished_wall_ns': time.time_ns(),
                   'counts': dict(self.counts), 'dropped': dict(self.dropped), 'write_error': self.error,
                   'evaluations_present': self.counts['/evaluation'] > 0,
                   'runtime_error_count': self.counts['recorder_error'],
                   'note': 'Message receipt times are recorded; exact sensor synchronization is not implied.'}
        (self.directory/'summary.json').write_text(json.dumps(summary, indent=2))
        return summary


class NavigationRecorder(Node):
    def __init__(self):
        super().__init__('navigation_recorder')
        self.declare_parameter('output_dir', str(Path.home()/'go2_maps/diagnostics'))
        self.declare_parameter('evaluation_hz', 2.0)
        self.declare_parameter('record_obstacle_sensors', False)
        self.declare_parameter('duration', 0.0)
        self.declare_parameter('config_file', '')
        self.declare_parameter('map_database', '')
        self.record_obstacle_sensors = self.get_parameter('record_obstacle_sensors').value
        self.writer = TraceWriter(self.get_parameter('output_dir').value)
        self.last = {}
        self.closed = False
        self.param_pending = set()
        self.params = {
            'controller_server': ['FollowPath.critics', 'FollowPath.min_speed_xy', 'FollowPath.min_speed_theta',
                'FollowPath.max_vel_x', 'FollowPath.max_vel_theta', 'FollowPath.publish_evaluation',
                'FollowPath.Go2WalkingSpeed.minimum_translation_speed', 'progress_checker.plugin',
                'progress_checker.required_movement_radius', 'progress_checker.movement_time_allowance'],
            'velocity_smoother': ['min_velocity', 'max_velocity', 'velocity_timeout'],
            'sport_ctrl': ['enabled', 'max_linear_x', 'max_angular_z', 'cmd_vel_timeout'],
            'rtabmap': ['database_path', 'Mem/IncrementalMemory', 'Mem/LocalizationReadOnly'],
        }
        self.parameter_clients = {k: self.create_client(GetParameters, '/'+k+'/get_parameters') for k in self.params}
        sensor = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT)
        latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
        if self.record_obstacle_sensors:
            for topic, cls in [('/cloud_base_synced', PointCloud2),
                               ('/go2_nav/depth_scan', LaserScan)]:
                self.create_subscription(cls, topic,
                                         lambda m, t=topic: self.obstacle_sensor(t, m), sensor)
            for topic, cls in [('/initialpose', PoseWithCovarianceStamped),
                               ('/localization_pose', PoseWithCovarianceStamped), ('/info', Info)]:
                self.create_subscription(cls, topic, lambda m, t=topic: self.simple(t, m), sensor)
        for topic in ['/go2_nav/cmd_vel_raw', '/go2_nav/cmd_vel']:
            self.create_subscription(Twist, topic, lambda m, t=topic: self.simple(t, m), sensor)
        self.create_subscription(LocalPlanEvaluation, '/evaluation', self.evaluation, sensor)
        for topic in ['/robot_odom_fixed', '/utlidar/robot_odom']:
            self.create_subscription(Odometry, topic, lambda m, t=topic: self.sample(t, m, 10.), sensor)
        for topic in ['/sportmodestate', '/lf/sportmodestate']:
            self.create_subscription(SportModeState, topic, lambda m, t=topic: self.sample(t, m, 10.), sensor)
        self.create_subscription(Request, '/api/sport/request', self.request, sensor)
        self.create_subscription(Response, '/api/sport/response', lambda m: self.simple('/api/sport/response', m), sensor)
        for topic in ['/plan', '/local_plan']:
            self.create_subscription(NavPath, topic, lambda m, t=topic: self.sample(t, m, 2.), sensor)
        for topic in ['/local_costmap/costmap_raw', '/global_costmap/costmap_raw']:
            self.create_subscription(Costmap, topic, lambda m, t=topic: self.costmap(t, m), latched)
        for topic in ['/local_costmap/published_footprint', '/global_costmap/published_footprint']:
            self.create_subscription(PolygonStamped, topic, lambda m, t=topic: self.sample(t, m, 2.), sensor)
        for action in ['navigate_to_pose', 'follow_path', 'compute_path_to_pose']:
            topic = '/'+action+'/_action/status'
            self.create_subscription(GoalStatusArray, topic, lambda m, t=topic: self.simple(t, m), latched)
        self.create_subscription(TFMessage, '/tf', self.transforms, sensor)
        self.create_subscription(TFMessage, '/tf_static', lambda m: self.simple('/tf_static', m), latched)
        self.create_subscription(CameraInfo, '/camera/color/camera_info', lambda m: self.sample('/camera/color/camera_info', m, 1.), sensor)
        self.create_subscription(Log, '/rosout', self.log, sensor)
        config = self.get_parameter('config_file').value
        metadata = {'utc': datetime.now(timezone.utc).isoformat(), 'evaluation_hz': self.get_parameter('evaluation_hz').value,
                    'map_database': self.get_parameter('map_database').value,
                    'config_file': config, 'config_text': Path(config).read_text() if config and Path(config).is_file() else None,
                    'request_topic': self.resolve_topic_name('/api/sport/request'),
                    'publisher_gid_supported': False,
                    'images_recorded': False,
                    'pointclouds_recorded': self.record_obstacle_sensors,
                    'laser_scans_recorded': self.record_obstacle_sensors,
                    'tf_downsampled': not self.record_obstacle_sensors,
                    'evaluation_downsampled': not self.record_obstacle_sensors,
                    'candidate_scores_may_be_partial': 'DWB short_circuit_trajectory_evaluation is unchanged.'}
        (self.writer.directory/'metadata.json').write_text(json.dumps(metadata, indent=2))
        self.create_timer(5., self.parameters_and_graph)
        duration = self.get_parameter('duration').value
        self.deadline = time.monotonic() + duration if duration > 0 else None
        self.get_logger().info('Read-only diagnostics: '+str(self.writer.directory))

    def due(self, key, hz):
        now = time.monotonic()
        if now - self.last.get(key, -math.inf) < 1. / max(hz, .01):
            return False
        self.last[key] = now
        return True

    def simple(self, topic, msg, **extra):
        self.writer.emit(topic, message_to_ordereddict(msg), ros_receive_ns=self.get_clock().now().nanoseconds, **extra)

    def sample(self, topic, msg, hz):
        if self.due(topic, hz):
            self.simple(topic, msg)

    def evaluation(self, msg):
        if self.record_obstacle_sensors or self.due('/evaluation', self.get_parameter('evaluation_hz').value):
            self.writer.emit('/evaluation', evaluation_record(msg), ros_receive_ns=self.get_clock().now().nanoseconds)

    def obstacle_sensor(self, topic, msg):
        if self.record_obstacle_sensors:
            self.writer.emit(topic, obstacle_sensor_record(msg),
                             ros_receive_ns=self.get_clock().now().nanoseconds)

    def request(self, msg):
        # This Humble rclpy executor passes only the message to subscriptions.
        # The graph lists endpoints, but per-sample publisher GIDs are unavailable.
        self.simple('/api/sport/request', msg, publisher_gid=None)

    def costmap(self, topic, msg):
        hz = 5. if topic.startswith('/local') else (1. if self.record_obstacle_sensors else .2)
        if self.due(topic, hz):
            raw = msg.data.tobytes() if hasattr(msg.data, 'tobytes') else bytes(v & 255 for v in msg.data)
            self.writer.emit(topic, {'header': message_to_ordereddict(msg.header), 'metadata': message_to_ordereddict(msg.metadata),
                                     'encoding': 'base64-uint8', 'data': base64.b64encode(raw).decode('ascii')},
                             ros_receive_ns=self.get_clock().now().nanoseconds)

    def transforms(self, msg):
        transforms = [t for t in msg.transforms if t.header.frame_id in ['map', 'odom'] and
                      t.child_frame_id in ['odom', 'base_link'] and
                      (self.record_obstacle_sensors or self.due('tf:'+t.child_frame_id, 10.))]
        if transforms:
            self.writer.emit('/tf', [message_to_ordereddict(t) for t in transforms], ros_receive_ns=self.get_clock().now().nanoseconds)

    def log(self, msg):
        if msg.level >= 20 and any(s in msg.name for s in ['controller_server', 'planner_server', 'bt_navigator',
                                                          'costmap', 'behavior_server', 'sport_ctrl', 'rtabmap']):
            self.simple('/rosout', msg)

    def parameters_and_graph(self):
        for node, client in self.parameter_clients.items():
            if node in self.param_pending or not client.service_is_ready() or not self.due('params:'+node, 1./30.):
                continue
            req = GetParameters.Request(); req.names = self.params[node]
            future = client.call_async(req); self.param_pending.add(node)
            def done(f, name=node):
                self.param_pending.discard(name)
                if f.exception() is None:
                    self.writer.emit('parameters:'+name, dict(zip(self.params[name], [parameter_value_to_python(p) for p in f.result().values])))
            future.add_done_callback(done)
        self.writer.emit('sport_publisher_graph', [{'node': p.node_name, 'namespace': p.node_namespace,
                         'gid': bytes(p.endpoint_gid).hex()} for p in self.get_publishers_info_by_topic('/api/sport/request')])
        if self.writer.error:
            self.get_logger().error('Diagnostic disk write failed: '+self.writer.error)

    def close(self):
        if not self.closed:
            self.closed = True
            return self.writer.close()


def main(args=None):
    rclpy.init(args=args)
    node = NavigationRecorder()
    try:
        while rclpy.ok() and (node.deadline is None or time.monotonic() < node.deadline):
            rclpy.spin_once(node, timeout_sec=0.2)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except Exception as exc:
        node.writer.emit('recorder_error', {'type': type(exc).__name__, 'message': str(exc)})
        raise
    finally:
        summary = node.close()
        print('Diagnostics saved:', node.writer.directory, 'counts:', summary['counts'], flush=True)
        node.destroy_node()
        rclpy.try_shutdown()
