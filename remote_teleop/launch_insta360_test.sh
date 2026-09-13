#!/usr/bin/env bash
# One command on PC1: deploy sender to Unitree and show an Insta360 X5 stream.

set -Eeuo pipefail

DURATION_SEC=60
BITRATE_KBPS=2500
JITTER_MS=25
UNITREE_HOST="unitree-a2-wifi"
PC1_IP="172.18.21.232"
VIDEO_PORT=17203

while [[ $# -gt 0 ]]; do
    case "$1" in
        --duration) DURATION_SEC="$2"; shift 2 ;;
        --bitrate-kbps) BITRATE_KBPS="$2"; shift 2 ;;
        --jitter-ms) JITTER_MS="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--duration SEC] [--bitrate-kbps KBPS] [--jitter-ms MS]"
            exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/logs"
RUN_TAG="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"

/usr/bin/python3 -c 'import cv2, numpy' >/dev/null 2>&1 || {
    echo "PC1 requires /usr/bin/python3 OpenCV and NumPy." >&2
    exit 3
}
ssh -o BatchMode=yes -o ConnectTimeout=5 "$UNITREE_HOST" true
scp -q "$ROOT/unitree_insta360_reframe_sender.sh" "$UNITREE_HOST:~/arm_remote/"

PIDS=()
cleanup() {
    trap - EXIT INT TERM
    for pid in "${PIDS[@]:-}"; do kill -TERM "$pid" 2>/dev/null || true; done
    wait 2>/dev/null || true
    echo "Insta360 test stopped. Log: $LOG_DIR/insta360_forward_${RUN_TAG}.log"
}
trap cleanup EXIT INT TERM

ssh -tt "$UNITREE_HOST" \
    "PC1_IP=$PC1_IP VIDEO_PORT=$VIDEO_PORT DURATION_SEC=$DURATION_SEC BITRATE_KBPS=$BITRATE_KBPS YAW=180 PITCH=0 ROLL=0 H_FOV=110 V_FOV=77.55 OUTPUT_WIDTH=1280 OUTPUT_HEIGHT=720 bash ~/arm_remote/unitree_insta360_reframe_sender.sh" \
    >"$LOG_DIR/insta360_forward_${RUN_TAG}.log" 2>&1 &
PIDS+=("$!")

ready=0
for _ in {1..30}; do
    if grep -q READY "$LOG_DIR/insta360_forward_${RUN_TAG}.log" 2>/dev/null; then
        ready=1
        break
    fi
    kill -0 "${PIDS[0]}" 2>/dev/null || break
    sleep 0.5
done
if [[ "$ready" != "1" ]]; then
    echo "Insta360 sender failed:" >&2
    cat "$LOG_DIR/insta360_forward_${RUN_TAG}.log" >&2
    exit 4
fi

echo "Opening X5 fixed forward view: 1280x720@30, FOV=110"
VIDEO_PORT="$VIDEO_PORT" JITTER_MS="$JITTER_MS" "$ROOT/view_insta360_stream.sh"
