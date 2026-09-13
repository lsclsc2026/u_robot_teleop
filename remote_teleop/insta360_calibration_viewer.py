#!/usr/bin/env python3
"""Resizable X5 virtual-PTZ viewer; updates FFmpeg v360 and saves a preset."""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np


WIDTH = 1280
HEIGHT = 720
FRAME_BYTES = WIDTH * HEIGHT * 3
TITLE = "Insta360 X5 View Calibration"


class ZmqRequest:
    REQ = 3
    LINGER = 17
    RCVTIMEO = 27
    SNDTIMEO = 28

    def __init__(self, address: str) -> None:
        self.address = address.encode()
        self.lib = ctypes.CDLL("libzmq.so.5")
        self.lib.zmq_ctx_new.restype = ctypes.c_void_p
        self.lib.zmq_socket.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.lib.zmq_socket.restype = ctypes.c_void_p
        self.lib.zmq_connect.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self.lib.zmq_setsockopt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
        self.lib.zmq_send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        self.lib.zmq_recv.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        self.lib.zmq_close.argtypes = [ctypes.c_void_p]
        self.lib.zmq_ctx_term.argtypes = [ctypes.c_void_p]
        self.ctx = self.lib.zmq_ctx_new()
        self.sock: int | None = None
        self._open()

    def _open(self) -> None:
        self.sock = self.lib.zmq_socket(self.ctx, self.REQ)
        timeout = ctypes.c_int(150)
        linger = ctypes.c_int(0)
        self.lib.zmq_setsockopt(self.sock, self.RCVTIMEO, ctypes.byref(timeout), ctypes.sizeof(timeout))
        self.lib.zmq_setsockopt(self.sock, self.SNDTIMEO, ctypes.byref(timeout), ctypes.sizeof(timeout))
        self.lib.zmq_setsockopt(self.sock, self.LINGER, ctypes.byref(linger), ctypes.sizeof(linger))
        if self.lib.zmq_connect(self.sock, self.address) != 0:
            raise RuntimeError(f"Cannot connect ZMQ: {self.address.decode()}")

    def _reopen(self) -> None:
        if self.sock:
            self.lib.zmq_close(self.sock)
        self._open()

    def request(self, command: str) -> str:
        raw = command.encode()
        if self.lib.zmq_send(self.sock, ctypes.c_char_p(raw), len(raw), 0) < 0:
            self._reopen()
            raise RuntimeError("ZMQ send timeout")
        buf = ctypes.create_string_buffer(1024)
        size = self.lib.zmq_recv(self.sock, buf, len(buf), 0)
        if size < 0:
            self._reopen()
            raise RuntimeError("ZMQ receive timeout")
        reply = buf.raw[:size].decode(errors="replace")
        if not reply.startswith("0 "):
            raise RuntimeError(reply)
        return reply

    def close(self) -> None:
        if self.sock:
            self.lib.zmq_close(self.sock)
            self.sock = None
        if self.ctx:
            self.lib.zmq_ctx_term(self.ctx)
            self.ctx = None


def read_exact(size: int) -> bytes | None:
    data = bytearray(size)
    view = memoryview(data)
    offset = 0
    while offset < size:
        count = sys.stdin.buffer.readinto(view[offset:])
        if not count:
            return None
        offset += count
    return bytes(data)


def vertical_fov(horizontal_fov: float) -> float:
    radians = math.radians(horizontal_fov)
    return math.degrees(2 * math.atan(math.tan(radians / 2) * HEIGHT / WIDTH))


def load_preset(path: Path) -> dict[str, float]:
    defaults = {"yaw": 0.0, "pitch": 0.0, "roll": 0.0, "h_fov": 100.0}
    if path.exists():
        defaults.update(json.loads(path.read_text(encoding="utf-8")))
    return defaults


def current_values() -> dict[str, float]:
    return {
        "yaw": float(cv2.getTrackbarPos("Yaw", TITLE) - 180),
        "pitch": float(cv2.getTrackbarPos("Pitch", TITLE) - 90),
        "roll": float(cv2.getTrackbarPos("Roll", TITLE) - 180),
        "h_fov": float(cv2.getTrackbarPos("FOV", TITLE) + 30),
    }


def apply_values(client: ZmqRequest, values: dict[str, float]) -> None:
    commands = [
        ("yaw", values["yaw"]),
        ("pitch", values["pitch"]),
        ("roll", values["roll"]),
        ("h_fov", values["h_fov"]),
        ("v_fov", vertical_fov(values["h_fov"])),
    ]
    for name, value in commands:
        client.request(f"v360@view {name} {value:.4f}")


def save_preset(path: Path, values: dict[str, float]) -> None:
    output = dict(values)
    output.update({"output_width": WIDTH, "output_height": HEIGHT})
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control", default="tcp://172.18.20.152:5555")
    parser.add_argument("--preset", type=Path, required=True)
    args = parser.parse_args()

    preset = load_preset(args.preset)
    client = ZmqRequest(args.control)
    cv2.namedWindow(TITLE, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
    cv2.resizeWindow(TITLE, 1280, 800)
    cv2.createTrackbar("Yaw", TITLE, round(preset["yaw"]) + 180, 360, lambda _: None)
    cv2.createTrackbar("Pitch", TITLE, round(preset["pitch"]) + 90, 180, lambda _: None)
    cv2.createTrackbar("Roll", TITLE, round(preset["roll"]) + 180, 360, lambda _: None)
    cv2.createTrackbar("FOV", TITLE, round(preset["h_fov"]) - 30, 120, lambda _: None)

    last_values: dict[str, float] | None = None
    status = "Move sliders; press S to save, R to reset, Q/Esc to exit"
    try:
        while True:
            raw = read_exact(FRAME_BYTES)
            if raw is None:
                break
            values = current_values()
            if values != last_values:
                try:
                    apply_values(client, values)
                    status = "Live view updated; press S to save preset"
                    last_values = values.copy()
                except RuntimeError as exc:
                    status = f"Control error: {exc}"

            frame = np.frombuffer(raw, dtype=np.uint8).reshape(HEIGHT, WIDTH, 3).copy()
            text = (
                f"yaw={values['yaw']:+.0f}  pitch={values['pitch']:+.0f}  "
                f"roll={values['roll']:+.0f}  FOV={values['h_fov']:.0f}"
            )
            cv2.rectangle(frame, (8, 8), (900, 72), (0, 0, 0), -1)
            cv2.putText(frame, text, (20, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(frame, status, (20, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
            cv2.imshow(TITLE, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q"), ord("Q")):
                break
            if key in (ord("s"), ord("S")):
                save_preset(args.preset, values)
                status = f"SAVED: {args.preset}"
                print(status, flush=True)
            if key in (ord("r"), ord("R")):
                cv2.setTrackbarPos("Yaw", TITLE, 180)
                cv2.setTrackbarPos("Pitch", TITLE, 90)
                cv2.setTrackbarPos("Roll", TITLE, 180)
                cv2.setTrackbarPos("FOV", TITLE, 70)
            if cv2.getWindowProperty(TITLE, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        client.close()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
