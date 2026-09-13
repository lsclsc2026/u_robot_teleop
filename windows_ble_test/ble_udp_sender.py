import argparse
import asyncio
import csv
import ctypes
import math
import socket
import struct
import sys
import time
from pathlib import Path

from bleak import BleakClient


ADDRESS = "98:DA:10:09:E5:A7"
NOTIFY_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
F1_MASK = 0x0040
R1_MASK = 0x0001
L1_MASK = 0x0002
START_MASK = 0x0004
L2_MASK = 0x0020
X_MASK = 0x0400
UP_MASK = 0x1000
DOWN_MASK = 0x4000
BUTTON_NAMES = (
    "R1", "L1", "Start", "Select", "R2", "L2", "F1", "F2",
    "A", "B", "X", "Y", "Up", "Right", "Down", "Left",
)
MAGIC = 0x504A3241
VERSION = 1
COMMAND_TYPE = 1
ACK_TYPE = 2
RAW_AXES_FLAG = 0x0001
COMMAND_FORMAT = "<IHHQQQIHHfffffff"
ACK_FORMAT = "<IHHQQQQiHH"
COMMAND_SIZE = struct.calcsize(COMMAND_FORMAT)
ACK_SIZE = struct.calcsize(ACK_FORMAT)


def deadzone(value: float, size: float) -> float:
    if abs(value) <= size:
        return 0.0
    # Match the A2 SDK-side mapping: suppress center noise without rescaling
    # the remaining stick range.
    return value


