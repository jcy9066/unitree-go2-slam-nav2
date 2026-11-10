"""Motor-independent forward-only bounds, applied immediately before Sport encoding."""
import math


def bounded_command(x, y, yaw, max_x=0.3, max_yaw=1.8):
    if not all(math.isfinite(value) for value in (x, y, yaw)):
        return 0.0, 0.0, 0.0
    return max(0.0, min(x, max_x)), 0.0, max(-max_yaw, min(yaw, max_yaw))
