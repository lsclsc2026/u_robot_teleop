#!/usr/bin/env python3
"""Copy leader normalization ranges to the follower while preserving follower motor homing offsets."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from lerobot.motors import MotorCalibration

from so101_bus import JOINT_NAMES, load_calibration, make_bus


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--leader-calibration",
        default="~/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/aloha_leader.json",
    )
    parser.add_argument(
        "--follower-calibration",
        default="~/.cache/huggingface/lerobot/calibration/robots/so_follower/aloha_follower.json",
    )
    parser.add_argument(
        "--follower-serial",
        default="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B3D047726-if00",
    )
    parser.add_argument(
        "--export",
        default="~/feishu/a2pro/local_arm_test/remote_teleop/calibration_export/aloha_follower.json",
    )
    parser.add_argument("--restore", help="restore a previous follower calibration JSON instead of copying ranges")
    parser.add_argument("--apply", action="store_true", help="write the hybrid calibration to JSON and EEPROM")
    return parser.parse_args()


def save(path: Path, calibration: dict[str, MotorCalibration]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump({name: asdict(value) for name, value in calibration.items()}, file, indent=4)
        file.write("\n")
    temporary.replace(path)


def main() -> int:
    args = parse_args()
    leader_path = Path(args.leader_calibration).expanduser()
    follower_path = Path(args.follower_calibration).expanduser()
    follower_serial = Path(args.follower_serial).expanduser()
    export_path = Path(args.export).expanduser()
    leader = load_calibration(leader_path)
    follower = load_calibration(follower_path)

    hybrid = {
        name: MotorCalibration(
            id=follower[name].id,
            drive_mode=leader[name].drive_mode,
            homing_offset=follower[name].homing_offset,
            range_min=leader[name].range_min,
            range_max=leader[name].range_max,
        )
        for name in JOINT_NAMES
    }

    target = load_calibration(Path(args.restore).expanduser()) if args.restore else hybrid

    print("Follower calibration preview:")
    if args.restore:
        print(f"  restoring complete follower calibration from: {Path(args.restore).expanduser()}")
    else:
        print("  copied from leader: drive_mode, range_min, range_max")
        print("  preserved follower: id, homing_offset")
    print(f"{'joint':15} {'offset kept':>11} {'old follower range':>20} {'new leader range':>18}")
    for name in JOINT_NAMES:
        old = follower[name]
        new = target[name]
        print(
            f"{name:15} {new.homing_offset:11d} "
            f"{old.range_min:4d}..{old.range_max:<4d} "
            f"{new.range_min:4d}..{new.range_max:<4d}"
        )

    if not args.apply:
        print("\nPREVIEW ONLY: no JSON or motor EEPROM was changed.")
        print("Use --apply with FOLLOWER_RANGE_OVERRIDE=YES when physically ready.")
        return 0
    if os.environ.get("FOLLOWER_RANGE_OVERRIDE") != "YES":
        raise SystemExit("Refusing to apply. Prefix with FOLLOWER_RANGE_OVERRIDE=YES.")
    if not follower_serial.exists():
        raise FileNotFoundError(f"Follower serial is missing: {follower_serial}")
    if input("Support the follower and type APPLY to disable torque and write the test calibration: ").strip() != "APPLY":
        print("Cancelled before changing EEPROM or JSON.")
        return 2

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = follower_path.with_name(f"{follower_path.stem}.{timestamp}.before_leader_ranges.json")
    shutil.copy2(follower_path, backup_path)
    bus = make_bus(str(follower_serial), str(follower_path))
    bus.connect()
    changed = False
    try:
        bus.disable_torque(num_retry=5)
        for name, values in target.items():
            bus.write("Homing_Offset", name, values.homing_offset, normalize=False, num_retry=5)
            bus.write("Min_Position_Limit", name, values.range_min, normalize=False, num_retry=5)
            bus.write("Max_Position_Limit", name, values.range_max, normalize=False, num_retry=5)
        changed = True
        bus.calibration = target

        for name, values in target.items():
            actual = (
                int(bus.read("Homing_Offset", name, normalize=False, num_retry=5)),
                int(bus.read("Min_Position_Limit", name, normalize=False, num_retry=5)),
                int(bus.read("Max_Position_Limit", name, normalize=False, num_retry=5)),
            )
            expected = (values.homing_offset, values.range_min, values.range_max)
            if actual != expected:
                raise RuntimeError(f"EEPROM verification failed for {name}: {actual} != {expected}")

        save(follower_path, target)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(follower_path, export_path)
        changed = False
        print(f"Applied successfully. Backup: {backup_path}")
        print(f"Updated follower JSON: {follower_path}")
        print(f"Updated deployment JSON: {export_path}")
        print("Follower torque remains disabled. Test with a short, small-motion teleoperation run.")
        return 0
    except BaseException:
        if changed:
            print("Apply failed; attempting to restore the previous follower EEPROM...")
            for name, values in follower.items():
                bus.write("Homing_Offset", name, values.homing_offset, normalize=False, num_retry=5)
                bus.write("Min_Position_Limit", name, values.range_min, normalize=False, num_retry=5)
                bus.write("Max_Position_Limit", name, values.range_max, normalize=False, num_retry=5)
            bus.calibration = follower
            print("Previous follower EEPROM restored; original JSON was retained.")
        raise
    finally:
        if bus.is_connected:
            bus.disconnect(disable_torque=True)


if __name__ == "__main__":
    raise SystemExit(main())
