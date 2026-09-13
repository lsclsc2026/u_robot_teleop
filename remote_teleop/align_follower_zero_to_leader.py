#!/usr/bin/env python3
"""Align follower homing offsets to a leader while both arms share one physical pose."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from lerobot.motors import MotorCalibration

from so101_bus import JOINT_NAMES, assert_calibrated, load_calibration, make_bus


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--leader-serial",
        default="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B3D047743-if00",
    )
    parser.add_argument(
        "--follower-serial",
        default="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B3D047726-if00",
    )
    parser.add_argument(
        "--leader-calibration",
        default="~/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/aloha_leader.json",
    )
    parser.add_argument(
        "--follower-calibration",
        default="~/.cache/huggingface/lerobot/calibration/robots/so_follower/aloha_follower.json",
    )
    parser.add_argument(
        "--export",
        default="~/feishu/a2pro/local_arm_test/remote_teleop/calibration_export/aloha_follower.json",
    )
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--sample-hz", type=float, default=20.0)
    parser.add_argument("--max-correction-counts", type=int, default=1200)
    return parser.parse_args()


def save(path: Path, calibration: dict[str, MotorCalibration]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump({name: asdict(value) for name, value in calibration.items()}, file, indent=4)
        file.write("\n")
    temporary.replace(path)


def circular_delta(delta: int) -> int:
    return ((delta + 2048) % 4096) - 2048


def sample_raw(bus, count: int, hz: float) -> dict[str, int]:
    readings = {name: [] for name in JOINT_NAMES}
    period = 1.0 / hz
    for _ in range(count):
        started = time.monotonic()
        values = bus.sync_read("Present_Position", normalize=False, num_retry=5)
        for name in JOINT_NAMES:
            readings[name].append(int(values[name]))
        remaining = period - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)
    return {name: int(statistics.median(values)) for name, values in readings.items()}


def main() -> int:
    args = parse_args()
    if os.environ.get("PAIR_ZERO_ALIGN") != "YES":
        raise SystemExit("Refusing to alter follower homing offsets. Prefix with PAIR_ZERO_ALIGN=YES.")
    if args.samples < 5 or args.sample_hz <= 0:
        raise ValueError("samples must be >= 5 and sample-hz must be positive")

    leader_path = Path(args.leader_calibration).expanduser()
    follower_path = Path(args.follower_calibration).expanduser()
    export_path = Path(args.export).expanduser()
    leader_cal = load_calibration(leader_path)
    follower_cal = load_calibration(follower_path)
    for name in JOINT_NAMES:
        leader_range = (leader_cal[name].range_min, leader_cal[name].range_max)
        follower_range = (follower_cal[name].range_min, follower_cal[name].range_max)
        if leader_range != follower_range:
            raise RuntimeError(
                f"Ranges differ for {name}: leader={leader_range}, follower={follower_range}. "
                "Apply the shared-range calibration first."
            )

    leader = make_bus(args.leader_serial, str(leader_path))
    follower = make_bus(args.follower_serial, str(follower_path))
    connected = []
    follower_changed = False
    try:
        for bus in (leader, follower):
            bus.connect()
            connected.append(bus)
            assert_calibrated(bus)

        input("Support BOTH arms, then press ENTER to disable torque...")
        leader.disable_torque(num_retry=5)
        follower.disable_torque(num_retry=5)
        input(
            "Place both arms in the SAME physical pose relative to their own bases.\n"
            "Match regions 1 (wrist_flex), 2 (elbow_flex), wrist roll and gripper exactly.\n"
            "Keep them still, then press ENTER to sample..."
        )

        leader_raw = sample_raw(leader, args.samples, args.sample_hz)
        follower_raw = sample_raw(follower, args.samples, args.sample_hz)
        aligned = {}
        print(
            f"{'joint':15} {'leader raw':>10} {'follower raw':>12} "
            f"{'pose error':>10} {'degrees':>9} {'old offset':>11} {'new offset':>11}"
        )
        for name in JOINT_NAMES:
            pose_error = circular_delta(follower_raw[name] - leader_raw[name])
            old = follower_cal[name]
            # Feetech reports Present_Position = Actual_Position - Homing_Offset.
            # Recover the 0..4095 absolute encoder value first; otherwise an
            # offset crossing zero may appear outside the signed 11-bit range.
            actual_encoder = (follower_raw[name] + old.homing_offset) % 4096
            new_offset = actual_encoder - leader_raw[name]
            if new_offset > 2047:
                new_offset -= 4096
            elif new_offset < -2047:
                new_offset += 4096
            print(
                f"{name:15} {leader_raw[name]:10d} {follower_raw[name]:12d} "
                f"{pose_error:+10d} {pose_error * 360 / 4095:+9.2f} "
                f"{old.homing_offset:+11d} {new_offset:+11d}"
            )
            if abs(pose_error) > args.max_correction_counts:
                raise RuntimeError(
                    f"{name} pose error {pose_error} exceeds safety limit {args.max_correction_counts}; "
                    "the physical poses were probably not matched. No EEPROM value was changed."
                )
            if not -2047 <= new_offset <= 2047:
                raise RuntimeError(
                    f"{name} resulting homing offset {new_offset} is outside the STS3215 signed range. "
                    "No EEPROM value was changed; check that the two physical poses match."
                )
            aligned[name] = MotorCalibration(
                id=old.id,
                drive_mode=old.drive_mode,
                homing_offset=new_offset,
                range_min=old.range_min,
                range_max=old.range_max,
            )

        if input("Type APPLY_ZERO to write these follower-only offset corrections: ").strip() != "APPLY_ZERO":
            print("Cancelled after measurement; no EEPROM or JSON value was changed.")
            return 2

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = follower_path.with_name(f"{follower_path.stem}.{timestamp}.before_zero_alignment.json")
        shutil.copy2(follower_path, backup)
        for name, values in aligned.items():
            follower.write("Homing_Offset", name, values.homing_offset, normalize=False, num_retry=5)
        follower_changed = True
        follower.calibration = aligned
        for name, values in aligned.items():
            actual = int(follower.read("Homing_Offset", name, normalize=False, num_retry=5))
            if actual != values.homing_offset:
                raise RuntimeError(f"EEPROM verification failed for {name}: {actual} != {values.homing_offset}")

        save(follower_path, aligned)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(follower_path, export_path)
        follower_changed = False
        print(f"Follower zero alignment applied. Backup: {backup}")
        print(f"Updated follower calibration: {follower_path}")
        print(f"Updated deployment calibration: {export_path}")
        print("Both arms remain torque-disabled. Test with a short local teleoperation run.")
        return 0
    except BaseException:
        if follower_changed:
            print("Alignment failed; attempting to restore previous follower homing offsets...")
            for name, values in follower_cal.items():
                follower.write("Homing_Offset", name, values.homing_offset, normalize=False, num_retry=5)
            follower.calibration = follower_cal
            print("Previous follower homing offsets restored; original JSON retained.")
        raise
    finally:
        for bus in reversed(connected):
            if bus.is_connected:
                bus.disconnect(disable_torque=True)


if __name__ == "__main__":
    raise SystemExit(main())
