#!/usr/bin/env python3
"""RealSense SDK color-only capture -> bounded, leaky H.264/RTP pipeline."""
import os
import signal
import threading
import time

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
import numpy as np
import pyrealsense2 as rs
if not hasattr(rs, 'pipeline'):
    from pyrealsense2 import pyrealsense2 as rs


def main():
    Gst.init(None)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.set())
    width = int(os.getenv('INPUT_WIDTH', '640'))
    height = int(os.getenv('INPUT_HEIGHT', '360'))
    capture_fps = int(os.getenv('INPUT_FPS', '30'))
    out_width = int(os.getenv('OUTPUT_WIDTH', '480'))
    out_height = int(os.getenv('OUTPUT_HEIGHT', '270'))
    fps = int(os.getenv('OUTPUT_FPS', '20'))
    bitrate = int(os.getenv('BITRATE_KBPS', '800'))
    duration = float(os.getenv('DURATION_SEC', '3600'))
    deadline = time.monotonic() + duration if duration > 0 else float('inf')
    serial = os.getenv('REALSENSE_SERIAL', '')
    while not stop.is_set() and time.monotonic() < deadline:
        camera = rs.pipeline()
        encoder = None
        started = False
        try:
            devices = list(rs.context().query_devices())
            serials = [d.get_info(rs.camera_info.serial_number) for d in devices]
            chosen = serial
            if chosen not in serials:
                if len(devices) != 1:
                    raise RuntimeError(f'cannot uniquely select RealSense: requested={serial}, found={serials}')
                chosen = serials[0]
            config = rs.config()
            config.enable_device(chosen)
            config.enable_stream(rs.stream.color, width, height, rs.format.bgr8, capture_fps)
            # SDK queue holds just one frameset: a slow consumer skips old frames.
            frames = rs.frame_queue(1)
            profile = camera.start(config, frames)
            started = True
            encoder = Gst.parse_launch(
                f'appsrc name=source is-live=true format=time do-timestamp=true block=false '
                f'max-buffers=1 leaky-type=downstream '
                f'caps=video/x-raw,format=BGR,width={width},height={height},framerate={fps}/1 '
                f'! queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 '
                f'! videoconvert ! videoscale '
                f'! video/x-raw,format=I420,width={out_width},height={out_height} '
                f'! x264enc tune=zerolatency speed-preset=ultrafast bitrate={bitrate} '
                f'key-int-max=10 bframes=0 threads=2 sliced-threads=true '
                f'rc-lookahead=0 sync-lookahead=0 vbv-buf-capacity=50 '
                f'! h264parse config-interval=-1 '
                f'! rtph264pay pt={int(os.getenv("PAYLOAD_TYPE", "97"))} '
                f'config-interval=-1 aggregate-mode=zero-latency mtu=1200 '
                f'! udpsink name=network sync=false async=false buffer-size=65536'
            )
            network = encoder.get_by_name('network')
            network.set_property('host', os.environ['PC1_IP'])
            network.set_property('port', int(os.getenv('VIDEO_PORT', '17202')))
            source = encoder.get_by_name('source')
            bus = encoder.get_bus()
            encoder.set_state(Gst.State.PLAYING)
            print(f'REALSENSE_READY serial={profile.get_device().get_info(rs.camera_info.serial_number)} '
                  f'capture={width}x{height}@{capture_fps} output={out_width}x{out_height}@{fps}', flush=True)
            next_send = time.monotonic()
            last_frame = next_send
            report_at = next_send
            count = 0
            while not stop.is_set() and time.monotonic() < deadline:
                message = bus.pop_filtered(Gst.MessageType.ERROR)
                if message:
                    error, debug = message.parse_error()
                    raise RuntimeError(f'{error}: {debug}')
                try:
                    frame = frames.wait_for_frame(1000).as_frameset().get_color_frame()
                except RuntimeError:
                    if time.monotonic() - last_frame > 3:
                        raise RuntimeError('no RealSense color frame for 3 seconds')
                    continue
                if not frame:
                    continue
                now = time.monotonic()
                last_frame = now
                if now < next_send:
                    continue
                next_send = max(next_send + 1 / fps, now)
                raw = np.asanyarray(frame.get_data()).tobytes()
                buffer = Gst.Buffer.new_allocate(None, len(raw), None)
                buffer.fill(0, raw)
                buffer.duration = Gst.SECOND // fps
                result = source.emit('push-buffer', buffer)
                if result != Gst.FlowReturn.OK:
                    raise RuntimeError(f'encoder rejected frame: {result}')
                count += 1
                if now - report_at >= 5:
                    print(f'REALSENSE_PUSH_FPS={count / (now-report_at):.1f}', flush=True)
                    report_at, count = now, 0
        except Exception as exc:
            print(f'WARNING: RealSense stream: {exc}; retrying in 1s', flush=True)
        finally:
            if encoder is not None:
                encoder.set_state(Gst.State.NULL)
            if started:
                try:
                    camera.stop()
                except RuntimeError as exc:
                    print(f'WARNING: RealSense stop: {exc}', flush=True)
        stop.wait(1)


if __name__ == '__main__':
    main()
