#!/usr/bin/env python3
"""Low-latency PC1(WiFi) -> PC2 -> Unitree(Ethernet) UDP relay.

This process never imports or calls the Unitree SDK. It validates and forwards
the fixed A2JP packet, then relays the Unitree ACK back from the same WiFi
endpoint that PC1 sent to.
"""

import argparse
import csv
import math
import select
import socket
import struct
import time
from pathlib import Path


MAGIC = 0x504A3241
VERSION = 1
COMMAND_TYPE = 1
ACK_TYPE = 2
COMMAND_FORMAT = "<IHHQQQIHHfffffff"
ACK_HEADER_FORMAT = "<IHHQ"
COMMAND_SIZE = struct.calcsize(COMMAND_FORMAT)
ACK_SIZE = 48


def valid_command(data: bytes):
    if len(data) != COMMAND_SIZE:
        return None
    fields = struct.unpack(COMMAND_FORMAT, data)
    if fields[0] != MAGIC or fields[1] != VERSION or fields[2] != COMMAND_TYPE:
        return None
    if not all(math.isfinite(value) for value in fields[9:]):
        return None
    return fields


def valid_ack(data: bytes):
    if len(data) != ACK_SIZE:
        return None
    magic, version, packet_type, seq = struct.unpack_from(ACK_HEADER_FORMAT, data)
    if magic != MAGIC or version != VERSION or packet_type != ACK_TYPE:
        return None
    return seq


def make_socket(bind_ip: str, port: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((bind_ip, port))
    sock.setblocking(False)
    return sock


def main():
    parser = argparse.ArgumentParser(
        description="A2 PC2 dual-NIC UDP relay (no Unitree SDK)"
    )
    parser.add_argument("--wifi-bind", required=True, help="PC2 WiFi IPv4")
    parser.add_argument("--listen-port", type=int, default=39001)
    parser.add_argument("--allowed-pc1", required=True, help="accepted PC1 WiFi IPv4")
    parser.add_argument("--ethernet-bind", required=True, help="PC2 Ethernet IPv4")
    parser.add_argument("--unitree", required=True, help="Unitree receiver IPv4")
    parser.add_argument("--unitree-port", type=int, default=39001)
    parser.add_argument("--unitree-ack-port", type=int, default=39002)
    parser.add_argument("--duration", type=float, default=45.0)
    parser.add_argument("--pending-timeout", type=float, default=10.0)
    parser.add_argument("--csv", default="pc2_udp_relay.csv")
    args = parser.parse_args()

    wifi_socket = make_socket(args.wifi_bind, args.listen_port)
    ethernet_socket = make_socket(args.ethernet_bind, args.unitree_ack_port)
    unitree_target = (args.unitree, args.unitree_port)

    output = Path(args.csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = {}
    received = forwarded = acked = invalid = rejected_source = 0
    stale = gaps = expired = 0
    last_seq = 0
    started = time.perf_counter()
    next_print = started
    next_flush = started + 1.0

    print(
        f"PC2 relay: {args.wifi_bind}:{args.listen_port} (WiFi) -> "
        f"{args.unitree}:{args.unitree_port} via {args.ethernet_bind} (Ethernet)",
        flush=True,
    )
    print(
        f"ACK: {args.ethernet_bind}:{args.unitree_ack_port} -> PC1; "
        "SAFE RELAY: no Unitree SDK is loaded",
        flush=True,
    )

    with output.open("w", newline="", encoding="utf-8-sig") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(
            [
                "seq",
                "pc2_receive_unix_ns",
                "pc2_receive_perf_ns",
                "pc2_forward_perf_ns",
                "relay_processing_us",
                "unitree_ack_perf_ns",
                "pc2_to_unitree_ack_ms",
                "ack_result",
                "ack_flags",
                "pc1_ip",
            ]
        )
        try:
            while args.duration <= 0 or time.perf_counter() - started < args.duration:
                readable, _, _ = select.select(
                    [wifi_socket, ethernet_socket], [], [], 0.005
                )
                for sock in readable:
                    if sock is wifi_socket:
                        while True:
                            try:
                                data, source = wifi_socket.recvfrom(2048)
                            except BlockingIOError:
                                break
                            receive_ns = time.perf_counter_ns()
                            received += 1
                            if source[0] != args.allowed_pc1:
                                rejected_source += 1
                                continue
                            fields = valid_command(data)
                            if fields is None:
                                invalid += 1
                                continue
                            seq = fields[3]
                            if seq <= last_seq:
                                stale += 1
                                continue
                            if last_seq and seq > last_seq + 1:
                                gaps += seq - last_seq - 1
                            last_seq = seq
                            ethernet_socket.sendto(data, unitree_target)
                            forward_ns = time.perf_counter_ns()
                            pending[seq] = (
                                source,
                                receive_ns,
                                forward_ns,
                                time.time_ns(),
                            )
                            forwarded += 1
                    else:
                        while True:
                            try:
                                data, source = ethernet_socket.recvfrom(2048)
                            except BlockingIOError:
                                break
                            ack_ns = time.perf_counter_ns()
                            if source[0] != args.unitree:
                                rejected_source += 1
                                continue
                            seq = valid_ack(data)
                            if seq is None:
                                invalid += 1
                                continue
                            item = pending.pop(seq, None)
                            if item is None:
                                stale += 1
                                continue
                            pc1_source, receive_ns, forward_ns, receive_unix_ns = item
                            wifi_socket.sendto(data, pc1_source)
                            ack_fields = struct.unpack("<IHHQQQQiHH", data)
                            writer.writerow(
                                [
                                    seq,
                                    receive_unix_ns,
                                    receive_ns,
                                    forward_ns,
                                    f"{(forward_ns - receive_ns) / 1000:.3f}",
                                    ack_ns,
                                    f"{(ack_ns - forward_ns) / 1_000_000:.3f}",
                                    ack_fields[7],
                                    ack_fields[8],
                                    pc1_source[0],
                                ]
                            )
                            acked += 1

                now = time.perf_counter()
                if now >= next_flush:
                    cutoff_ns = time.perf_counter_ns() - int(
                        args.pending_timeout * 1_000_000_000
                    )
                    old = [seq for seq, item in pending.items() if item[2] < cutoff_ns]
                    for seq in old:
                        pending.pop(seq, None)
                    expired += len(old)
                    output_file.flush()
                    next_flush = now + 1.0
                if now >= next_print:
                    print(
                        f"rx={received} fwd={forwarded} ack={acked} "
                        f"pending={len(pending)} invalid={invalid} gaps={gaps}",
                        flush=True,
                    )
                    next_print = now + 1.0
        except KeyboardInterrupt:
            print("Ctrl-C", flush=True)

    wifi_socket.close()
    ethernet_socket.close()
    print(
        f"done: received={received} forwarded={forwarded} acked={acked} "
        f"pending={len(pending)} invalid={invalid} rejected_source={rejected_source} "
        f"stale={stale} gaps={gaps} expired={expired} CSV={output}",
        flush=True,
    )


if __name__ == "__main__":
    main()
