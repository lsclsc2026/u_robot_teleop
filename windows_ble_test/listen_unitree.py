import asyncio
import csv
import time
from pathlib import Path

from bleak import BleakClient


ADDRESS = "98:DA:10:09:E5:A7"
NOTIFY_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
DURATION_SECONDS = 60
OUTPUT = Path(__file__).with_name("unitree_notify.csv")


async def main():
    started_ns = time.perf_counter_ns()

    with OUTPUT.open("w", newline="", encoding="utf-8-sig") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(["unix_ns", "elapsed_ms", "length", "hex"])

        def on_notify(_sender, data: bytearray):
            unix_ns = time.time_ns()
            elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
            payload = bytes(data)
            hex_data = payload.hex(" ")
            writer.writerow([unix_ns, f"{elapsed_ms:.3f}", len(payload), hex_data])
            output_file.flush()
            print(
                f"elapsed_ms={elapsed_ms:10.3f} len={len(payload):3d} data={hex_data}",
                flush=True,
            )

        print(f"Connecting to {ADDRESS} ...", flush=True)
        async with BleakClient(ADDRESS, timeout=20.0) as client:
            print(f"connected: {client.is_connected}", flush=True)
            await client.start_notify(NOTIFY_UUID, on_notify)
            print(
                "Listening for 60 seconds. Press one button or move one stick at a time.",
                flush=True,
            )
            await asyncio.sleep(DURATION_SECONDS)
            await client.stop_notify(NOTIFY_UUID)

    print(f"done; CSV saved to: {OUTPUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
