"""Explicit ROS smoke test; use an isolated domain, never the robot domain."""
import base64
import gzip
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

import rclpy
from rclpy.serialization import serialize_message, deserialize_message
from ament_index_python.packages import get_package_prefix
from dwb_msgs.msg import LocalPlanEvaluation, TrajectoryScore, CriticScore
from nav2_msgs.msg import Costmap
from sensor_msgs.msg import LaserScan, PointCloud2
from geometry_msgs.msg import PoseWithCovarianceStamped
from rtabmap_msgs.msg import Info
from unitree_api.msg import Request
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy


def main():
    if os.environ.get('ROS_DOMAIN_ID', '0') == '0' or 'name="lo"' not in os.environ.get('CYCLONEDDS_URI', ''):
        raise RuntimeError('This synthetic test requires a nonzero domain and loopback-only CycloneDDS')
    root = Path(tempfile.mkdtemp(prefix='go2-recorder-smoke-'))
    exe = Path(get_package_prefix('go2_slam_nav'))/'lib/go2_slam_nav/navigation_recorder'
    log = (root/'process.log').open('w')
    process = subprocess.Popen([str(exe), '--ros-args', '-p', 'output_dir:='+str(root),
                                '-p', 'duration:=6.0', '-p', 'record_obstacle_sensors:=true',
                                '-r', '/api/sport/request:=/diagnostic_request_fixture'],
                               stdout=log, stderr=subprocess.STDOUT)
    rclpy.init(); node = rclpy.create_node('synthetic_evaluation_fixture')
    try:
        request_pub = node.create_publisher(Request, '/diagnostic_request_fixture', 10)
        evaluation_pub = node.create_publisher(LocalPlanEvaluation, '/evaluation', 10)
        scan_pub = node.create_publisher(LaserScan, '/go2_nav/depth_scan', 10)
        cloud_pub = node.create_publisher(PointCloud2, '/cloud_base_synced', 10)
        pose_pub = node.create_publisher(PoseWithCovarianceStamped, '/initialpose', 10)
        info_pub = node.create_publisher(Info, '/info', 10)
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)
        costmap_pub = node.create_publisher(Costmap, '/local_costmap/costmap_raw', qos)
        deadline = time.monotonic()+3.
        while time.monotonic()<deadline and evaluation_pub.get_subscription_count()==0:
            rclpy.spin_once(node, timeout_sec=.1)
        assert evaluation_pub.get_subscription_count()>0, 'Recorder never subscribed'
        msg = LocalPlanEvaluation(); msg.header.frame_id='synthetic_test'; msg.best_index=2
        for name in ['Go2WalkingSpeed', 'ObstacleFootprint']:
            bad=TrajectoryScore(); bad.total=-1.; bad.traj.velocity.x=.08
            score=CriticScore(); score.name=name; score.raw_score=-1.; score.scale=1.
            bad.scores=[score]; msg.twists.append(bad)
        good=TrajectoryScore(); good.total=1.; good.traj.velocity.theta=.4; msg.twists.append(good)
        grid=Costmap(); grid.header.frame_id='synthetic_test'; grid.metadata.size_x=10; grid.metadata.size_y=10
        grid.metadata.resolution=.02; grid.data=[0]*100; grid.data[55]=254
        scan = LaserScan(); scan.header.frame_id = 'synthetic_scan'
        scan.ranges = [float('inf'), float('nan'), .8]
        cloud = PointCloud2(); cloud.header.frame_id = 'synthetic_cloud'
        cloud.height = 1; cloud.width = 1; cloud.point_step = 4; cloud.row_step = 4
        cloud.data = b'\x01\x02\x03\x04'
        for _ in range(3):
            msg.header.stamp=node.get_clock().now().to_msg(); evaluation_pub.publish(msg); costmap_pub.publish(grid)
            scan_pub.publish(scan); cloud_pub.publish(cloud)
            pose = PoseWithCovarianceStamped(); pose.header.frame_id = 'synthetic_map'
            pose.pose.pose.position.x = .2; pose_pub.publish(pose)
            info = Info(); info.loop_closure_id = 7; info_pub.publish(info)
            request=Request(); request.header.identity.api_id=99999; request.parameter='diagnostic metadata only'; request_pub.publish(request)
            deadline=time.monotonic()+.6
            while time.monotonic()<deadline:rclpy.spin_once(node,timeout_sec=.1)
        assert not node.get_publishers_info_by_topic('/api/sport/request')
        for topic in ['/go2_nav/cmd_vel', '/go2_nav/cmd_vel_raw']:
            assert not node.get_publishers_info_by_topic(topic)
        assert process.wait(timeout=10)==0, 'Recorder did not exit cleanly at duration'
        log.close()
        summaries=list(root.glob('*/summary.json')); assert len(summaries)==1
        summary=json.loads(summaries[0].read_text())
        assert not summary['write_error'] and not summary['dropped'] and summary['evaluations_present']
        with gzip.open(summaries[0].parent/'events.jsonl.gz', 'rt') as stream:
            records=[json.loads(line) for line in stream]
        evaluations=[r for r in records if r['topic']=='/evaluation']
        grids=[r for r in records if r['topic']=='/local_costmap/costmap_raw']
        requests=[r for r in records if r['topic']=='/api/sport/request']
        scans = [r for r in records if r['topic'] == '/go2_nav/depth_scan']
        clouds = [r for r in records if r['topic'] == '/cloud_base_synced']
        for rows, original, cls in [(scans, scan, LaserScan), (clouds, cloud, PointCloud2)]:
            assert rows, 'Raw obstacle sensor was not recorded'
            restored = deserialize_message(base64.b64decode(rows[0]['data']['data']), cls)
            assert serialize_message(restored) == serialize_message(original)
        metadata = json.loads((summaries[0].parent/'metadata.json').read_text())
        assert metadata['pointclouds_recorded'] and metadata['laser_scans_recorded']
        assert metadata['tf_downsampled'] is False
        assert metadata['evaluation_downsampled'] is False
        assert any(r['topic'] == '/initialpose' and
                   r['data']['pose']['pose']['position']['x'] == .2 for r in records)
        assert any(r['topic'] == '/info' and r['data']['loop_closure_id'] == 7 for r in records)
        assert requests and requests[0]['data']['header']['identity']['api_id']==99999
        assert requests[0]['publisher_gid'] is None
        assert json.loads((summaries[0].parent/'metadata.json').read_text())['request_topic']=='/diagnostic_request_fixture'
        assert evaluations[0]['data']['invalid_count']==2 and evaluations[0]['data']['selected_index']==2
        assert base64.b64decode(grids[0]['data']['data'])[55]==254
        print('PASS: DDS evaluation/request/costmap + lossless cloud and NaN/Inf scan CDR, timed shutdown, zero motion publishers')
        print('Evidence:',root)
    finally:
        if process.poll() is None:process.kill();process.wait()
        log.close();node.destroy_node();rclpy.try_shutdown()


if __name__=='__main__':main()
