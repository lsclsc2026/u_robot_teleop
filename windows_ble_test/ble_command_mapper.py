import argparse
import asyncio
import csv
import math
import struct
import time
from pathlib import Path

from bleak import BleakClient


ADDRESS = "98:DA:10:09:E5:A7"
NOTIFY_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
F1_MASK = 0x0040


def apply_deadzone(value: float, deadzone: float) -> float:
    if abs(value) <= deadzone:
        return 0.0
    scaled = (abs(value) - deadzone) / (1.0 - deadzone)
    return math.copysign(min(scaled, 1.0), value)


async def run(args):
    output = Path(args.csv)
    latest = {
        "recv_ns": 0,
        "lx": 0.0,
        "ly": 0.0,
        "rx": 0.0,
        "ry": 0.0,
        "buttons": 0,
        "valid": False,
    }
    received = 0
    invalid = 0
    started_ns = 0

    with output.open("w", newline="", encoding="utf-8-sig") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(
            [
                "unix_ns",
                "elapsed_ms",
                "packet_age_ms",
                "packet_valid",
                "f1_held",
                "lx",
                "ly",
                "rx",
                "ry",
                "vx",
                "vy",
                "yaw",
                "state",
            ]
        )

        def on_notify(_sender, data: bytearray):
            nonlocal received, invalid
            payload = bytes(data)
            now_ns = time.perf_counter_ns()
            received += 1

            if len(payload) != 20:
                invalid += 1
                latest.update(recv_ns=now_ns, valid=False)
                return

            # BLE float order: LX, RX, RY, LY.
            lx, rx, ry, ly = struct.unpack_from("<4f", payload, 0)
            buttons = struct.unpack_from("<H", payload, 16)[0]
            axes = (lx, ly, rx, ry)

            # Reject non-finite values and transient values outside the physical range.
            valid = all(math.isfinite(v) and abs(v) <= args.max_raw_axis for v in axes)
            if not valid:
                invalid += 1

            latest.update(
                recv_ns=now_ns,
                lx=lx,
                ly=ly,
                rx=rx,
                ry=ry,
                buttons=buttons,
                valid=valid,
            )

        print(f"Connecting to {ADDRESS} ...", flush=True)
        async with BleakClient(ADDRESS, timeout=20.0) as client:
            print(f"connected: {client.is_connected}", flush=True)
            await client.start_notify(NOTIFY_UUID, on_notify)
            started_ns = time.perf_counter_ns()
            period = 1.0 / args.command_hz
            deadline = time.perf_counter() + args.duration
            print(
                "DRY RUN: hold F1 to enable command output; release F1 to stop.",
                flush=True,
            )

            while time.perf_counter() < deadline:
                tick_ns = time.perf_counter_ns()
                recv_ns = latest["recv_ns"]
                age_ms = (tick_ns - recv_ns) / 1_000_000 if recv_ns else float("inf")
                fresh = recv_ns != 0 and age_ms <= args.timeout_ms
                f1_held = bool(latest["buttons"] & F1_MASK)

                if not fresh:
                    state = "STOP_TIMEOUT"
                elif not latest["valid"]:
                    state = "STOP_INVALID"
                elif not f1_held:
                    state = "STOP_F1_RELEASED"
                else:
                    state = "ENABLED"

                if state == "ENABLED":
                    lx = apply_deadzone(latest["lx"], args.deadzone)
                    ly = apply_deadzone(latest["ly"], args.deadzone)
                    rx = apply_deadzone(latest["rx"], args.deadzone)
                    ry = apply_deadzone(latest["ry"], args.deadzone)
                    vx = max(-args.max_vx, min(args.max_vx, ly * args.max_vx))
                    vy = max(-args.max_vy, min(args.max_vy, lx * args.max_vy))
                    yaw = max(-args.max_yaw, min(args.max_yaw, rx * args.max_yaw))
                else:
                    lx = ly = rx = ry = 0.0
                    vx = vy = yaw = 0.0

                elapsed_ms = (tick_ns - started_ns) / 1_000_000
                print(
                    f"{state:<16} F1={int(f1_held)} "
                    f"LX={lx:+.2f} LY={ly:+.2f} RX={rx:+.2f} RY={ry:+.2f} "
                    f"=> vx={vx:+.3f} vy={vy:+.3f} yaw={yaw:+.3f}",
                    flush=True,
                )
                writer.writerow(
                    [
                        time.time_ns(),
                        f"{elapsed_ms:.3f}",
                        "inf" if not fresh else f"{age_ms:.3f}",
                        int(latest["valid"]),
                        int(f1_held),
                        f"{latest['lx']:.6f}",
                        f"{latest['ly']:.6f}",
                        f"{latest['rx']:.6f}",
                        f"{latest['ry']:.6f}",
                        f"{vx:.6f}",
                        f"{vy:.6f}",
                        f"{yaw:.6f}",
                        state,
                    ]
                )
                output_file.flush()
                await asyncio.sleep(period)

            await client.stop_notify(NOTIFY_UUID)

    print(f"done: received={received} invalid={invalid} CSV={output}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Unitree BLE remote command mapper (dry run)")
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--command-hz", type=float, default=10.0)
    parser.add_argument("--deadzone", type=float, default=0.05)
    parser.add_argument("--timeout-ms", type=float, default=250.0)
    parser.add_argument("--max-raw-axis", type=float, default=1.05)
    parser.add_argument("--max-vx", type=float, default=0.20)
    parser.add_argument("--max-vy", type=float, default=0.10)
    parser.add_argument("--max-yaw", type=float, default=0.30)
    parser.add_argument(
        "--csv",
        default=str(Path(__file__).with_name("ble_command_dry_run.csv")),
    )
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
