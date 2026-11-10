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
from ament_index_python.packages import get_package_prefix
from dwb_msgs.msg import LocalPlanEvaluation, TrajectoryScore, CriticScore
from nav2_msgs.msg import Costmap
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy


def main():
    if os.environ.get('ROS_DOMAIN_ID', '0') == '0' or 'name="lo"' not in os.environ.get('CYCLONEDDS_URI', ''):
        raise RuntimeError('This synthetic test requires a nonzero domain and loopback-only CycloneDDS')
    root = Path(tempfile.mkdtemp(prefix='go2-recorder-smoke-'))
    exe = Path(get_package_prefix('go2_slam_nav'))/'lib/go2_slam_nav/navigation_recorder'
    log = (root/'process.log').open('w')
    process = subprocess.Popen([str(exe), '--ros-args', '-p', 'output_dir:='+str(root), '-p', 'duration:=6.0'], stdout=log, stderr=subprocess.STDOUT)
    rclpy.init(); node = rclpy.create_node('synthetic_evaluation_fixture')
    try:
        evaluation_pub = node.create_publisher(LocalPlanEvaluation, '/evaluation', 10)
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
        for _ in range(3):
            msg.header.stamp=node.get_clock().now().to_msg(); evaluation_pub.publish(msg); costmap_pub.publish(grid)
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
        assert evaluations[0]['data']['invalid_count']==2 and evaluations[0]['data']['selected_index']==2
        assert base64.b64decode(grids[0]['data']['data'])[55]==254
        print('PASS: real DDS evaluation + both rejection critics + raw costmap roundtrip, clean timed shutdown, zero motion publishers')
        print('Evidence:',root)
    finally:
        if process.poll() is None:process.kill();process.wait()
        log.close();node.destroy_node();rclpy.try_shutdown()


if __name__=='__main__':main()
