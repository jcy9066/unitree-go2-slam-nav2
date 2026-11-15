#!/usr/bin/env python3
"""Read-only ROS /map OccupancyGrid snapshot for a mapping session; no motion."""
import argparse
import os
from pathlib import Path
import signal
import struct
import tempfile
import zlib


def _png_chunk(kind, payload):
    return struct.pack('!I', len(payload)) + kind + payload + struct.pack('!I', zlib.crc32(kind + payload) & 0xffffffff)


def occupancy_png(width, height, cells, max_side=900):
    if width <= 0 or height <= 0 or width * height != len(cells):
        raise ValueError('Invalid occupancy grid dimensions')
    step = max(1, (max(width, height) + max_side - 1) // max_side)
    out_width = (width + step - 1) // step
    out_height = (height + step - 1) // step
    rows = bytearray()
    for y in range(out_height - 1, -1, -1):
        rows.append(0)
        source_y = min(height - 1, y * step)
        for x in range(out_width):
            value = cells[source_y * width + min(width - 1, x * step)]
            rows.append(210 if value < 0 else (30 if value >= 65 else (255 if value == 0 else 130)))
    header = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack('!2I5B', out_width, out_height, 8, 0, 0, 0, 0)
    return header + _png_chunk(b'IHDR', ihdr) + _png_chunk(b'IDAT', zlib.compress(bytes(rows), 6)) + _png_chunk(b'IEND', b'')


def save_png(target, image):
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.preview-', suffix='.png', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(image)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def capture(output):
    import rclpy
    from nav_msgs.msg import OccupancyGrid
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy

    rclpy.init()
    node = rclpy.create_node('go2_map_preview_capture')
    cache = {'message': None, 'stop': False}

    def on_map(message):
        cache['message'] = message

    def stop(_signal, _frame):
        cache['stop'] = True

    qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                     durability=DurabilityPolicy.TRANSIENT_LOCAL)
    subscriber = node.create_subscription(OccupancyGrid, '/map', on_map, qos)
    signal.signal(signal.SIGTERM, stop)
    try:
        while rclpy.ok() and not cache['stop']:
            rclpy.spin_once(node, timeout_sec=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        message = cache['message']
        if message is not None:
            save_png(output, occupancy_png(message.info.width, message.info.height, message.data))
            print('[map] 미리보기 저장: ' + str(output), flush=True)
        else:
            print('[map] /map을 수신하지 못해 미리보기는 생성되지 않았습니다', flush=True)
        node.destroy_subscription(subscriber)
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    capture(args.output)
