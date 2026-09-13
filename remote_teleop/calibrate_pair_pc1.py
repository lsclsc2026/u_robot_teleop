#!/usr/bin/env python3
"""Calibrate a locally connected SO-101 leader/follower pair and export the follower JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from lerobot.motors import Motor, MotorCalibration, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus, OperatingMode


JOINT_NAMES = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)
SCANNED_JOINTS = tuple(name for name in JOINT_NAMES if name != "wrist_roll")


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
        "--export-dir",
        default="~/feishu/a2pro/local_arm_test/remote_teleop/calibration_export",
    )
    parser.add_argument("--min-span", type=int, default=100)
    return parser.parse_args()


def load_calibration(path: Path) -> dict[str, MotorCalibration]:
    with path.open(encoding="utf-8") as file:
        raw = json.load(file)
    if set(raw) != set(JOINT_NAMES):
        raise ValueError(f"Unexpected calibration joints in {path}: {sorted(raw)}")
    return {name: MotorCalibration(**raw[name]) for name in JOINT_NAMES}


def make_raw_bus(serial: Path, calibration: dict[str, MotorCalibration]) -> FeetechMotorsBus:
    motors = {
        name: Motor(
            index + 1,
            "sts3215",
            MotorNormMode.RANGE_0_100 if name == "gripper" else MotorNormMode.DEGREES,
        )
        for index, name in enumerate(JOINT_NAMES)
    }
    return FeetechMotorsBus(port=str(serial), motors=motors, calibration=calibration)


def write_motor_calibration(
    bus: FeetechMotorsBus, calibration: dict[str, MotorCalibration]
) -> None:
    for motor, values in calibration.items():
        bus.write("Homing_Offset", motor, values.homing_offset, normalize=False, num_retry=5)
        bus.write("Min_Position_Limit", motor, values.range_min, normalize=False, num_retry=5)
        bus.write("Max_Position_Limit", motor, values.range_max, normalize=False, num_retry=5)
    bus.calibration = calibration


def save_calibration(path: Path, calibration: dict[str, MotorCalibration]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump({name: asdict(values) for name, values in calibration.items()}, file, indent=4)
        file.write("\n")
    temporary.replace(path)


def verify_eeprom(bus: FeetechMotorsBus, expected: dict[str, MotorCalibration]) -> None:
    for name, values in expected.items():
        actual = {
            "homing_offset": int(bus.read("Homing_Offset", name, normalize=False, num_retry=5)),
            "range_min": int(bus.read("Min_Position_Limit", name, normalize=False, num_retry=5)),
            "range_max": int(bus.read("Max_Position_Limit", name, normalize=False, num_retry=5)),
        }
        wanted = {
            "homing_offset": values.homing_offset,
            "range_min": values.range_min,
            "range_max": values.range_max,
        }
        if actual != wanted:
            raise RuntimeError(f"EEPROM verification failed for {name}: actual={actual}, expected={wanted}")


def calibrate_one(
    role: str,
    serial: Path,
    calibration_path: Path,
    min_span: int,
) -> dict[str, MotorCalibration]:
    if not serial.exists():
        raise FileNotFoundError(f"{role} serial is missing: {serial}")
    if not calibration_path.exists():
        raise FileNotFoundError(f"{role} calibration is missing: {calibration_path}")

    old_calibration = load_calibration(calibration_path)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = calibration_path.with_name(f"{calibration_path.stem}.{timestamp}.pair_backup.json")
    shutil.copy2(calibration_path, backup)
    print(f"\n{role}: old calibration backed up to {backup}")
    if input(f"Support the {role} arm and type CALIBRATE to continue: ").strip() != "CALIBRATE":
        raise RuntimeError(f"{role} calibration cancelled")

    bus = make_raw_bus(serial, old_calibration)
    calibration_changed = False
    bus.connect()
    try:
        bus.disable_torque(num_retry=5)
        for motor in JOINT_NAMES:
            bus.write("Operating_Mode", motor, OperatingMode.POSITION.value, num_retry=5)

        input(
            f"Place the {role} in the SAME marked middle pose used by the other arm.\n"
            "Make the gripper opening plane point in the same direction, then press ENTER..."
        )

        for motor in JOINT_NAMES:
            bus.write("Homing_Offset", motor, 0, normalize=False, num_retry=5)
            bus.write("Min_Position_Limit", motor, 0, normalize=False, num_retry=5)
            bus.write("Max_Position_Limit", motor, 4095, normalize=False, num_retry=5)
        calibration_changed = True

        actual_positions = bus.sync_read(
            "Present_Position", list(JOINT_NAMES), normalize=False, num_retry=5
        )
        homing_offsets = bus._get_half_turn_homings(actual_positions)
        for motor, offset in homing_offsets.items():
            bus.write("Homing_Offset", motor, offset, normalize=False, num_retry=5)

        print(
            f"Move ONLY the {role} through the complete safe ranges of shoulder_pan, shoulder_lift, "
            "elbow_flex, wrist_flex and gripper.\n"
            "wrist_roll is referenced by the marked middle pose and uses its full encoder range.\n"
            "Press ENTER only when all five displayed ranges are complete."
        )
        range_mins, range_maxes = bus.record_ranges_of_motion(list(SCANNED_JOINTS))
        range_mins["wrist_roll"] = 0
        range_maxes["wrist_roll"] = 4095

        new_calibration = {
            name: MotorCalibration(
                id=index + 1,
                drive_mode=0,
                homing_offset=int(homing_offsets[name]),
                range_min=int(range_mins[name]),
                range_max=int(range_maxes[name]),
            )
            for index, name in enumerate(JOINT_NAMES)
        }
        print(f"\n{role} recorded ranges:")
        for name, values in new_calibration.items():
            span = values.range_max - values.range_min
            print(f"  {name:<15} min={values.range_min:4d} max={values.range_max:4d} span={span:4d}")
            if name in SCANNED_JOINTS and span < min_span:
                raise ValueError(f"{role} {name} span {span} is below required minimum {min_span}")

        write_motor_calibration(bus, new_calibration)
        verify_eeprom(bus, new_calibration)
        save_calibration(calibration_path, new_calibration)
        calibration_changed = False
        print(f"{role} calibration saved and EEPROM verified: {calibration_path}")
        return new_calibration
    except BaseException:
        if calibration_changed:
            print(f"{role} calibration failed; attempting to restore its previous EEPROM...")
            try:
                write_motor_calibration(bus, old_calibration)
                verify_eeprom(bus, old_calibration)
                print(f"{role} previous EEPROM calibration restored.")
            except Exception as restore_error:
                print(f"WARNING: {role} EEPROM restore failed: {restore_error}")
                print("Do not teleoperate this arm until EEPROM and JSON are reconciled.")
        raise
    finally:
        if bus.is_connected:
            bus.disconnect(disable_torque=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    leader_serial = Path(args.leader_serial).expanduser()
    follower_serial = Path(args.follower_serial).expanduser()
    leader_path = Path(args.leader_calibration).expanduser()
    follower_path = Path(args.follower_calibration).expanduser()
    export_dir = Path(args.export_dir).expanduser()

    print("PAIR CALIBRATION: both arms must use the same marked physical middle pose.")
    print("Calibration is separate: leader and follower homing offsets are never copied between arms.")
    calibrate_one("leader", leader_serial, leader_path, args.min_span)
    input("Return both arms to the SAME marked middle pose, support the follower, then press ENTER...")
    calibrate_one("follower", follower_serial, follower_path, args.min_span)

    export_dir.mkdir(parents=True, exist_ok=True)
    exported_follower = export_dir / "aloha_follower.json"
    shutil.copy2(follower_path, exported_follower)
    checksum = sha256(exported_follower)
    manifest = export_dir / "README.txt"
    manifest.write_text(
        "SO-101 follower calibration generated on PC1.\n"
        f"source_serial={follower_serial}\n"
        f"sha256={checksum}\n"
        "Copy this JSON to the Unitree path:\n"
        "/home/unitree/.cache/huggingface/lerobot/calibration/robots/so_follower/aloha_follower.json\n",
        encoding="utf-8",
    )
    print("\nPair calibration completed.")
    print(f"Follower deployment file: {exported_follower}")
    print(f"SHA256: {checksum}")
    print("The follower EEPROM now contains the same calibration; mount it on the dog and copy this JSON only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
