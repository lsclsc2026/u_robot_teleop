#!/usr/bin/env bash
# Version 2:
# Unpaired Unitree remote -> BLE -> Windows PC1 -> UDP/WiFi -> Unitree -> A2
# PC1 leader -> Unitree -> follower arm
# A2 main + generic UVC arm view + wrist camera -> PC1 dashboard

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/logs"
RUN_TAG="$(date +%Y%m%d_%H%M%S)"

DURATION_SEC="${DURATION_SEC:-3600}"
UNITREE_HOST="${UNITREE_HOST:-unitree-a2-wifi}"
UNITREE_WIFI_IP="${UNITREE_WIFI_IP:-}"
PC1_WIFI_IP="${PC1_WIFI_IP:-}"
BLE_ADDRESS="${BLE_ADDRESS:-00:00:00:07:FC:3A}"
BLE_SEND_HZ="${BLE_SEND_HZ:-50}"
INSTA_YAW="${INSTA_YAW:-180}"
INSTA_PITCH="${INSTA_PITCH:-0}"
INSTA_H_FOV="${INSTA_H_FOV:-110}"
ARM_VIEW_MODE="${ARM_VIEW_MODE:-uvc}"
ARM_VIEW_DEVICE="${ARM_VIEW_DEVICE:-}"

WINDOWS_PYTHON="${WINDOWS_PYTHON:-/mnt/c/Users/47487/AppData/Local/Programs/Python/Python310/python.exe}"
WINDOWS_BLE_SCRIPT="${WINDOWS_BLE_SCRIPT:-D:\\unitree_ble_test\\ble_udp_sender.py}"
WINDOWS_CSV="${WINDOWS_CSV:-D:\\unitree_ble_test\\ble_pc_to_a2_${RUN_TAG}.csv}"

DOCKER_TELEOP_ENTRY="${DOCKER_TELEOP_ENTRY:-$ROOT/pc1_ble_docker.py}"
REMOTE_DOCKER_TELEOP_ENTRY="${REMOTE_DOCKER_TELEOP_ENTRY:-/home/unitree/unitree_robot_development/u_robot_move/scripts/pc1_ble_docker.py}"
TELEOP_READY_TIMEOUT_SEC="${TELEOP_READY_TIMEOUT_SEC:-30}"

if [[ "${ARM_REAL_CONTROL:-}" != "YES" || "${A2_REAL_CONTROL:-}" != "YES" ]]; then
    echo "Refusing combined real robot/arm control." >&2
    echo "After clearing the robot area and supporting the follower arm, run:" >&2
    echo "  ARM_REAL_CONTROL=YES A2_REAL_CONTROL=YES $0" >&2
    exit 2
fi
if [[ ! "$DURATION_SEC" =~ ^[0-9]+$ || "$DURATION_SEC" -lt 1 ]]; then
    echo "DURATION_SEC must be a positive integer." >&2
    exit 2
fi

if [[ -z "$UNITREE_WIFI_IP" ]]; then
    UNITREE_WIFI_IP="$(
        ssh -G "$UNITREE_HOST" 2>/dev/null |
        awk '$1 == "hostname" { print $2; exit }'
    )"
fi
if [[ -z "$PC1_WIFI_IP" ]]; then
    PC1_WIFI_IP="$(
        ip route get "$UNITREE_WIFI_IP" |
        awk '{ for (i = 1; i <= NF; ++i) if ($i == "src") { print $(i + 1); exit } }'
    )"
fi
test -n "$UNITREE_WIFI_IP" || {
    echo "Cannot resolve Unitree IP from SSH host: $UNITREE_HOST" >&2
    exit 3
}
test -n "$PC1_WIFI_IP" || {
    echo "Cannot determine the PC1 source IP used to reach $UNITREE_WIFI_IP" >&2
    exit 3
}

mkdir -p "$LOG_DIR"
test -x "$WINDOWS_PYTHON" || {
    echo "Missing Windows Python: $WINDOWS_PYTHON" >&2
    exit 3
}
ssh -o BatchMode=yes -o ConnectTimeout=5 "$UNITREE_HOST" true

