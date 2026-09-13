#!/usr/bin/env python3
"""Small LeRobot motor-bus adapter used by the split-machine teleop tools."""

from __future__ import annotations

import json
from pathlib import Path

from lerobot.motors import Motor, MotorCalibration, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus, OperatingMode

from arm_udp_protocol import JOINT_NAMES


def load_calibration(path: str | Path) -> dict[str, MotorCalibration]:
    with Path(path).expanduser().open(encoding="utf-8") as file:
        raw = json.load(file)
    if set(raw) != set(JOINT_NAMES):
        raise ValueError(f"calibration joints do not match: {sorted(raw)}")
    return {name: MotorCalibration(**raw[name]) for name in JOINT_NAMES}


def make_bus(port: str, calibration_path: str | Path) -> FeetechMotorsBus:
    calibration = load_calibration(calibration_path)
    motors = {
        name: Motor(
            index + 1,
            "sts3215",
            MotorNormMode.RANGE_0_100 if name == "gripper" else MotorNormMode.DEGREES,
        )
        for index, name in enumerate(JOINT_NAMES)
    }
    return FeetechMotorsBus(port=port, motors=motors, calibration=calibration)


def assert_calibrated(bus: FeetechMotorsBus) -> None:
    if not bus.is_calibrated:
        raise RuntimeError(
            "Motor EEPROM calibration does not match the supplied calibration JSON. "
            "Refusing to write calibration automatically."
        )


def configure_leader(bus: FeetechMotorsBus) -> None:
    bus.disable_torque(num_retry=5)
    bus.configure_motors()
    for motor in JOINT_NAMES:
        bus.write("Operating_Mode", motor, OperatingMode.POSITION.value)


def configure_follower(bus: FeetechMotorsBus) -> None:
    with bus.torque_disabled(num_retry=5):
        bus.configure_motors()
        for motor in JOINT_NAMES:
            bus.write("Operating_Mode", motor, OperatingMode.POSITION.value)
            bus.write("P_Coefficient", motor, 16)
            bus.write("I_Coefficient", motor, 0)
            bus.write("D_Coefficient", motor, 32)
            if motor == "gripper":
                bus.write("Max_Torque_Limit", motor, 500)
                bus.write("Protection_Current", motor, 250)
                bus.write("Overload_Torque", motor, 25)


def read_positions(bus: FeetechMotorsBus) -> tuple[float, float, float, float, float, float]:
    values = bus.sync_read("Present_Position", num_retry=4)
    return tuple(float(values[name]) for name in JOINT_NAMES)  # type: ignore[return-value]


def send_positions(
    bus: FeetechMotorsBus,
    positions: tuple[float, ...],
    max_relative_target: float | None,
) -> tuple[
    tuple[float, float, float, float, float, float],
    tuple[float, float, float, float, float, float],
]:
    goals = dict(zip(JOINT_NAMES, positions, strict=True))
    if max_relative_target is not None:
        present = bus.sync_read("Present_Position", num_retry=4)
        limit = float(max_relative_target)
        goals = {
            name: max(float(present[name]) - limit, min(float(present[name]) + limit, float(goal)))
            for name, goal in goals.items()
        }
    else:
        present = bus.sync_read("Present_Position", num_retry=4)
    bus.sync_write("Goal_Position", goals, num_retry=2)
    applied = tuple(float(goals[name]) for name in JOINT_NAMES)
    actual = tuple(float(present[name]) for name in JOINT_NAMES)
    return applied, actual  # type: ignore[return-value]
