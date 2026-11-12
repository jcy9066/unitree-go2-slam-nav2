"""Read-only reconnect/preflight check. HEALTHY means ROS readiness, not safety."""
import argparse
import json
import time

import rclpy
from rclpy.parameter import parameter_value_to_python
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from rcl_interfaces.srv import GetParameters
from lifecycle_msgs.srv import GetState
from nav_msgs.msg import Odometry
from sensor_msgs.msg import CameraInfo, PointCloud2
from rtabmap_msgs.msg import OdomInfo
from tf2_ros import Buffer, TransformListener, TransformException


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=float,default=4.)
    args=parser.parse_args()
    if not 2. <= args.seconds <= 15.:
        parser.error('--seconds must be between 2 and 15')
    rclpy.init(); node=rclpy.create_node('go2_navigation_health')
    buffer=Buffer(); listener=TransformListener(buffer,node)
    counts={}; last={}; heading=[]; failures=[]
    for topic,kind in [('/camera/color/camera_info',CameraInfo),
                       ('/utlidar/robot_odom',Odometry),('/robot_odom_fixed',Odometry),
                       ('/cloud_base_synced',PointCloud2),('/go2_nav/obstacle_cloud',PointCloud2)]:
        def callback(msg, topic=topic):
            counts[topic]=counts.get(topic,0)+1; last[topic]=time.monotonic()
        node.create_subscription(kind,topic,callback,qos_profile_sensor_data)
    node.create_subscription(OdomInfo,'/go2_heading/info',heading.append,qos_profile_sensor_data)
    deadline=time.monotonic()+args.seconds
    while time.monotonic()<deadline:
        rclpy.spin_once(node,timeout_sec=.03)
    for topic in ['/camera/color/camera_info','/utlidar/robot_odom','/robot_odom_fixed',
                  '/cloud_base_synced','/go2_nav/obstacle_cloud']:
        if topic not in last or time.monotonic()-last[topic]>.7:
            failures.append('Missing/stale sensor: '+topic)
    if not heading or heading[-1].lost:
        failures.append('Relative visual odometry is lost or missing')
    def call(kind,path,request):
        client=node.create_client(kind,path)
        if not client.wait_for_service(timeout_sec=1.):
            failures.append('Missing service: '+path); return None
        future=client.call_async(request)
        rclpy.spin_until_future_complete(node,future,timeout_sec=2.)
        if not future.done() or future.result() is None:
            failures.append('Service timeout: '+path); return None
        return future.result()
    states={}
    for target in ['controller_server','planner_server','bt_navigator',
                   'waypoint_follower','velocity_smoother']:
        response=call(GetState,'/'+target+'/get_state',GetState.Request())
        states[target]=response.current_state.label if response else None
        if states[target]!='active': failures.append('Inactive server: '+target)
    params={}
    for target,keys in {
        'planner_server':['GridBased.allow_unknown'],
        'controller_server':['progress_checker.plugin','progress_checker.required_movement_angle',
                             'FollowPath.max_vel_x','FollowPath.min_speed_theta','FollowPath.max_vel_theta'],
        'sport_ctrl':['enabled','max_linear_x','max_angular_z'],
        'waypoint_follower':['stop_on_failure'],
        'go2_heading_vo':['Odom/GuessMotion','Odom/ResetCountdown'],
    }.items():
        response=call(GetParameters,'/'+target+'/get_parameters',GetParameters.Request(names=keys))
        params[target]=dict(zip(keys,map(parameter_value_to_python,response.values))) if response else {}
    if params['planner_server'].get('GridBased.allow_unknown') is not False:
        failures.append('Unknown-space traversal is not disabled')
    if params['controller_server'].get('progress_checker.plugin')!='nav2_controller::PoseProgressChecker':
        failures.append('Angular progress checker is not loaded')
    if params['controller_server'].get('FollowPath.max_vel_x')!=.5 or params['sport_ctrl'].get('max_linear_x')!=.5:
        failures.append('Forward command caps do not match0.5m/s')
    try:
        transform=buffer.lookup_transform('map','base_link',Time())
        age=(node.get_clock().now().nanoseconds-Time.from_msg(transform.header.stamp).nanoseconds)/1e9
        if age>.7: failures.append('Map/base TF is stale')
    except TransformException as exc:
        age=None; failures.append('Map/base TF unavailable: '+str(exc))
    result={'status':'HEALTHY' if not failures else 'NOT READY','failures':failures,
            'sensor_counts':counts,'heading_inliers':heading[-1].inliers if heading else None,
            'server_states':states,'parameters':params,'map_base_age_s':age,
            'scope':'Read-only ROS check; operator must verify physical pose/clearance. No motion sent.'}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    node.destroy_node();rclpy.shutdown()
    return 1 if failures else 0


if __name__=='__main__':
    raise SystemExit(main())
