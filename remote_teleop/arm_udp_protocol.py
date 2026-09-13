#!/usr/bin/env python3
"""Fixed-size UDP protocol shared by the SO-101 leader and follower."""

from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass


JOINT_NAMES = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)

VERSION = 2
ACTION_MAGIC = b"A2AR"
ACK_MAGIC = b"A2AK"
FLAG_ENABLED = 0x01

ACK_DRY_RUN = 0
ACK_ROBOT_SENT = 1
ACK_SUPERSEDED = 2
ACK_STARTUP_REJECTED = 3
ACK_ROBOT_ERROR = 4
ACK_STARTUP_SYNCING = 5

ACK_STATUS_NAMES = {
    ACK_DRY_RUN: "dry_run",
    ACK_ROBOT_SENT: "robot_sent",
    ACK_SUPERSEDED: "superseded",
    ACK_STARTUP_REJECTED: "startup_rejected",
    ACK_ROBOT_ERROR: "robot_error",
    ACK_STARTUP_SYNCING: "startup_syncing",
}

_ACTION_BODY = struct.Struct("!4sBBIQ6f")
_ACK_BODY = struct.Struct("!4sBBIQQ12f")
_CRC = struct.Struct("!I")
ACTION_SIZE = _ACTION_BODY.size + _CRC.size
ACK_SIZE = _ACK_BODY.size + _CRC.size


@dataclass(frozen=True)
class ActionPacket:
    flags: int
    seq: int
    send_ns: int
    positions: tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class AckPacket:
    status: int
    seq: int
    receive_ns: int
    done_ns: int
    applied_positions: tuple[float, float, float, float, float, float]
    present_positions: tuple[float, float, float, float, float, float]


def _with_crc(body: bytes) -> bytes:
    return body + _CRC.pack(zlib.crc32(body) & 0xFFFFFFFF)


def _checked_body(data: bytes, expected_size: int) -> bytes:
    if len(data) != expected_size:
        raise ValueError(f"wrong packet size: {len(data)} != {expected_size}")
    body, crc_bytes = data[:-_CRC.size], data[-_CRC.size :]
    (received_crc,) = _CRC.unpack(crc_bytes)
    actual_crc = zlib.crc32(body) & 0xFFFFFFFF
    if received_crc != actual_crc:
        raise ValueError("CRC mismatch")
    return body


def encode_action(seq: int, send_ns: int, positions: tuple[float, ...], *, enabled: bool = True) -> bytes:
    if len(positions) != len(JOINT_NAMES):
        raise ValueError(f"expected {len(JOINT_NAMES)} positions")
    values = tuple(float(value) for value in positions)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("joint position is not finite")
    flags = FLAG_ENABLED if enabled else 0
    body = _ACTION_BODY.pack(ACTION_MAGIC, VERSION, flags, seq & 0xFFFFFFFF, send_ns, *values)
    return _with_crc(body)


def decode_action(data: bytes) -> ActionPacket:
    body = _checked_body(data, ACTION_SIZE)
    magic, version, flags, seq, send_ns, *positions = _ACTION_BODY.unpack(body)
    if magic != ACTION_MAGIC or version != VERSION:
        raise ValueError("unsupported action packet")
    if not all(math.isfinite(value) for value in positions):
        raise ValueError("joint position is not finite")
    return ActionPacket(flags, seq, send_ns, tuple(positions))  # type: ignore[arg-type]


def encode_ack(
    status: int,
    seq: int,
    receive_ns: int,
    done_ns: int,
    applied_positions: tuple[float, ...] | None = None,
    present_positions: tuple[float, ...] | None = None,
) -> bytes:
    missing = (math.nan,) * len(JOINT_NAMES)
    applied = missing if applied_positions is None else tuple(float(value) for value in applied_positions)
    present = missing if present_positions is None else tuple(float(value) for value in present_positions)
    if len(applied) != len(JOINT_NAMES) or len(present) != len(JOINT_NAMES):
        raise ValueError("ACK joint array has the wrong length")
    body = _ACK_BODY.pack(
        ACK_MAGIC, VERSION, status, seq & 0xFFFFFFFF, receive_ns, done_ns, *applied, *present
    )
    return _with_crc(body)


def decode_ack(data: bytes) -> AckPacket:
    body = _checked_body(data, ACK_SIZE)
    unpacked = _ACK_BODY.unpack(body)
    magic, version, status, seq, receive_ns, done_ns, *positions = unpacked
    if magic != ACK_MAGIC or version != VERSION:
        raise ValueError("unsupported ACK packet")
    applied = tuple(positions[: len(JOINT_NAMES)])
    present = tuple(positions[len(JOINT_NAMES) :])
    return AckPacket(status, seq, receive_ns, done_ns, applied, present)  # type: ignore[arg-type]
