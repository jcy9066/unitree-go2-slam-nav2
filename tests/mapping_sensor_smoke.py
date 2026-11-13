"""Explicit loopback-only ROS check for the mapping preflight, never real Go2."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import rclpy
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Image, CameraInfo, PointCloud2


def main():
    if os.environ.get('ROS_DOMAIN_ID', '0') == '0' or 'name="lo"' not in os.environ.get('CYCLONEDDS_URI', ''):
        raise RuntimeError('Requires a nonzero domain and loopback-only CycloneDDS')
    rclpy.init(); node=rclpy.create_node('synthetic_mapping_sensor_fixture')
    pubs=[]
    for t,typ in [('/camera/color/image_raw',Image),('/camera/aligned_depth_to_color/image_raw',Image),
                  ('/camera/color/camera_info',CameraInfo),('/utlidar/cloud_base',PointCloud2),
                  ('/utlidar/robot_odom',Odometry)]:
        pubs.append((node.create_publisher(typ,t,10),typ()))
    helper=Path(__file__).parents[1]/'scripts/mapping_preflight.py'

    def run(mode):
        p=subprocess.Popen([sys.executable,str(helper),mode,'--timeout','4'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+9
            while p.poll() is None and time.monotonic()<deadline:
                for pub,msg in pubs:pub.publish(msg)
                rclpy.spin_once(node,timeout_sec=.05)
            out,err=p.communicate(timeout=2)
            return p.returncode,json.loads(out.strip().splitlines()[-1])
        finally:
            if p.poll() is None:p.kill();p.wait()
    blocker=None
    try:
        rc,d=run('ready');assert rc==0 and len(d['received'])==5,d
        blocker=rclpy.create_node('controller_server')
        rc,d=run('ready');assert rc==2 and d['active_nodes'],d
        blocker.destroy_node();blocker=None
        # Camera publisher exists, but aligned depth is absent: refuse duplication.
        pub,_=pubs.pop(1);node.destroy_publisher(pub)
        rc,d=run('camera');assert rc==3 and '/camera/aligned_depth_to_color/image_raw' in d['missing_or_stale'],d
        for topic in ['/api/sport/request','/go2_nav/cmd_vel','/go2_nav/cmd_vel_raw']:
            assert not node.get_publishers_info_by_topic(topic)
        print('PASS: five fresh inputs, duplicate-SLAM guard, stale-camera guard, zero motion publishers')
    finally:
        if blocker:blocker.destroy_node()
        node.destroy_node();rclpy.try_shutdown()


if __name__=='__main__':main()
