#!/usr/bin/env python3
"""Interactively calibrate the SO-101 follower attached to the Unitree PC."""

from __future__ import annotations

import argparse
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
    return parser.parse_args()


def load_calibration(path: Path) -> dict[str, MotorCalibration]:
    with path.open(encoding="utf-8") as file:
        raw = json.load(file)
    if set(raw) != set(JOINT_NAMES):
        raise ValueError(f"Unexpected calibration joints: {sorted(raw)}")
    return {name: MotorCalibration(**raw[name]) for name in JOINT_NAMES}


def write_motor_calibration(
    bus: FeetechMotorsBus, calibration: dict[str, MotorCalibration]
) -> None:
    for motor, values in calibration.items():
        bus.write("Homing_Offset", motor, values.homing_offset, num_retry=5)
        bus.write("Min_Position_Limit", motor, values.range_min, num_retry=5)
        bus.write("Max_Position_Limit", motor, values.range_max, num_retry=5)
    bus.calibration = calibration


def save_calibration(path: Path, calibration: dict[str, MotorCalibration]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump({name: asdict(values) for name, values in calibration.items()}, file, indent=4)
        file.write("\n")
    temporary.replace(path)


def main() -> int:
    args = parse_args()
    serial = Path(args.serial).expanduser()
    calibration_path = Path(args.calibration).expanduser()
    if not serial.exists():
        raise FileNotFoundError(f"Follower serial is missing: {serial}")
    if not calibration_path.exists():
        raise FileNotFoundError(f"Existing follower calibration is missing: {calibration_path}")

    old_calibration = load_calibration(calibration_path)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = calibration_path.with_name(f"{calibration_path.stem}.{timestamp}.bak.json")
    shutil.copy2(calibration_path, backup_path)
    print(f"Old follower calibration backed up to: {backup_path}")
    print("WARNING: follower torque will be disabled; support the arm before continuing.")

    motors = {
        name: Motor(
            index + 1,
            "sts3215",
            MotorNormMode.RANGE_0_100 if name == "gripper" else MotorNormMode.DEGREES,
        )
        for index, name in enumerate(JOINT_NAMES)
    }
    bus = FeetechMotorsBus(port=str(serial), motors=motors, calibration=old_calibration)
    calibration_changed = False
    bus.connect()
    try:
        input("Support the follower arm, then press ENTER to disable torque...")
        bus.disable_torque(num_retry=5)
        for motor in JOINT_NAMES:
            bus.write("Operating_Mode", motor, OperatingMode.POSITION.value, num_retry=5)

        input("Move every follower joint to the middle of its physical range, then press ENTER...")

        # Reset the EEPROM to raw full-range values with retries, then centre all
        # encoders around half a turn. Keep the JSON untouched until the entire
        # interactive scan has completed successfully.
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

        scanned_joints = [name for name in JOINT_NAMES if name != "wrist_roll"]
        print(
            "Move shoulder_pan, shoulder_lift, elbow_flex, wrist_flex and gripper "
            "through their complete safe physical ranges.\n"
            "wrist_roll is intentionally excluded. Press ENTER only after all five are complete."
        )
        range_mins, range_maxes = bus.record_ranges_of_motion(scanned_joints)
        range_mins["wrist_roll"] = 0
        range_maxes["wrist_roll"] = 4095

        new_calibration = {
            name: MotorCalibration(
                id=motors[name].id,
                drive_mode=0,
                homing_offset=int(homing_offsets[name]),
                range_min=int(range_mins[name]),
                range_max=int(range_maxes[name]),
            )
            for name in JOINT_NAMES
        }
        print("Recorded follower ranges:")
        for name, values in new_calibration.items():
            print(
                f"  {name:<15} min={values.range_min:4d} "
                f"max={values.range_max:4d} span={values.range_max - values.range_min:4d}"
            )

        write_motor_calibration(bus, new_calibration)
        save_calibration(calibration_path, new_calibration)
        calibration_changed = False
        print(f"Follower calibration saved to: {calibration_path}")
        print("Calibration completed successfully. Keep the follower supported after disconnect.")
        return 0
    except BaseException:
        if calibration_changed:
            print("Calibration did not complete; attempting to restore the previous follower EEPROM...")
            try:
                write_motor_calibration(bus, old_calibration)
                print("Previous follower EEPROM calibration restored.")
            except Exception as restore_error:
                print(f"WARNING: EEPROM restore failed: {restore_error}")
                print("Do not start teleoperation until EEPROM and the JSON are reconciled.")
        raise
    finally:
        if bus.is_connected:
            bus.disconnect(disable_torque=True)


if __name__ == "__main__":
    raise SystemExit(main())
