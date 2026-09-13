#!/usr/bin/env python3
"""Independent RTP decoders, single-slot latest frames, fixed-cadence UI."""
import os
import signal
import subprocess
import threading
import time

import cv2
import numpy as np


def decoder_command(port, width, height, jitter, payload=None):
    caps = 'application/x-rtp,media=video,encoding-name=H264,clock-rate=90000'
    if payload is not None:
        caps += f',payload={payload}'
    return [
        'gst-launch-1.0', '-q', 'udpsrc', 'address=0.0.0.0', f'port={port}',
        'buffer-size=262144', f'caps={caps}', '!', 'rtpjitterbuffer',
        f'latency={jitter}', 'drop-on-latency=true', 'do-lost=true', '!',
        'rtph264depay', 'wait-for-keyframe=true', '!', 'h264parse', '!',
        'avdec_h264', 'max-threads=2', 'output-corrupt=false', '!',
        'queue', 'leaky=downstream', 'max-size-buffers=1', 'max-size-bytes=0',
        'max-size-time=0', '!', 'videoconvert', '!', 'videoscale', 'method=1',
        '!', f'video/x-raw,format=BGR,width={width},height={height},pixel-aspect-ratio=1/1',
        '!', 'queue', 'leaky=downstream', 'max-size-buffers=1',
        'max-size-bytes=0', 'max-size-time=0', '!', 'fdsink', 'fd=1',
        'sync=false', 'async=false',
    ]


class Camera:
    def __init__(self, name, port, width, height, jitter, payload=None):
        self.name, self.width, self.height = name, width, height
        self.command = decoder_command(port, width, height, jitter, payload)
        self.latest = None
        self.count = 0
        self.stop = threading.Event()
        self.process = None
        self.thread = threading.Thread(target=self.receive, daemon=True)

    def receive(self):
        while not self.stop.is_set():
            process = None
            try:
                process = subprocess.Popen(self.command, stdout=subprocess.PIPE,
                                           bufsize=0, start_new_session=True)
                self.process = process
                size = self.width * self.height * 3
                while not self.stop.is_set():
                    data = bytearray(size)
                    view = memoryview(data)
                    offset = 0
                    while offset < size and not self.stop.is_set():
                        n = process.stdout.readinto(view[offset:])
                        if not n:
                            raise EOFError('decoder output ended')
                        offset += n
                    if offset == size:
                        frame = np.frombuffer(data, np.uint8).reshape(self.height, self.width, 3)
                        self.latest = (frame, time.monotonic())
                        self.count += 1
            except Exception as exc:
                if not self.stop.is_set():
                    print(f'WARNING: {self.name}: {exc}; retrying decoder', flush=True)
            finally:
                if process is not None:
                    self.terminate(process)
                    if process.stdout:
                        process.stdout.close()
                self.process = None
            self.stop.wait(1)

    @staticmethod
    def terminate(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def close(self):
        self.stop.set()
        if self.process:
            self.terminate(self.process)
        self.thread.join(timeout=2)


def main():
    cv2.setNumThreads(1)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.set())
    cameras = [
        Camera('Main', int(os.getenv('MAIN_PORT', '17200')), 848, 480,
               int(os.getenv('MAIN_JITTER_MS', '15'))),
        Camera('Arm', int(os.getenv('ARM_VIEW_PORT', '17202')), 432, 240,
               int(os.getenv('ARM_VIEW_JITTER_MS', '15')), 97),
        Camera('Wrist', int(os.getenv('WRIST_PORT', '17201')), 432, 240,
               int(os.getenv('WRIST_JITTER_MS', '15')), 96),
    ]
    title = 'A2 Teleoperation - Main | Arm / Wrist'
    interval = 1 / max(1, float(os.getenv('DASHBOARD_FPS', '20')))
    stale = float(os.getenv('VIDEO_STALE_SEC', '0.75'))
    states = [None] * 3
    fps = [0.0] * 3
    counts = [0] * 3
    report_at = time.monotonic()
    canvas = np.zeros((480, 1280, 3), np.uint8)
    try:
        for camera in cameras:
            camera.thread.start()
        cv2.namedWindow(title, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
        cv2.resizeWindow(title, 1280, 480)
        while not stop.is_set():
            now = time.monotonic()
            canvas.fill(0)
            # Widths are multiples of four: GStreamer BGR row stride equals width*3.
            for i, (camera, (x, y)) in enumerate(zip(cameras, [(0, 0), (848, 0), (848, 240)])):
                latest = camera.latest
                live = latest is not None and now - latest[1] < stale
                if live:
                    canvas[y:y+camera.height, x:x+camera.width] = latest[0]
                if states[i] != live:
                    print(f'{"VIDEO_OK" if live else "WARNING VIDEO_STALE"}: {camera.name}', flush=True)
                    states[i] = live
                label = f'{camera.name} {fps[i]:.1f} fps' if live else f'{camera.name} NO FRESH FRAME'
                cv2.putText(canvas, label, (x+8, y+23), cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, (0, 255, 0) if live else (0, 180, 255), 1)
            if now - report_at >= 5:
                elapsed = now - report_at
                fps = [(cam.count - old) / elapsed for cam, old in zip(cameras, counts)]
                counts = [cam.count for cam in cameras]
                report_at = now
                print('VIDEO_FPS ' + ' '.join(f'{cam.name}={rate:.1f}' for cam, rate in zip(cameras, fps)), flush=True)
            cv2.imshow(title, canvas)
            if cv2.waitKey(1) & 0xff in (27, ord('q')):
                break
            try:
                if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                    break
            except cv2.error:
                pass
            stop.wait(max(0, interval - (time.monotonic() - now)))
    finally:
        for camera in cameras:
            camera.close()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