async def run(args):
    loop = asyncio.get_running_loop()
    new_ble_event = asyncio.Event()
    latest = {
        "arrival_ns": 0,
        "lx": 0.0,
        "ly": 0.0,
        "rx": 0.0,
        "ry": 0.0,
        "buttons": 0,
        "valid": False,
    }
    sent_times = {}
    sent = 0
    acked = 0
    invalid_ble = 0
    nonzero_axes = 0

    # Use one socket for command and ACK so Windows treats the ACK as a reply
    # to an established UDP flow instead of unrelated inbound traffic.
    command_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    command_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    command_socket.bind((args.ack_listen, args.ack_port))
    command_socket.connect((args.target, args.port))
    command_socket.setblocking(False)

    output = Path(args.csv)
    with output.open("w", newline="", encoding="utf-8-sig") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(
            [
                "seq",
                "send_unix_ns",
                "ack_unix_ns",
                "ble_to_send_ms",
                "udp_rtt_ms",
                "ble_to_ack_ms",
                "receiver_processing_us",
                "new_ble_sample",
                "f1_held",
                "deadman_required",
                "packet_valid",
                "button_mask",
                "buttons",
                "control_mode",
                "gait",
                "speed_level",
                "lx",
                "ly",
                "rx",
                "ry",
                "vx",
                "vy",
                "yaw",
                "ack_result",
                "ack_flags",
            ]
        )

        stop_ack_reader = asyncio.Event()

        async def ack_reader():
            nonlocal acked
            loop = asyncio.get_running_loop()
            while not stop_ack_reader.is_set():
                try:
                    ack_data = await loop.sock_recv(command_socket, 2048)
                except asyncio.CancelledError:
                    break
                except (ConnectionResetError, OSError):
                    await asyncio.sleep(0.01)
                    continue

                ack_arrival_ns = time.perf_counter_ns()
                if len(ack_data) != ACK_SIZE:
                    continue
                fields = struct.unpack(ACK_FORMAT, ack_data)
                magic, version, packet_type, ack_seq = fields[:4]
                if magic != MAGIC or version != VERSION or packet_type != ACK_TYPE:
                    continue
                previous = sent_times.pop(ack_seq, None)
                if previous is None:
                    continue

                acked += 1
                (
                    send_ns,
                    send_unix_ns,
                    ble_arrival_ns,
                    new_ble_sample,
                    held,
                    deadman_required,
                    valid,
                    button_mask,
                    button_text,
                    plx,
                    ply,
                    prx,
                    pry,
                ) = previous
                ble_to_send_ms = (
                    (send_ns - ble_arrival_ns) / 1_000_000
                    if ble_arrival_ns
                    else float("nan")
                )
                rtt_ms = (ack_arrival_ns - send_ns) / 1_000_000
                ble_to_ack_ms = (
                    (ack_arrival_ns - ble_arrival_ns) / 1_000_000
                    if ble_arrival_ns
                    else float("nan")
                )
                receiver_processing_us = max(0, fields[6] - fields[5]) / 1_000
                writer.writerow(
                    [
                        ack_seq,
                        send_unix_ns,
                        time.time_ns(),
                        f"{ble_to_send_ms:.3f}",
                        f"{rtt_ms:.3f}",
                        f"{ble_to_ack_ms:.3f}",
                        f"{receiver_processing_us:.3f}",
                        int(new_ble_sample),
                        int(held),
                        int(deadman_required),
                        int(valid),
                        f"0x{button_mask:04x}",
                        button_text,
                        "raw_axes",
                        "receiver_owned",
                        "receiver_owned",
                        f"{plx:.6f}",
                        f"{ply:.6f}",
                        f"{prx:.6f}",
                        f"{pry:.6f}",
                        "0.000000",
                        "0.000000",
                        "0.000000",
                        fields[7],
                        fields[8],
                    ]
                )

        def on_notify(_sender, data: bytearray):
            nonlocal invalid_ble
            payload = bytes(data)
            now_ns = time.perf_counter_ns()
            if len(payload) != 20:
                invalid_ble += 1
                latest.update(arrival_ns=now_ns, valid=False)
                return

            raw_lx, raw_rx, raw_ry, raw_ly = struct.unpack_from("<4f", payload, 0)
            buttons = struct.unpack_from("<H", payload, 16)[0]
            axes = (raw_lx, raw_ly, raw_rx, raw_ry)
            valid = all(math.isfinite(v) and abs(v) <= args.max_raw_axis for v in axes)
            if not valid:
                invalid_ble += 1
            latest.update(
                arrival_ns=now_ns,
                lx=raw_lx,
                ly=raw_ly,
                rx=raw_rx,
                ry=raw_ry,
                buttons=buttons,
                valid=valid,
            )
            # Bleak may deliver notifications outside the asyncio task. Wake
            # the UDP loop immediately instead of waiting for its next tick.
            loop.call_soon_threadsafe(new_ble_event.set)

        print(f"Connecting BLE remote {args.address} ...", flush=True)
        async with BleakClient(args.address, timeout=20.0) as client:
            print(f"connected: {client.is_connected}", flush=True)
            await client.start_notify(NOTIFY_UUID, on_notify)
            started_ns = time.perf_counter_ns()
            deadline = time.perf_counter() + args.duration
            heartbeat_period = 1.0 / args.send_hz
            next_flush = time.perf_counter() + 1.0
            last_sent_ble_arrival_ns = 0
            ack_task = asyncio.create_task(ack_reader())
            print(
                f"UDP dry-run target={args.target}:{args.port}, ACK={args.ack_listen}:{args.ack_port}",
                flush=True,
            )
            if args.no_deadman:
                print("Sender direct-control mode: joystick motion is mapped without F1.", flush=True)
            else:
                print("Hold F1 to produce non-zero mapped commands.", flush=True)
            print("This PC sender never calls the robot API; receiver behavior is independent.", flush=True)

            first_packet = True
            while time.perf_counter() < deadline:
                if not first_packet:
                    try:
                        await asyncio.wait_for(
                            new_ble_event.wait(), timeout=heartbeat_period
                        )
                    except asyncio.TimeoutError:
                        pass
                first_packet = False
                new_ble_event.clear()
                if time.perf_counter() >= deadline:
                    break
                now_ns = time.perf_counter_ns()
                age_ms = (
                    (now_ns - latest["arrival_ns"]) / 1_000_000
                    if latest["arrival_ns"]
                    else float("inf")
                )
                fresh = age_ms <= args.timeout_ms
                f1_held = bool(latest["buttons"] & F1_MASK)
                enabled = fresh and latest["valid"] and (args.no_deadman or f1_held)

                if enabled:
                    # Send untouched BLE axes. Calibration, deadzone, gait and
                    # speed mapping have one authoritative owner: Unitree.
                    lx = latest["lx"]
                    ly = latest["ly"]
                    rx = latest["rx"]
                    ry = latest["ry"]
                else:
                    lx = ly = rx = ry = 0.0

                sent += 1
                seq = sent
                packet = struct.pack(
                    COMMAND_FORMAT,
                    MAGIC,
                    VERSION,
                    COMMAND_TYPE,
                    seq,
                    now_ns,
                    latest["arrival_ns"],
                    int((now_ns - started_ns) / 1_000_000) & 0xFFFFFFFF,
                    latest["buttons"],
                    RAW_AXES_FLAG,
                    lx,
                    ly,
                    rx,
                    ry,
                    0.0,
                    0.0,
                    0.0,
                )
                if len(packet) != 68:
                    raise RuntimeError(f"unexpected command packet size: {len(packet)}")
                command_socket.send(packet)
                new_ble_sample = (
                    latest["arrival_ns"] != 0
                    and latest["arrival_ns"] != last_sent_ble_arrival_ns
                )
                if new_ble_sample:
                    last_sent_ble_arrival_ns = latest["arrival_ns"]
                sent_times[seq] = (
                    now_ns,
                    time.time_ns(),
                    latest["arrival_ns"],
                    new_ble_sample,
                    f1_held,
                    not args.no_deadman,
                    latest["valid"],
                    latest["buttons"],
                    "+".join(
                        name
                        for bit, name in enumerate(BUTTON_NAMES)
                        if latest["buttons"] & (1 << bit)
                    ),
                    lx,
                    ly,
                    rx,
                    ry,
                )
                if lx != 0.0 or ly != 0.0 or rx != 0.0 or ry != 0.0:
                    nonzero_axes += 1

                if seq == 1 or seq % max(1, int(args.send_hz)) == 0:
                    print(
                        f"sent={sent} acked={acked} F1={int(f1_held)} "
                        f"raw=({lx:+.3f},{ly:+.3f},{rx:+.3f},{ry:+.3f}) "
                        "mapping=unitree",
                        flush=True,
                    )
                if time.perf_counter() >= next_flush:
                    next_flush = time.perf_counter() + 1.0
                    output_file.flush()

            await client.stop_notify(NOTIFY_UUID)
            await asyncio.sleep(args.ack_drain_ms / 1000.0)
            stop_ack_reader.set()
            ack_task.cancel()
            try:
                await ack_task
            except asyncio.CancelledError:
                pass
            output_file.flush()

    command_socket.close()
    print(
        f"done: sent={sent} acked={acked} pending={len(sent_times)} "
        f"nonzero_axes={nonzero_axes} invalid_ble={invalid_ble} CSV={output}",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description="Unitree BLE to A2JP UDP sender (dry-run receiver only)")
    parser.add_argument("--address", default=ADDRESS, help="BLE address shown by scan_ble.py")
    parser.add_argument("--target", required=True)
    parser.add_argument("--port", type=int, default=39001)
    parser.add_argument("--ack-listen", default="0.0.0.0")
    parser.add_argument("--ack-port", type=int, default=39002)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument(
        "--send-hz",
        type=float,
        default=50.0,
        help="heartbeat rate; new BLE notifications are sent immediately",
    )
    parser.add_argument("--ack-drain-ms", type=float, default=300.0)
    parser.add_argument("--deadzone", type=float, default=0.05)
    parser.add_argument("--timeout-ms", type=float, default=250.0)
    parser.add_argument("--max-raw-axis", type=float, default=1.05)
    parser.add_argument("--max-vx", type=float, default=None, help="optional safety cap")
    parser.add_argument("--max-vy", type=float, default=None, help="optional safety cap")
    parser.add_argument("--max-yaw", type=float, default=None, help="optional safety cap")
    parser.add_argument(
        "--no-deadman",
        dest="no_deadman",
        action="store_true",
        default=True,
        help="map joystick motion without F1 (default)",
    )
    parser.add_argument(
        "--require-f1",
        dest="no_deadman",
        action="store_false",
        help="require holding F1 before mapping joystick motion",
    )
    parser.add_argument(
        "--csv",
        default=str(Path(__file__).with_name("ble_udp_sender.csv")),
    )
    args = parser.parse_args()
    high_resolution_timer = False
    if sys.platform == "win32":
        try:
            high_resolution_timer = ctypes.windll.winmm.timeBeginPeriod(1) == 0
        except (AttributeError, OSError):
            pass
    try:
        asyncio.run(run(args))
    finally:
        if high_resolution_timer:
            ctypes.windll.winmm.timeEndPeriod(1)


if __name__ == "__main__":
    main()
