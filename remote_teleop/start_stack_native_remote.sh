#!/usr/bin/env bash
# Version 1:
# Native paired remote -> A2
# PC1 leader -> Unitree -> follower arm
# A2 main + Insta360 arm view + wrist camera -> PC1 dashboard

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DURATION_SEC="${DURATION_SEC:-3600}"

if [[ "${ARM_REAL_CONTROL:-}" != "YES" ]]; then
    echo "Refusing real follower-arm control." >&2
    echo "After supporting the follower and clearing the area, run:" >&2
    echo "  ARM_REAL_CONTROL=YES $0" >&2
    exit 2
fi

echo "VERSION 1: native A2 remote + remote follower arm + three-camera dashboard"
echo "Keep the BLE-to-PC sender OFF; do not run the UDP dog-control receiver."

exec "$ROOT/launch_pc1_operation.sh" \
    --enable-arm \
    --duration "$DURATION_SEC" \
    --fps 100 \
    --max-relative-target 8.0 \
    --startup-max-delta 80 \
    --startup-sync-tolerance 2 \
    "$@"

