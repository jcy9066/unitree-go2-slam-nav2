"""Relative visual yaw constrains native-odom drift without owning another TF edge."""
from collections import deque
import math


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


class HeadingFusion:
    """Keep native displacement; rotate increments into the corrected odom frame."""
    def __init__(self, timeout=.5, match_tolerance=.04, time_constant=.5, max_rate=.05):
        self.timeout, self.match_tolerance = timeout, match_tolerance
        self.time_constant, self.max_rate = time_constant, max_rate
        self.history = deque(maxlen=150)
        self.last = None
        self.xy = None
        self.raw_unwrapped = 0.
        self.offset = self.target = 0.
        self.anchor = self.visual = None
        self.frame = None
        self.accepted = self.rejected = 0

    def native(self, stamp, x, y, yaw):
        if not all(math.isfinite(v) for v in (stamp, x, y, yaw)):
            raise ValueError('Non-finite native odometry')
        if self.last is None:
            self.xy, self.raw_unwrapped = (x, y), yaw
        else:
            old_stamp, ox, oy, old_yaw = self.last
            dt = stamp-old_stamp
            if dt <= 0:
                raise ValueError('Native camera stamps must increase')
            if math.hypot(x-ox, y-oy) > .2+2.*dt or abs(wrap(yaw-old_yaw)) > .2+3.*dt:
                raise ValueError('Native odometry discontinuity; reinitialize localization')
            self.raw_unwrapped += wrap(yaw-old_yaw)
            old_offset = self.offset
            if self.visual is not None and 0 <= stamp-self.visual[0] <= self.timeout:
                step = (self.target-self.offset)*dt/(self.time_constant+dt)
                self.offset += max(-self.max_rate*dt, min(step, self.max_rate*dt))
            else:
                self.anchor = self.visual = None
                self.target = self.offset
            angle = (old_offset+self.offset)/2
            c, s = math.cos(angle), math.sin(angle)
            dx, dy = x-ox, y-oy
            self.xy = (self.xy[0]+c*dx-s*dy, self.xy[1]+s*dx+c*dy)
        self.last = (stamp, x, y, yaw)
        self.history.append((stamp, self.raw_unwrapped, self.offset))
        return (*self.xy, wrap(yaw+self.offset))

    def observe(self, stamp, yaw, covariance, frame):
        if (not self.history or not frame or not all(math.isfinite(v) for v in
                (stamp, yaw, covariance)) or not 0 <= covariance <= .05):
            self.anchor = self.visual = None
            self.rejected += 1
            return False
        matched = min(self.history, key=lambda r: abs(r[0]-stamp))
        if abs(matched[0]-stamp) > self.match_tolerance or self.last[0]-stamp > self.timeout:
            self.rejected += 1
            return False
        raw, offset = matched[1:]
        if self.visual is not None:
            dt = stamp-self.visual[0]
            if dt <= 0:
                self.rejected += 1
                return False
            if frame != self.frame or dt > self.timeout:
                self.anchor = self.visual = None
            else:
                visual_step = wrap(yaw-self.visual[1])
                raw_step = raw-self.visual[3]
                if abs(wrap(visual_step-raw_step)) > .03+.05*dt:
                    self.anchor = self.visual = None
                    self.rejected += 1
                    return False
        if self.anchor is None:
            self.anchor = (yaw, raw, offset)
            unwrapped = yaw
        else:
            unwrapped = self.visual[2]+wrap(yaw-self.visual[1])
        self.target = self.anchor[2]+(unwrapped-self.anchor[0])-(raw-self.anchor[1])
        self.visual = (stamp, yaw, unwrapped, raw)
        self.frame = frame
        self.accepted += 1
        return True
