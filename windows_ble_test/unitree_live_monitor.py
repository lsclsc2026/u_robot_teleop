import argparse
import asyncio
import csv
import struct
import time
from pathlib import Path

from bleak import BleakClient


ADDRESS = "98:DA:10:09:E5:A7"
NOTIFY_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

BUTTONS = (
    (0x0001, "R1"),
    (0x0002, "L1"),
    (0x0004, "Start"),
    (0x0008, "Select"),
    (0x0010, "R2"),
    (0x0020, "L2"),
    (0x0040, "F1"),
    (0x0080, "F2"),
    (0x0100, "A"),
    (0x0200, "B"),
    (0x0400, "X"),
    (0x0800, "Y"),
    (0x1000, "Up"),
    (0x2000, "Right"),
    (0x4000, "Down"),
    (0x8000, "Left"),
)


def button_names(mask: int) -> str:
    names = [name for bit, name in BUTTONS if mask & bit]
    return "+".join(names) if names else "-"


def clean_axis(value: float, deadzone: float) -> float:
    return 0.0 if abs(value) < deadzone else value


async def run(address: str, duration: float, output: Path, deadzone: float):
    rows = 0
    started_ns = 0
    last_print_ns = 0
    last_state = None

    with output.open("w", newline="", encoding="utf-8-sig") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(
            ["unix_ns", "elapsed_ms", "lx", "ly", "rx", "ry", "button_mask", "buttons", "battery", "raw_hex"]
        )

        def on_notify(_sender, data: bytearray):
            nonlocal rows, last_print_ns, last_state
            payload = bytes(data)
            if len(payload) != 20:
                print(f"unexpected packet length: {len(payload)}", flush=True)
                return

            # BLE payload float order is LX, RX, RY, LY.
            raw_lx, raw_rx, raw_ry, raw_ly = struct.unpack_from("<4f", payload, 0)
            lx = clean_axis(raw_lx, deadzone)
            ly = clean_axis(raw_ly, deadzone)
            rx = clean_axis(raw_rx, deadzone)
            ry = clean_axis(raw_ry, deadzone)
            mask = struct.unpack_from("<H", payload, 16)[0]
            names = button_names(mask)
            battery = payload[18]
            now_ns = time.perf_counter_ns()
            elapsed_ms = (now_ns - started_ns) / 1_000_000

            writer.writerow(
                [time.time_ns(), f"{elapsed_ms:.3f}", f"{lx:.6f}", f"{ly:.6f}", f"{rx:.6f}", f"{ry:.6f}", f"0x{mask:04x}", names, battery, payload.hex()]
            )
            rows += 1

            state = (round(lx, 2), round(ly, 2), round(rx, 2), round(ry, 2), mask)
            if state != last_state and now_ns - last_print_ns >= 40_000_000:
                print(
                    f"LX={lx:+.3f} LY={ly:+.3f} RX={rx:+.3f} RY={ry:+.3f} "
                    f"buttons={names:<12} battery={battery}%",
                    flush=True,
                )
                last_state = state
                last_print_ns = now_ns

        print(f"Connecting to {address} ...", flush=True)
        async with BleakClient(address, timeout=20.0) as client:
            print(f"connected: {client.is_connected}", flush=True)
            await client.start_notify(NOTIFY_UUID, on_notify)
            started_ns = time.perf_counter_ns()
            print(f"Live monitoring for {duration:g} seconds. Move one control at a time.", flush=True)
            await asyncio.sleep(duration)
            await client.stop_notify(NOTIFY_UUID)

    print(f"done: rows={rows}; CSV={output}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Unitree BLE remote live monitor")
    parser.add_argument("--address", default=ADDRESS, help="BLE address shown by scan_ble.py")
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--csv", type=Path, default=Path(__file__).with_name("unitree_live.csv"))
    parser.add_argument("--deadzone", type=float, default=0.03)
    args = parser.parse_args()
    asyncio.run(run(args.address, args.duration, args.csv, args.deadzone))


if __name__ == "__main__":
    main()
