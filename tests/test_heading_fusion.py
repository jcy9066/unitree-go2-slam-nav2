"""Exercise stationary bias, real turns, loss/recovery, and frame continuity."""
import math
import pytest
from go2_slam_nav.heading_fusion import HeadingFusion, wrap


def run(samples, native_yaw, visual_yaw):
    f = HeadingFusion()
    for i in range(samples):
        t = i/15
        f.native(t, 0., 0., native_yaw(t))
        if i%2 == 0: f.observe(t, visual_yaw(t), .001, 'vo')
    return f


def test_stationary_native_drift_is_constrained_by_visual_observation():
    f = run(1500, lambda t: .01*t, lambda t: 0.)
    assert abs(wrap(f.last[3]+f.offset)) < .008
    assert f.accepted > 700


def test_real_rotation_including_wrap_is_preserved():
    f = run(1500, lambda t: .3*t+.001*t, lambda t: wrap(.3*t))
    assert abs(wrap(f.last[3]+f.offset-.3*f.last[0])) < .003


def test_native_fallback_retains_offset_and_follows_turns():
    f = run(150, lambda t: .01*t, lambda t: 0.)
    for i in range(150,165):f.native(i/15, 0., 0., .01*i/15)
    offset = f.offset;before = f.last[3]
    f.native(11., 0., 0., before+.1)
    assert f.offset == offset and f.anchor is None
    assert wrap(f.last[3]+f.offset-(before+offset)) == pytest.approx(.1)


def test_visual_reset_reanchors_without_heading_jump():
    f = run(150, lambda t: .001*t, lambda t: 0.)
    before = f.offset;t = f.last[0]+1/15
    f.native(t, 0., 0., .001*t)
    assert f.observe(t, 0., .001, 'new_vo_frame')
    assert abs(f.target-before) < .001


def test_timestamp_covariance_and_spurious_visual_rotation_are_rejected():
    f = run(30, lambda t: 0., lambda t: 0.)
    assert not f.observe(0., 0., .001, 'vo')
    assert not f.observe(f.last[0], 1., 9999., 'vo')
    t = f.last[0]+1/15;f.native(t, 0., 0., 0.);f.observe(t, 0., .001, 'vo')
    t += 1/15;f.native(t, 0., 0., 0.)
    assert not f.observe(t, 1., .001, 'vo')


def test_corrected_frame_translation_rotates_native_displacement():
    f = HeadingFusion();f.native(0.,0.,0.,0.);f.offset = .1
    x,y,yaw = f.native(.1,.1,0.,0.)
    assert (x,y) == pytest.approx((.1*math.cos(.1),.1*math.sin(.1)))
    assert yaw == pytest.approx(.1)


def test_native_clock_and_pose_resets_do_not_publish_a_jump():
    f = HeadingFusion();f.native(1.,0.,0.,0.)
    with pytest.raises(ValueError):f.native(.9,0.,0.,0.)
    with pytest.raises(ValueError):f.native(1.01,1.,0.,0.)
