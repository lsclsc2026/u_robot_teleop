import argparse
import csv
import math
import socket
import struct
import time
from pathlib import Path


MAGIC = 0x504A3241
VERSION = 1
COMMAND_TYPE = 1
ACK_TYPE = 2
COMMAND_FORMAT = "<IHHQQQIHHfffffff"
ACK_FORMAT = "<IHHQQQQiHH"
COMMAND_SIZE = struct.calcsize(COMMAND_FORMAT)


def main():
    parser = argparse.ArgumentParser(
        description="Dry-run UDP receiver: unpack, print and ACK; never controls a robot"
    )
    parser.add_argument("--listen", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=39001)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--csv", default="udp_dry_receiver.csv")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.listen, args.port))
    sock.settimeout(0.2)

    received = 0
    invalid = 0
    nonzero = 0
    started = time.monotonic()
    deadline = started + args.duration if args.duration > 0 else None
    next_print = started
    next_flush = started + 1.0
    output = Path(args.csv)

    print(f"UDP DRY RECEIVER listening on {args.listen}:{args.port}", flush=True)
    print("SAFE MODE: no Unitree SDK; packets are only unpacked and acknowledged", flush=True)

    with output.open("w", newline="", encoding="utf-8-sig") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(
            [
                "recv_unix_ns",
                "source",
                "seq",
                "buttons",
                "lx",
                "ly",
                "rx",
                "ry",
                "vx",
                "vy",
                "yaw",
            ]
        )

        try:
            while deadline is None or time.monotonic() < deadline:
                try:
                    data, source = sock.recvfrom(2048)
                except socket.timeout:
                    continue

                receiver_arrival_ns = time.perf_counter_ns()
                if len(data) != COMMAND_SIZE:
                    invalid += 1
                    continue

                fields = struct.unpack(COMMAND_FORMAT, data)
                magic, version, packet_type = fields[:3]
                if magic != MAGIC or version != VERSION or packet_type != COMMAND_TYPE:
                    invalid += 1
                    continue

                seq = fields[3]
                original_send_ns = fields[4]
                buttons = fields[7]
                lx, ly, rx, ry, vx, vy, yaw = fields[9:16]
                values = (lx, ly, rx, ry, vx, vy, yaw)
                if not all(math.isfinite(value) for value in values):
                    invalid += 1
                    continue

                received += 1
                moving = any(abs(value) > 1e-6 for value in (vx, vy, yaw))
                nonzero += int(moving)

                # ACK first: disk logging and terminal output must never delay
                # the real-time network response path.
                ack_send_ns = time.perf_counter_ns()
                ack = struct.pack(
                    ACK_FORMAT,
                    MAGIC,
                    VERSION,
                    ACK_TYPE,
                    seq,
                    original_send_ns,
                    receiver_arrival_ns,
                    ack_send_ns,
                    0,
                    0,
                    0,
                )
                sock.sendto(ack, source)

                writer.writerow(
                    [
                        time.time_ns(),
                        f"{source[0]}:{source[1]}",
                        seq,
                        f"0x{buttons:04x}",
                        f"{lx:.6f}",
                        f"{ly:.6f}",
                        f"{rx:.6f}",
                        f"{ry:.6f}",
                        f"{vx:.6f}",
                        f"{vy:.6f}",
                        f"{yaw:.6f}",
                    ]
                )

                now = time.monotonic()
                if now >= next_flush:
                    next_flush = now + 1.0
                    output_file.flush()
                if now >= next_print:
                    next_print = now + 0.5
                    print(
                        f"rx={received} seq={seq} buttons=0x{buttons:04x} "
                        f"cmd(vx,vy,yaw)=({vx:+.3f},{vy:+.3f},{yaw:+.3f}) "
                        "robot_sent=0",
                        flush=True,
                    )
        except KeyboardInterrupt:
            pass
        finally:
            sock.close()

    print(
        f"done: received={received} invalid={invalid} nonzero={nonzero} CSV={output}",
        flush=True,
    )


if __name__ == "__main__":
    main()
