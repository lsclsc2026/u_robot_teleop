#!/usr/bin/env python3
"""Summarize latency CSV produced by a2_network_bridge."""

import csv
import statistics
import sys
from pathlib import Path


def percentile(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    index = (len(values) - 1) * p
    lo = int(index)
    hi = min(lo + 1, len(values) - 1)
    frac = index - lo
    return values[lo] * (1.0 - frac) + values[hi] * frac


def summarize(label, values):
    print(
        f"{label}: count={len(values)} "
        f"p50={percentile(values, 0.50):.3f} "
        f"p95={percentile(values, 0.95):.3f} "
        f"p99={percentile(values, 0.99):.3f} "
        f"max={max(values) if values else 0.0:.3f}"
    )


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} <network_bridge.csv>", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    rows = list(csv.DictReader(path.open(newline="")))
    rtt = [float(row["rtt_ms"]) for row in rows]
    lowstate_to_ack = [float(row["lowstate_to_ack_ms"]) for row in rows]
    oneway = [float(row["receiver_oneway_ms_same_clock"]) for row in rows]
    button_rows = [row for row in rows if row["pressed"]]
    robot_command_rows = [
        row for row in rows if row.get("robot_command_sent", "0") == "1"
    ]

    print(f"file: {path}")
    print(f"acked packets: {len(rows)}")
    summarize("udp_rtt_ms", rtt)
    summarize("lowstate_to_ack_ms", lowstate_to_ack)
    summarize("receiver_oneway_ms_same_clock", oneway)
    print(f"button packets: {len(button_rows)}")
    print(f"robot command packets: {len(robot_command_rows)}")
    for row in button_rows[:20]:
        print(
            f"button seq={row['seq']} pressed={row['pressed']} "
            f"rtt_ms={float(row['rtt_ms']):.3f} "
            f"lowstate_to_ack_ms={float(row['lowstate_to_ack_ms']):.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
