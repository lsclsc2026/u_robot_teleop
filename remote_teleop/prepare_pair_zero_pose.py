#!/usr/bin/env python3
"""Safely move a locally connected SO-101 leader/follower pair to one neutral pose."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from lerobot.motors.feetech import OperatingMode

from so101_bus import JOINT_NAMES, assert_calibrated, make_bus


DEFAULT_LEADER_SERIAL = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B3D047743-if00"
DEFAULT_FOLLOWER_SERIAL = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B3D047726-if00"
DEFAULT_LEADER_CAL = "~/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/aloha_leader.json"
DEFAULT_FOLLOWER_CAL = "~/.cache/huggingface/lerobot/calibration/robots/so_follower/aloha_follower.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--leader-serial", default=DEFAULT_LEADER_SERIAL)
    parser.add_argument("--follower-serial", default=DEFAULT_FOLLOWER_SERIAL)
    parser.add_argument("--leader-calibration", default=DEFAULT_LEADER_CAL)
    parser.add_argument("--follower-calibration", default=DEFAULT_FOLLOWER_CAL)
    parser.add_argument("--body-speed-deg-s", type=float, default=15.0)
    parser.add_argument("--gripper-speed-pct-s", type=float, default=15.0)
    parser.add_argument("--hz", type=float, default=50.0)
    return parser.parse_args()


def check_path(path: str, label: str) -> None:
    resolved = Path(path).expanduser()
    if not resolved.exists():
        raise FileNotFoundError(f"{label} is missing: {resolved}")


def configure_for_slow_position_control(bus) -> None:
    bus.disable_torque(num_retry=5)
    bus.configure_motors()
    for motor in JOINT_NAMES:
        bus.write("Operating_Mode", motor, OperatingMode.POSITION.value, num_retry=5)
        bus.write("P_Coefficient", motor, 16, num_retry=5)
        bus.write("I_Coefficient", motor, 0, num_retry=5)
        bus.write("D_Coefficient", motor, 32, num_retry=5)


def read_positions(bus) -> dict[str, float]:
    values = bus.sync_read("Present_Position", num_retry=5)
    return {name: float(values[name]) for name in JOINT_NAMES}


def interpolate(start: dict[str, float], target: dict[str, float], fraction: float) -> dict[str, float]:
    return {name: start[name] + (target[name] - start[name]) * fraction for name in JOINT_NAMES}


def required_duration(start: dict[str, float], args: argparse.Namespace) -> float:
    body_delta = max(abs(start[name]) for name in JOINT_NAMES if name != "gripper")
    gripper_delta = abs(start["gripper"] - 50.0)
    return max(
        2.0,
        body_delta / args.body_speed_deg_s,
        gripper_delta / args.gripper_speed_pct_s,
    )


def main() -> int:
    args = parse_args()
    if os.environ.get("ARM_ZERO_MOVE") != "YES":
        raise SystemExit(
            "Refusing to move both arms. After clearing the area, prefix the command with ARM_ZERO_MOVE=YES."
        )
    if args.hz <= 0 or args.body_speed_deg_s <= 0 or args.gripper_speed_pct_s <= 0:
        raise ValueError("Speeds and hz must be positive")

    check_path(args.leader_serial, "leader serial")
    check_path(args.follower_serial, "follower serial")
    check_path(args.leader_calibration, "leader calibration")
    check_path(args.follower_calibration, "follower calibration")

    leader = make_bus(args.leader_serial, args.leader_calibration)
    follower = make_bus(args.follower_serial, args.follower_calibration)
    connected = []
    try:
        for label, bus in (("leader", leader), ("follower", follower)):
            bus.connect()
            connected.append(bus)
            assert_calibrated(bus)
            configure_for_slow_position_control(bus)
            print(f"{label} calibration JSON matches its motor EEPROM.")

        starts = {"leader": read_positions(leader), "follower": read_positions(follower)}
        target = {name: (50.0 if name == "gripper" else 0.0) for name in JOINT_NAMES}
        duration = max(required_duration(starts["leader"], args), required_duration(starts["follower"], args))

        print("\nCurrent calibrated positions:")
        for label in ("leader", "follower"):
            values = " ".join(f"{name}={starts[label][name]:+.1f}" for name in JOINT_NAMES)
            print(f"  {label}: {values}")
        print(f"\nNeutral target: body joints=0 deg, gripper=50%; planned duration={duration:.1f}s")
        print("This pose is computed from the EXISTING calibrations; it is a repeatable starting point,")
        print("not proof that the two physical coordinate frames are already aligned.")
        if input("Support both arms and type MOVE to start the slow motion: ").strip() != "MOVE":
            print("Cancelled before torque was enabled.")
            return 2

        leader.enable_torque(num_retry=5)
        follower.enable_torque(num_retry=5)
        period = 1.0 / args.hz
        step_count = max(1, int(duration * args.hz))
        for step in range(1, step_count + 1):
            started = time.monotonic()
            fraction = step / step_count
            leader.sync_write("Goal_Position", interpolate(starts["leader"], target, fraction), num_retry=2)
            follower.sync_write("Goal_Position", interpolate(starts["follower"], target, fraction), num_retry=2)
            remaining = period - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)

        time.sleep(0.5)
        print("Both arms reached the calibrated neutral target.")
        input("Hold both arms firmly, then press ENTER to disable torque...")
        leader.disable_torque(num_retry=5)
        follower.disable_torque(num_retry=5)
        print("Torque disabled. Manually make the two physical poses identical before calibration.")
        return 0
    finally:
        for bus in reversed(connected):
            if bus.is_connected:
                bus.disconnect(disable_torque=True)


if __name__ == "__main__":
    raise SystemExit(main())
