#!/usr/bin/env python3
"""Display a raw BGR dashboard stream in one normal resizable Qt window."""

from __future__ import annotations

import sys
import os

import cv2
import numpy as np


WIDTH = int(os.environ.get("DASHBOARD_WIDTH", "1280"))
HEIGHT = int(os.environ.get("DASHBOARD_HEIGHT", "480"))
FRAME_BYTES = WIDTH * HEIGHT * 3
TITLE = os.environ.get(
    "DASHBOARD_TITLE", "A2 Teleoperation Dashboard - Main | Arm / Wrist"
)
WINDOW_WIDTH = int(os.environ.get("DASHBOARD_WINDOW_WIDTH", "1280"))
WINDOW_HEIGHT = int(os.environ.get("DASHBOARD_WINDOW_HEIGHT", "480"))


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


def main() -> int:
    cv2.namedWindow(TITLE, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
    cv2.resizeWindow(TITLE, WINDOW_WIDTH, WINDOW_HEIGHT)
    try:
        while True:
            raw = read_exact(FRAME_BYTES)
            if raw is None:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(HEIGHT, WIDTH, 3)
            cv2.imshow(TITLE, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
            # Some WSLg/OpenCV Qt builds lose the internal window receiver
            # temporarily while resizing.  Querying WND_PROP_VISIBLE then
            # raises cv2.error and used to tear down all remote services.
            try:
                if cv2.getWindowProperty(TITLE, cv2.WND_PROP_VISIBLE) < 1:
                    break
            except cv2.error:
                pass
    finally:
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
