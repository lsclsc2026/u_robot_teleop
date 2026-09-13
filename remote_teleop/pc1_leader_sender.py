#!/usr/bin/env python3
"""Read an SO-101 leader on PC1 and stream calibrated joint targets over UDP."""

from __future__ import annotations

import argparse
import csv
import math
import select
import socket
import time
from pathlib import Path

from arm_udp_protocol import ACK_STATUS_NAMES, JOINT_NAMES, decode_ack, encode_action
from so101_bus import assert_calibrated, configure_leader, make_bus, read_positions


DEFAULT_PORT = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B3D047743-if00"
DEFAULT_CALIBRATION = "~/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/aloha_leader.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="172.18.20.152", help="Unitree WiFi IPv4")
    parser.add_argument("--port", type=int, default=39101, help="UDP control port")
    parser.add_argument("--serial", default=DEFAULT_PORT)
    parser.add_argument("--calibration", default=DEFAULT_CALIBRATION)
    parser.add_argument("--fps", type=float, default=100.0)
    parser.add_argument("--duration", type=float, default=300.0)
    parser.add_argument("--csv", default="remote_arm_sender.csv")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.fps <= 200:
        raise SystemExit("--fps must be between 1 and 200")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1_048_576)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1_048_576)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0xB8)
    sock.connect((args.target, args.port))
    sock.setblocking(False)

    bus = make_bus(args.serial, args.calibration)
    rows: dict[int, dict[str, object]] = {}
    pending: dict[int, int] = {}
    seq = 0
    acked = 0
    invalid_acks = 0
    last_ack_status = "waiting"
    last_applied_error: float | None = None
    last_present_error: float | None = None
    start = time.monotonic()
    next_tick = start
    next_report = start

    def collect_acks(wait_s: float = 0.0) -> None:
        nonlocal acked, invalid_acks, last_ack_status, last_applied_error, last_present_error
        if not select.select([sock], [], [], max(wait_s, 0.0))[0]:
            return
        while True:
            try:
                ack = decode_ack(sock.recv(256))
            except BlockingIOError:
                return
            except ValueError:
                invalid_acks += 1
            else:
                ack_arrival_ns = time.monotonic_ns()
                original_send_ns = pending.pop(ack.seq, None)
                if original_send_ns is not None and ack.seq in rows:
                    acked += 1
                    row = rows[ack.seq]
                    row["ack_steady_ns"] = ack_arrival_ns
                    row["rtt_ms"] = (ack_arrival_ns - original_send_ns) / 1_000_000
                    row["ack_status"] = ACK_STATUS_NAMES.get(ack.status, f"unknown_{ack.status}")
                    last_ack_status = str(row["ack_status"])
                    row["receiver_processing_us"] = (ack.done_ns - ack.receive_ns) / 1_000
                    if all(math.isfinite(value) for value in ack.applied_positions):
                        for name, value in zip(JOINT_NAMES, ack.applied_positions, strict=True):
                            row[f"applied_{name}"] = value
                        row["target_applied_max_abs_error"] = max(
                            abs(float(row[name]) - value)
                            for name, value in zip(JOINT_NAMES, ack.applied_positions, strict=True)
                        )
                        last_applied_error = float(row["target_applied_max_abs_error"])
                    if all(math.isfinite(value) for value in ack.present_positions):
                        for name, value in zip(JOINT_NAMES, ack.present_positions, strict=True):
                            row[f"present_{name}"] = value
                        row["target_present_max_abs_error"] = max(
                            abs(float(row[name]) - value)
                            for name, value in zip(JOINT_NAMES, ack.present_positions, strict=True)
                        )
                        last_present_error = float(row["target_present_max_abs_error"])
            if not select.select([sock], [], [], 0)[0]:
                return

    print(f"PC1 SO-101 leader -> udp://{args.target}:{args.port}")
    print(f"serial: {args.serial}")
    print("This process reads the leader only; it does not have access to the follower motors.")

    try:
        bus.connect()
        assert_calibrated(bus)
        configure_leader(bus)

        while time.monotonic() - start < args.duration:
            loop_start_ns = time.monotonic_ns()
            positions = read_positions(bus)
            read_done_ns = time.monotonic_ns()
            seq += 1
            packet = encode_action(seq, read_done_ns, positions)
            sock.send(packet)
            send_ns = time.monotonic_ns()
            pending[seq] = send_ns
            rows[seq] = {
                "seq": seq,
                "host_unix_ns": time.time_ns(),
                "leader_read_us": (read_done_ns - loop_start_ns) / 1_000,
                "send_steady_ns": send_ns,
                "ack_steady_ns": "",
                "rtt_ms": "",
                "ack_status": "",
                "receiver_processing_us": "",
                "target_applied_max_abs_error": "",
                "target_present_max_abs_error": "",
                **{name: value for name, value in zip(JOINT_NAMES, positions, strict=True)},
                **{f"applied_{name}": "" for name in JOINT_NAMES},
                **{f"present_{name}": "" for name in JOINT_NAMES},
            }

            collect_acks()

            now = time.monotonic()
            if now >= next_report:
                pos = ", ".join(f"{name}={value:+.1f}" for name, value in zip(JOINT_NAMES, positions))
                error_parts = []
                if last_applied_error is not None:
                    error_parts.append(f"applied_err={last_applied_error:.2f}")
                if last_present_error is not None:
                    error_parts.append(f"present_err={last_present_error:.2f}")
                errors = " ".join(error_parts) if error_parts else "feedback_err=n/a"
                print(
                    f"sent={seq} acked={acked} pending={len(pending)} "
                    f"status={last_ack_status} {errors} {pos}"
                )
                next_report = now + 1.0

            next_tick += 1.0 / args.fps
            sleep_s = next_tick - time.monotonic()
            if sleep_s > 0:
                while True:
                    remaining_s = next_tick - time.monotonic()
                    if remaining_s <= 0:
                        break
                    collect_acks(remaining_s)
            elif sleep_s < -0.5:
                next_tick = time.monotonic()
    except KeyboardInterrupt:
        print("Interrupted.")
    except ConnectionRefusedError:
        print("Receiver became unavailable; stopping sender and preserving the CSV.")
    finally:
        if bus.is_connected:
            bus.disconnect(disable_torque=False)
        deadline = time.monotonic() + 0.3
        while pending and time.monotonic() < deadline:
            try:
                collect_acks(0.02)
            except ConnectionRefusedError:
                break
        sock.close()

        csv_path = Path(args.csv).expanduser()
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "seq", "host_unix_ns", "leader_read_us", "send_steady_ns", "ack_steady_ns",
            "rtt_ms", "ack_status", "receiver_processing_us", *JOINT_NAMES,
            "target_applied_max_abs_error", "target_present_max_abs_error",
            *(f"applied_{name}" for name in JOINT_NAMES),
            *(f"present_{name}" for name in JOINT_NAMES),
        ]
        with csv_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows[index] for index in sorted(rows))
        print(f"done: sent={seq} acked={acked} pending={len(pending)} invalid_acks={invalid_acks}")
        print(f"CSV: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