if [[ ! -r "$DOCKER_TELEOP_ENTRY" ]]; then
    echo "Fetching Docker teleop PC1 entry from Unitree..."
    scp -q "$UNITREE_HOST:$REMOTE_DOCKER_TELEOP_ENTRY" \
        "$DOCKER_TELEOP_ENTRY.new"
    mv -f "$DOCKER_TELEOP_ENTRY.new" "$DOCKER_TELEOP_ENTRY"
fi
test -r "$DOCKER_TELEOP_ENTRY" || {
    echo "Missing Docker teleop PC1 entry: $DOCKER_TELEOP_ENTRY" >&2
    exit 3
}

echo "VERSION 2: BLE remote -> PC1 -> Unitree -> A2, plus arm control and three videos"
echo "The original A2-paired remote must be powered OFF to avoid two control sources."

PIDS=()
cleanup() {
    trap - EXIT INT TERM
    for pid in "${PIDS[@]:-}"; do
        kill -INT "$pid" 2>/dev/null || true
    done
    sleep 0.3
    for pid in "${PIDS[@]:-}"; do
        kill -TERM "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    echo "Combined stack stopped. Logs: $LOG_DIR"
}
trap cleanup EXIT INT TERM

DOCKER_RECEIVER_LOG="$LOG_DIR/docker_a2_receiver_${RUN_TAG}.log"
echo "Starting Docker A2 UDP motion receiver on 39001/39002..."
PYTHONUNBUFFERED=1 python3 "$DOCKER_TELEOP_ENTRY" \
    --robot "$UNITREE_HOST" \
    --pc1-ip "$PC1_WIFI_IP" \
    --real-control \
    > >(tee "$DOCKER_RECEIVER_LOG") 2>&1 &
PIDS+=("$!")

ready=0
for ((attempt = 0; attempt < TELEOP_READY_TIMEOUT_SEC * 10; ++attempt)); do
    if grep -q 'TELEOP_READY' "$DOCKER_RECEIVER_LOG" 2>/dev/null; then
        ready=1
        break
    fi
    if ! kill -0 "${PIDS[0]}" 2>/dev/null; then
        echo "Docker A2 receiver exited before TELEOP_READY." >&2
        wait "${PIDS[0]}" 2>/dev/null || true
        exit 4
    fi
    sleep 0.1
done
if [[ "$ready" != "1" ]]; then
    echo "Timed out waiting ${TELEOP_READY_TIMEOUT_SEC}s for TELEOP_READY." >&2
    exit 4
fi
echo "Docker A2 receiver is ready."

echo "Starting follower-arm control and the three-camera dashboard..."
ARM_VIEW_MODE="$ARM_VIEW_MODE" ARM_VIEW_DEVICE="$ARM_VIEW_DEVICE" \
ARM_REAL_CONTROL=YES "$ROOT/launch_pc1_operation.sh" \
    --enable-arm \
    --duration "$DURATION_SEC" \
    --fps 100 \
    --max-relative-target 8.0 \
    --startup-max-delta 80 \
    --startup-sync-tolerance 2 \
    --insta-yaw "$INSTA_YAW" \
    --insta-pitch "$INSTA_PITCH" \
    --insta-fov "$INSTA_H_FOV" \
    > >(tee "$LOG_DIR/arm_video_stack_${RUN_TAG}.log") 2>&1 &
PIDS+=("$!")

sleep 4
kill -0 "${PIDS[1]}" 2>/dev/null || {
    echo "Arm/video stack exited during startup." >&2
    exit 4
}

echo "Starting Windows BLE sender: $BLE_ADDRESS -> $UNITREE_WIFI_IP:39001"
"$WINDOWS_PYTHON" "$WINDOWS_BLE_SCRIPT" \
    --address "$BLE_ADDRESS" \
    --target "$UNITREE_WIFI_IP" \
    --duration "$DURATION_SEC" \
    --send-hz "$BLE_SEND_HZ" \
    --no-deadman \
    --csv "$WINDOWS_CSV" \
    > >(tee "$LOG_DIR/ble_sender_${RUN_TAG}.log") 2>&1 &
PIDS+=("$!")

echo "LAUNCHED run_tag=$RUN_TAG duration=${DURATION_SEC}s"
echo "Dog control: BLE/UDP 39001, ACK 39002"
echo "Arm control: UDP 39101"
echo "Video: UDP 17200, 17201, 17202"
echo "Press Ctrl+C once to stop the complete stack."

wait -n "${PIDS[@]}"
