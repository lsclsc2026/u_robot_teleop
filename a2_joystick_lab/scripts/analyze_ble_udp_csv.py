#!/usr/bin/env python3

import argparse
import csv
import math
import statistics
from collections import Counter


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def metric(rows, name, unit, label=None):
    values = []
    for row in rows:
        try:
            value = float(row[name])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    if not values:
        return
    print(
        f"{label or name}: count={len(values)} "
        f"p50={statistics.median(values):.3f}{unit} "
        f"p95={percentile(values, 0.95):.3f}{unit} "
        f"p99={percentile(values, 0.99):.3f}{unit} "
        f"max={max(values):.3f}{unit}"
    )


def main():
    parser = argparse.ArgumentParser(description="Analyze BLE-to-UDP sender ACK CSV")
    parser.add_argument("csv_file")
    args = parser.parse_args()

    with open(args.csv_file, encoding="utf-8-sig", newline="") as input_file:
        rows = list(csv.DictReader(input_file))

    print(f"file: {args.csv_file}")
    print(f"acked packets: {len(rows)}")
    if not rows:
        return

    sequences = sorted(int(row["seq"]) for row in rows)
    missing = len(set(range(sequences[0], sequences[-1] + 1)) - set(sequences))
    print(
        f"acked seq: {sequences[0]}..{sequences[-1]} "
        f"missing_inside_range={missing} duplicates={len(sequences) - len(set(sequences))}"
    )

    new_ble_rows = [row for row in rows if row.get("new_ble_sample", "1") == "1"]
    metric(
        new_ble_rows,
        "ble_to_send_ms",
        " ms",
        "new_ble_to_first_send_ms",
    )
    metric(rows, "udp_rtt_ms", " ms")
    metric(
        new_ble_rows,
        "ble_to_ack_ms",
        " ms",
        "new_ble_to_first_ack_ms",
    )
    metric(rows, "receiver_processing_us", " us")

    f1_rows = sum(row.get("f1_held") == "1" for row in rows)
    raw_axes_mode = any(row.get("control_mode") == "raw_axes" for row in rows)
    signal_names = ("lx", "ly", "rx", "ry") if raw_axes_mode else ("vx", "vy", "yaw")
    nonzero = sum(
        any(abs(float(row.get(name, "0"))) > 1e-9 for name in signal_names)
        for row in rows
    )
    unsafe = sum(
        row.get("deadman_required", "1") == "1"
        and row.get("f1_held") != "1"
        and any(abs(float(row.get(name, "0"))) > 1e-9 for name in signal_names)
        for row in rows
    )
    move_flags = sum(
        (int(row.get("ack_flags", "0"), 0) & 0x1) != 0 for row in rows
    )
    action_flags = sum(
        (int(row.get("ack_flags", "0"), 0) & 0x2) != 0 for row in rows
    )
    superseded_flags = sum(
        (int(row.get("ack_flags", "0"), 0) & 0x4) != 0 for row in rows
    )
    print(
        f"f1 packets={f1_rows} "
        f"nonzero {'raw-axis packets' if raw_axes_mode else 'commands'}={nonzero} "
        f"nonzero_without_required_enable={unsafe} "
        f"robot_move_ack_flags={move_flags} robot_action_ack_flags={action_flags} "
        f"superseded_ack_flags={superseded_flags}"
    )

    if raw_axes_mode:
        maxima = {
            name: max(abs(float(row.get(name, "0"))) for row in rows)
            for name in ("lx", "ly", "rx", "ry")
        }
        print(
            "control_mode=raw_axes mapping=unitree_receiver "
            + " ".join(f"max_abs_{name}={value:.3f}" for name, value in maxima.items())
        )

    if not raw_axes_mode and "gait" in rows[0] and "speed_level" in rows[0]:
        profiles = Counter(
            (row.get("gait", ""), row.get("speed_level", "")) for row in rows
        )
        print(
            "profiles: "
            + ", ".join(
                f"{gait}/{speed}={count}"
                for (gait, speed), count in sorted(profiles.items())
            )
        )
        max_vx = max(abs(float(row["vx"])) for row in rows)
        max_vy = max(abs(float(row["vy"])) for row in rows)
        max_yaw = max(abs(float(row["yaw"])) for row in rows)
        print(
            f"max_abs_command: vx={max_vx:.3f} vy={max_vy:.3f} yaw={max_yaw:.3f}"
        )
        for gait, speed in sorted(profiles):
            profile_rows = [
                row
                for row in rows
                if row.get("gait") == gait and row.get("speed_level") == speed
            ]
            profile_vx = max(abs(float(row["vx"])) for row in profile_rows)
            profile_vy = max(abs(float(row["vy"])) for row in profile_rows)
            profile_yaw = max(abs(float(row["yaw"])) for row in profile_rows)
            print(
                f"profile_max {gait}/{speed}: vx={profile_vx:.3f} "
                f"vy={profile_vy:.3f} yaw={profile_yaw:.3f}"
            )

    action_rows = [
        row for row in rows if int(row.get("ack_flags", "0"), 0) & 0x2
    ]
    for row in action_rows[:30]:
        print(
            f"action seq={row.get('seq', '')} "
            f"buttons={row.get('buttons', row.get('button_mask', '')) or '-'} "
            f"mask={row.get('button_mask', '-')} ret={row.get('ack_result', '')}"
        )


if __name__ == "__main__":
    main()
