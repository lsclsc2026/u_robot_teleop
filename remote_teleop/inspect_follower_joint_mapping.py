#!/usr/bin/env python3
"""Read all follower encoders while torque is disabled; never send position goals."""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from so101_bus import JOINT_NAMES, make_bus


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--serial",
        default="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B3D047726-if00",
    )
    parser.add_argument(
        "--calibration",
        default="~/.cache/huggingface/lerobot/calibration/robots/so_follower/aloha_follower.json",
    )
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--hz", type=float, default=20.0)
    parser.add_argument("--threshold", type=int, default=8)
    parser.add_argument("--csv", default="~/arm_remote/logs/follower_joint_mapping.csv")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    csv_path = Path(args.csv).expanduser()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    bus = make_bus(args.serial, args.calibration)
    bus.connect()
    try:
        print("READ-ONLY JOINT IDENTIFICATION: no Goal_Position command will be sent.")
        input("Support the follower arm, then press ENTER to disable torque...")
        bus.disable_torque(num_retry=5)
        baseline = bus.sync_read("Present_Position", normalize=False, num_retry=5)
        previous = baseline.copy()
        print("Move ONLY the suspect physical joint slowly in both directions.")
        print("Changed encoder names will be printed; Ctrl+C stops early.")
        deadline = time.monotonic() + args.duration
        period = 1.0 / args.hz
        row_count = 0
        with csv_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["steady_ns", *JOINT_NAMES])
            while time.monotonic() < deadline:
                started = time.monotonic()
                values = bus.sync_read("Present_Position", normalize=False, num_retry=5)
                writer.writerow([time.monotonic_ns(), *(int(values[name]) for name in JOINT_NAMES)])
                row_count += 1
                changed = [
                    name
                    for name in JOINT_NAMES
                    if abs(int(values[name]) - int(previous[name])) >= args.threshold
                ]
                if changed:
                    details = " ".join(
                        f"{name}=raw:{int(values[name])} total_delta:{int(values[name])-int(baseline[name]):+d}"
                        for name in changed
                    )
                    print(f"changed: {details}")
                previous = values
                remaining = period - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(remaining)
        print(f"done: rows={row_count} CSV={csv_path}")
        return 0
    finally:
        if bus.is_connected:
            bus.disconnect(disable_torque=True)


if __name__ == "__main__":
    raise SystemExit(main())
