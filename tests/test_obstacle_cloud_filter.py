import sys
from pathlib import Path

import numpy as np
from sensor_msgs.msg import PointCloud2, PointField

sys.path.insert(0, str(Path(__file__).parents[1]/'go2_slam_nav'))
from go2_slam_nav.obstacle_cloud_filter import filtered_cloud


def cloud(points, *, big=False, organized=False):
    a = np.array(points, dtype='>f4' if big else '<f4')
    m = PointCloud2()
    m.header.frame_id = 'base_link'; m.header.stamp.sec = 123
    m.height, m.width = (2, len(a)//2) if organized else (1, len(a))
    m.fields = [PointField(name=k, offset=i*4, datatype=PointField.FLOAT32, count=1)
                for i, k in enumerate(['x','y','z','intensity'])]
    m.point_step = 16; m.is_bigendian = big
    m.row_step = m.width*16+4  # preserve and understand input row padding
    m.data = b''.join(a[i*m.width:(i+1)*m.width].tobytes()+b'PAD!' for i in range(m.height))
    return m


def test_floor_rejection_does_not_depend_on_map_or_odom_origin_height():
    m=cloud([[1,0,-.30,10],[1,0,-.10,20],[1,0,1.30,30],[float('nan'),0,0,40]])
    original=bytes(m.data)
    for world_z in [-.4,0.,.31,2.]:
        # sensor and robot share translation; its world datum cancels.
        out=filtered_cloud(m,[0,0,1],world_z-world_z)
        assert out.width==1 and out.height==1 and out.row_step==16
        np.testing.assert_allclose(np.frombuffer(out.data,dtype='<f4'),[1,0,-.1,20])
        assert out.header==m.header and out.fields==m.fields
    assert bytes(m.data)==original


def test_gravity_direction_tracks_pitch_and_keeps_point_bytes():
    m=cloud([[1,0,-.1,8],[0,0,-.3,9]])
    # Sensor tilted 30deg: the first nominally high point is below the gate.
    out=filtered_cloud(m,[-.5,0,np.sqrt(.75)],0.)
    assert out.width==0 and not out.data and out.row_step==0


def test_organized_big_endian_cloud_retains_non_xyz_fields_and_header():
    m=cloud([[1,0,-.3,10],[1,0,0,20],[2,0,.2,30],[2,0,1.3,40]],big=True,organized=True)
    out=filtered_cloud(m,[0,0,1],0.)
    assert out.width==2 and out.is_bigendian and out.header==m.header
    assert np.allclose(np.frombuffer(out.data,dtype='>f4').reshape(-1,4),[[1,0,0,20],[2,0,.2,30]])
