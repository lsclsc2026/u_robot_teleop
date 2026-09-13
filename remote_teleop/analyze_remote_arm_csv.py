#!/usr/bin/env python3
"""Summarize the PC1 sender CSV produced by pc1_leader_sender.py."""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import Counter

from arm_udp_protocol import JOINT_NAMES


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def describe(name: str, values: list[float], unit: str) -> None:
    if not values:
        print(f"{name}: count=0")
        return
    print(
        f"{name}: count={len(values)} p50={statistics.median(values):.3f} {unit} "
        f"p95={percentile(values, 0.95):.3f} {unit} "
        f"p99={percentile(values, 0.99):.3f} {unit} max={max(values):.3f} {unit}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file")
    args = parser.parse_args()
    with open(args.csv_file, newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    rtts = [float(row["rtt_ms"]) for row in rows if row.get("rtt_ms")]
    reads = [float(row["leader_read_us"]) for row in rows if row.get("leader_read_us")]
    processing = [float(row["receiver_processing_us"]) for row in rows if row.get("receiver_processing_us")]
    target_applied = [
        float(row["target_applied_max_abs_error"])
        for row in rows
        if row.get("target_applied_max_abs_error")
    ]
    target_present = [
        float(row["target_present_max_abs_error"])
        for row in rows
        if row.get("target_present_max_abs_error")
    ]
    statuses = Counter(row["ack_status"] or "missing" for row in rows)
    seqs = [int(row["seq"]) for row in rows]

    print(f"file: {args.csv_file}")
    print(f"sent rows: {len(rows)}")
    if seqs:
        print(f"seq: {min(seqs)}..{max(seqs)}")
    print("ACK status:", " ".join(f"{key}={value}" for key, value in sorted(statuses.items())))
    describe("leader_read", reads, "us")
    describe("udp_write_ack_rtt", rtts, "ms")
    if statuses.get("robot_sent", 0) or statuses.get("startup_syncing", 0) or statuses.get("startup_rejected", 0):
        describe("receiver_unpack_and_serial_write", processing, "us")
    else:
        describe("receiver_unpack_and_ack_dry_run", processing, "us")
    describe("target_to_applied_max_abs_error", target_applied, "units")
    describe("target_to_present_max_abs_error", target_present, "units")

    print("joint ranges:")
    for joint in JOINT_NAMES:
        values = [float(row[joint]) for row in rows if row.get(joint)]
        if values:
            print(
                f"  {joint}: min={min(values):.3f} max={max(values):.3f} "
                f"span={max(values) - min(values):.3f}"
            )
    if statuses.get("robot_sent", 0):
        print("per-joint target-to-present absolute error:")
        for joint in JOINT_NAMES:
            values = [
                abs(float(row[joint]) - float(row[f"present_{joint}"]))
                for row in rows
                if row.get("present_" + joint) and row.get("ack_status") == "robot_sent"
            ]
            if values:
                print(
                    f"  {joint}: p50={statistics.median(values):.3f} "
                    f"p95={percentile(values, 0.95):.3f} max={max(values):.3f}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
