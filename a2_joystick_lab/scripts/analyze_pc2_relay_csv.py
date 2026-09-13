#!/usr/bin/env python3

import argparse
import csv
import math
import statistics


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def print_metric(rows, field, unit):
    values = []
    for row in rows:
        try:
            value = float(row[field])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    if values:
        print(
            f"{field}: count={len(values)} p50={statistics.median(values):.3f}{unit} "
            f"p95={percentile(values, .95):.3f}{unit} "
            f"p99={percentile(values, .99):.3f}{unit} max={max(values):.3f}{unit}"
        )


def main():
    parser = argparse.ArgumentParser(description="Analyze the PC2 relay CSV")
    parser.add_argument("csv_file")
    args = parser.parse_args()
    with open(args.csv_file, encoding="utf-8-sig", newline="") as input_file:
        rows = list(csv.DictReader(input_file))
    print(f"file: {args.csv_file}")
    print(f"acked packets: {len(rows)}")
    if not rows:
        return
    seqs = [int(row["seq"]) for row in rows]
    missing = len(set(range(min(seqs), max(seqs) + 1)) - set(seqs))
    print(
        f"acked seq: {min(seqs)}..{max(seqs)} missing_inside_range={missing} "
        f"duplicates={len(seqs) - len(set(seqs))}"
    )
    print_metric(rows, "relay_processing_us", " us")
    print_metric(rows, "pc2_to_unitree_ack_ms", " ms")
    errors = sum(int(row.get("ack_result", "0")) != 0 for row in rows)
    actions = sum(int(row.get("ack_flags", "0"), 0) & 0x2 != 0 for row in rows)
    print(f"nonzero_ack_results={errors} robot_action_acks={actions}")


if __name__ == "__main__":
    main()
