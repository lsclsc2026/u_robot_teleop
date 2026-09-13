#!/usr/bin/env python3
"""Receive latest SO-101 targets on Unitree and optionally drive the follower arm."""

from __future__ import annotations

import argparse
import csv
import os
import select
import signal
import socket
import time
from pathlib import Path

from arm_udp_protocol import (
    ACK_DRY_RUN,
    ACK_ROBOT_ERROR,
    ACK_ROBOT_SENT,
    ACK_STARTUP_REJECTED,
    ACK_STARTUP_SYNCING,
    ACK_SUPERSEDED,
    FLAG_ENABLED,
    JOINT_NAMES,
    decode_action,
    encode_ack,
)


DEFAULT_PORT = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B3D047726-if00"
DEFAULT_CALIBRATION = "~/.cache/huggingface/lerobot/calibration/robots/so_follower/aloha_follower.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=39101)
    parser.add_argument("--allowed-sender", default="172.18.21.232")
    parser.add_argument("--serial", default=DEFAULT_PORT)
    parser.add_argument("--calibration", default=DEFAULT_CALIBRATION)
    parser.add_argument("--max-relative-target", type=float, default=8.0)
    parser.add_argument("--startup-max-delta", type=float, default=25.0)
    parser.add_argument("--startup-sync-speed", type=float, default=30.0)
    parser.add_argument("--startup-sync-tolerance", type=float, default=2.0)
    parser.add_argument("--watchdog-ms", type=float, default=250.0)
    parser.add_argument("--duration", type=float, default=300.0)
    parser.add_argument("--csv", default="remote_arm_receiver.csv")
    parser.add_argument("--enable-motors", action="store_true")
    parser.add_argument("--keep-torque-on-exit", action="store_true")
    return parser.parse_args()


def send_ack(
    sock: socket.socket,
    peer: tuple[str, int],
    status: int,
    seq: int,
    receive_ns: int,
    applied_positions: tuple[float, ...] | None = None,
    present_positions: tuple[float, ...] | None = None,
) -> int:
    done_ns = time.monotonic_ns()
    sock.sendto(
        encode_ack(status, seq, receive_ns, done_ns, applied_positions, present_positions), peer
    )
    return done_ns


def main() -> int:
    args = parse_args()
    signal.signal(signal.SIGINT, lambda _signum, _frame: (_ for _ in ()).throw(KeyboardInterrupt()))
    signal.signal(signal.SIGTERM, lambda _signum, _frame: (_ for _ in ()).throw(KeyboardInterrupt()))
    if args.enable_motors and os.getenv("ARM_REAL_CONTROL") != "YES":
        raise SystemExit(
            "Refusing real follower control. After clearing the workspace, prefix the command with "
            "ARM_REAL_CONTROL=YES."
        )

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1_048_576)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1_048_576)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0xB8)
    sock.bind((args.bind, args.port))
    sock.settimeout(min(args.watchdog_ms / 2_000.0, 0.05))

    bus = None
    read_positions = send_positions = None
    if args.enable_motors:
        from so101_bus import (
            assert_calibrated,
            configure_follower,
            make_bus,
            read_positions as _read_positions,
            send_positions as _send_positions,
        )

        bus = make_bus(args.serial, args.calibration)
        print(f"Connecting follower: {args.serial}")
        bus.connect()
        assert_calibrated(bus)
        configure_follower(bus)
        read_positions = _read_positions
        send_positions = _send_positions

    print(f"Unitree follower receiver listening on udp://{args.bind}:{args.port}")
    print(f"allowed sender: {args.allowed_sender}")
    if bus is None:
        print("DRY RUN: packets are unpacked and ACKed; no serial/motor API is opened.")
    else:
        print("REAL FOLLOWER CONTROL ENABLED")
        print("No packet for watchdog interval => stop sending new targets; servos retain their last goal.")

    rows: list[dict[str, object]] = []
    received = processed = superseded = invalid = wrong_sender = robot_errors = 0
    last_seq = 0
    last_valid_ns = 0
    watchdog_active = False
    control_started = False
    start = time.monotonic()
    next_report = start

    try:
        while time.monotonic() - start < args.duration:
            batch: list[tuple[object, tuple[str, int], int]] = []
            try:
                data, peer = sock.recvfrom(512)
                receive_ns = time.monotonic_ns()
                if peer[0] != args.allowed_sender:
                    wrong_sender += 1
                    continue
                try:
                    packet = decode_action(data)
                except ValueError:
                    invalid += 1
                    continue
                batch.append((packet, peer, receive_ns))
                received += 1
            except socket.timeout:
                now_ns = time.monotonic_ns()
                if last_valid_ns and (now_ns - last_valid_ns) / 1_000_000 > args.watchdog_ms:
                    if not watchdog_active:
                        print(f"WATCHDOG: no fresh target for > {args.watchdog_ms:.0f} ms; holding last goal")
                        watchdog_active = True
                continue

            sock.setblocking(False)
            while select.select([sock], [], [], 0)[0]:
                try:
                    data, peer = sock.recvfrom(512)
                except BlockingIOError:
                    break
                receive_ns = time.monotonic_ns()
                if peer[0] != args.allowed_sender:
                    wrong_sender += 1
                    continue
                try:
                    packet = decode_action(data)
                except ValueError:
                    invalid += 1
                    continue
                batch.append((packet, peer, receive_ns))
                received += 1
            sock.settimeout(min(args.watchdog_ms / 2_000.0, 0.05))

            batch.sort(key=lambda item: item[0].seq)  # type: ignore[attr-defined]
            newest = batch[-1]
            for old_packet, old_peer, old_receive_ns in batch[:-1]:
                send_ack(sock, old_peer, ACK_SUPERSEDED, old_packet.seq, old_receive_ns)  # type: ignore[attr-defined]
                superseded += 1

            packet, peer, receive_ns = newest
            if packet.seq <= last_seq or not (packet.flags & FLAG_ENABLED):  # type: ignore[attr-defined]
                send_ack(sock, peer, ACK_SUPERSEDED, packet.seq, receive_ns)  # type: ignore[attr-defined]
                superseded += 1
                continue

            last_seq = packet.seq  # type: ignore[attr-defined]
            last_valid_ns = receive_ns
            watchdog_active = False
            status = ACK_DRY_RUN
            max_startup_delta: float | str = ""
            applied_positions: tuple[float, ...] | None = None
            present_positions: tuple[float, ...] | None = None

            try:
                if bus is not None:
                    assert read_positions is not None and send_positions is not None
                    if not control_started:
                        current = read_positions(bus)
                        present_positions = current
                        max_startup_delta = max(
                            abs(target - actual)
                            for target, actual in zip(packet.positions, current, strict=True)  # type: ignore[attr-defined]
                        )
                        if max_startup_delta > args.startup_max_delta:
                            status = ACK_STARTUP_REJECTED
                        elif max_startup_delta > args.startup_sync_tolerance:
                            # Match LeRobot SOFollower.send_action(): read the actual
                            # pose, clamp every target to present +/- max_relative_target,
                            # then write it. This produces a meaningful servo command at
                            # 100 Hz and converges to the leader pose at startup.
                            applied_positions, present_positions = send_positions(
                                bus,
                                packet.positions,  # type: ignore[attr-defined]
                                args.max_relative_target,
                            )
                            status = ACK_STARTUP_SYNCING
                        else:
                            control_started = True
                    if control_started:
                        applied_positions, present_positions = send_positions(
                            bus,
                            packet.positions,  # type: ignore[attr-defined]
                            args.max_relative_target,
                        )
                        status = ACK_ROBOT_SENT
                done_ns = send_ack(
                    sock,
                    peer,
                    status,
                    packet.seq,  # type: ignore[attr-defined]
                    receive_ns,
                    applied_positions,
                    present_positions,
                )
                processed += 1
            except Exception as error:
                robot_errors += 1
                status = ACK_ROBOT_ERROR
                done_ns = send_ack(sock, peer, ACK_ROBOT_ERROR, packet.seq, receive_ns)  # type: ignore[attr-defined]
                print(f"ROBOT ERROR seq={packet.seq}: {type(error).__name__}: {error}")  # type: ignore[attr-defined]

            rows.append(
                {
                    "seq": packet.seq,  # type: ignore[attr-defined]
                    "host_unix_ns": time.time_ns(),
                    "receive_steady_ns": receive_ns,
                    "done_steady_ns": done_ns,
                    "processing_us": (done_ns - receive_ns) / 1_000,
                    "status": status,
                    "startup_max_delta": max_startup_delta,
                    **{
                        f"target_{name}": value
                        for name, value in zip(JOINT_NAMES, packet.positions, strict=True)  # type: ignore[attr-defined]
                    },
                    **{
                        f"applied_{name}": "" if applied_positions is None else value
                        for name, value in zip(
                            JOINT_NAMES,
                            applied_positions if applied_positions is not None else ("",) * len(JOINT_NAMES),
                            strict=True,
                        )
                    },
                    **{
                        f"present_{name}": "" if present_positions is None else value
                        for name, value in zip(
                            JOINT_NAMES,
                            present_positions if present_positions is not None else ("",) * len(JOINT_NAMES),
                            strict=True,
                        )
                    },
                }
            )

            now = time.monotonic()
            if now >= next_report:
                print(
                    f"rx={received} processed={processed} superseded={superseded} "
                    f"invalid={invalid} seq={last_seq} real_sent={int(status == ACK_ROBOT_SENT)}"
                )
                next_report = now + 1.0
    except KeyboardInterrupt:
        print("Interrupted.")
    finally:
        if bus is not None and bus.is_connected:
            bus.disconnect(disable_torque=not args.keep_torque_on_exit)
        sock.close()
        csv_path = Path(args.csv).expanduser()
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "seq", "host_unix_ns", "receive_steady_ns", "done_steady_ns", "processing_us",
            "status", "startup_max_delta",
            *(f"target_{name}" for name in JOINT_NAMES),
            *(f"applied_{name}" for name in JOINT_NAMES),
            *(f"present_{name}" for name in JOINT_NAMES),
        ]
        with csv_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(
            f"done: received={received} processed={processed} superseded={superseded} "
            f"invalid={invalid} wrong_sender={wrong_sender} robot_errors={robot_errors}"
        )
        print(f"CSV: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
