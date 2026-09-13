#!/usr/bin/env bash
# One-command PC1 launcher: A2 main video + SO-101 teleop + wrist video.

set -Eeuo pipefail

DURATION_SEC=3600
ARM_FPS=100
ENABLE_ARM=0
ENABLE_VIDEO=1
PC1_IP="${PC1_IP:-}"
UNITREE_HOST="${UNITREE_HOST:-unitree-a2-wifi}"
UNITREE_WIFI_IP="${UNITREE_WIFI_IP:-}"
MAIN_VIDEO_PORT=17200
WRIST_VIDEO_PORT=17201
ARM_VIEW_VIDEO_PORT=17202
WRIST_WIDTH=1280
WRIST_HEIGHT=720
WRIST_FPS=20
WRIST_BITRATE_KBPS=700
WRIST_OUTPUT_WIDTH=480
WRIST_OUTPUT_HEIGHT=270
WRIST_JITTER_MS="${WRIST_JITTER_MS:-12}"
ARM_VIEW_WIDTH=480
ARM_VIEW_HEIGHT=270
ARM_VIEW_FPS=20
ARM_VIEW_BITRATE_KBPS=800
ARM_VIEW_INPUT_WIDTH=640
ARM_VIEW_INPUT_HEIGHT=360
ARM_VIEW_INPUT_FPS=30
ARM_VIEW_MODE="${ARM_VIEW_MODE:-uvc}"
ARM_VIEW_DEVICE="${ARM_VIEW_DEVICE:-}"
# A small non-zero budget prevents fragmented H.264 access units from being
# discarded on Wi-Fi without building a visible playback queue.
ARM_VIEW_JITTER_MS="${ARM_VIEW_JITTER_MS:-12}"
INSTA_YAW=180
INSTA_PITCH=0
INSTA_ROLL=0
INSTA_H_FOV=110
INSTA_V_FOV=77.55
ARM_PORT=39101
ARM_MAX_RELATIVE_TARGET=8.0
ARM_STARTUP_MAX_DELTA=25.0
ARM_STARTUP_SYNC_SPEED=30.0
ARM_STARTUP_SYNC_TOLERANCE=2.0

usage() {
    cat <<'EOF'
Usage:
  ./launch_pc1_operation.sh [--duration SEC] [--fps HZ]
      [--max-relative-target VALUE] [--startup-max-delta VALUE]
      [--startup-sync-speed VALUE] [--startup-sync-tolerance VALUE]
      [--wrist-fps VALUE] [--wrist-bitrate-kbps VALUE] [--wrist-jitter-ms VALUE]
      [--arm-view-width VALUE] [--arm-view-height VALUE]
      [--arm-view-fps VALUE] [--arm-view-bitrate-kbps VALUE] [--arm-view-jitter-ms VALUE]
      [--insta-yaw DEG] [--insta-pitch DEG] [--insta-fov DEG]
      [--enable-arm] [--no-video]

Default mode is a complete DRY-RUN: both video windows are real, leader data is
sent for real, but the Unitree receiver does not open the follower serial port.

Real follower control additionally requires:
  ARM_REAL_CONTROL=YES ./launch_pc1_operation.sh --enable-arm
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --duration) DURATION_SEC="$2"; shift 2 ;;
        --fps) ARM_FPS="$2"; shift 2 ;;
        --max-relative-target) ARM_MAX_RELATIVE_TARGET="$2"; shift 2 ;;
        --startup-max-delta) ARM_STARTUP_MAX_DELTA="$2"; shift 2 ;;
        --startup-sync-speed) ARM_STARTUP_SYNC_SPEED="$2"; shift 2 ;;
        --startup-sync-tolerance) ARM_STARTUP_SYNC_TOLERANCE="$2"; shift 2 ;;
        --wrist-fps) WRIST_FPS="$2"; shift 2 ;;
        --wrist-bitrate-kbps) WRIST_BITRATE_KBPS="$2"; shift 2 ;;
        --wrist-jitter-ms) WRIST_JITTER_MS="$2"; shift 2 ;;
        --arm-view-width) ARM_VIEW_WIDTH="$2"; shift 2 ;;
        --arm-view-height) ARM_VIEW_HEIGHT="$2"; shift 2 ;;
        --arm-view-fps) ARM_VIEW_FPS="$2"; shift 2 ;;
        --arm-view-bitrate-kbps) ARM_VIEW_BITRATE_KBPS="$2"; shift 2 ;;
        --arm-view-jitter-ms) ARM_VIEW_JITTER_MS="$2"; shift 2 ;;
        --insta-yaw) INSTA_YAW="$2"; shift 2 ;;
        --insta-pitch) INSTA_PITCH="$2"; shift 2 ;;
        --insta-fov)
            INSTA_H_FOV="$2"
            INSTA_V_FOV="$(
                python3 - "$INSTA_H_FOV" <<'PY'
import math
import sys
h_fov = float(sys.argv[1])
v_fov = math.degrees(2 * math.atan(math.tan(math.radians(h_fov) / 2) * 9 / 16))
print(f"{v_fov:.6f}")
PY
            )"
            shift 2
            ;;
        --enable-arm) ENABLE_ARM=1; shift ;;
        --no-video) ENABLE_VIDEO=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

if [[ "$ENABLE_ARM" == "1" && "${ARM_REAL_CONTROL:-}" != "YES" ]]; then
    echo "Refusing real arm control. Prefix with ARM_REAL_CONTROL=YES." >&2
    exit 2
fi
if [[ ! "$DURATION_SEC" =~ ^[0-9]+$ || "$DURATION_SEC" -lt 1 ]]; then
    echo "--duration must be a positive integer number of seconds." >&2
    exit 2
fi
REMOTE_DURATION_SEC=$((DURATION_SEC + 15))

if [[ -z "$UNITREE_WIFI_IP" ]]; then
    UNITREE_WIFI_IP="$(
        ssh -G "$UNITREE_HOST" 2>/dev/null |
        awk '$1 == "hostname" { print $2; exit }'
    )"
fi
if [[ -z "$PC1_IP" ]]; then
    PC1_IP="$(
        ip route get "$UNITREE_WIFI_IP" |
        awk '{ for (i = 1; i <= NF; ++i) if ($i == "src") { print $(i + 1); exit } }'
    )"
fi
test -n "$UNITREE_WIFI_IP" || {
    echo "Cannot resolve Unitree IP from SSH host: $UNITREE_HOST" >&2
    exit 3
}
test -n "$PC1_IP" || {
    echo "Cannot determine the PC1 source IP used to reach $UNITREE_WIFI_IP" >&2
    exit 3
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/logs"
RUN_TAG="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"

LEADER_PORT="${LEADER_PORT:-/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B3D047743-if00}"
USBIPD_EXE="${USBIPD_EXE:-/mnt/c/Program Files/usbipd-win/usbipd.exe}"
WSL_EXE="${WSL_EXE:-/mnt/c/Windows/System32/wsl.exe}"

find_leader_tty() {
    local tty properties
    for tty in /dev/ttyACM*; do
        [[ -e "$tty" ]] || continue
        properties="$(udevadm info -a -n "$tty" 2>/dev/null || true)"
        grep -q 'ATTRS{idVendor}=="1a86"' <<<"$properties" || continue
        grep -q 'ATTRS{idProduct}=="55d3"' <<<"$properties" || continue
        printf '%s\n' "$tty"
        return 0
    done
    return 1
}

if [[ ! -e "$LEADER_PORT" ]]; then
    detected_leader="$(find_leader_tty || true)"
    if [[ -z "$detected_leader" && -x "$USBIPD_EXE" ]]; then
        echo "PC1 leader is not attached to WSL; attaching USB 1a86:55d3 automatically..."
        set +e
        timeout 12 "$USBIPD_EXE" attach --wsl --hardware-id 1a86:55d3
        attach_status=$?
        set -e
        for _ in {1..20}; do
            detected_leader="$(find_leader_tty || true)"
            [[ -n "$detected_leader" ]] && break
            sleep 0.25
        done
        if [[ -z "$detected_leader" && "$attach_status" -ne 0 ]]; then
            echo "Automatic usbipd attach failed. Run usbipd list in Administrator PowerShell." >&2
        fi
    fi

    if [[ -n "$detected_leader" ]]; then
        # This migrated WSL image currently runs without systemd/udev, so a
        # newly attached ttyACM device arrives as root:root 0600.  Use the
        # Windows WSL launcher to apply the normal dialout permissions without
        # requiring an interactive sudo prompt on every experiment.
        if [[ ! -r "$detected_leader" || ! -w "$detected_leader" ]]; then
            if [[ -x "$WSL_EXE" && -n "${WSL_DISTRO_NAME:-}" ]]; then
                "$WSL_EXE" -d "$WSL_DISTRO_NAME" -u root -- chgrp dialout "$detected_leader" >/dev/null
                "$WSL_EXE" -d "$WSL_DISTRO_NAME" -u root -- chmod 660 "$detected_leader" >/dev/null
            fi
        fi
        echo "Leader by-id link is unavailable; using $detected_leader."
        LEADER_PORT="$detected_leader"
    fi
fi

# usbipd reconnects can leave an already-created by-id target as root:root
# 0600. Repair that case as well, rather than only fixing permissions during
# automatic attachment above.
if [[ -e "$LEADER_PORT" && ( ! -r "$LEADER_PORT" || ! -w "$LEADER_PORT" ) ]]; then
    leader_tty="$(readlink -f "$LEADER_PORT")"
    if [[ -x "$WSL_EXE" && -n "${WSL_DISTRO_NAME:-}" && -n "$leader_tty" ]]; then
        "$WSL_EXE" -d "$WSL_DISTRO_NAME" -u root -- chgrp dialout "$leader_tty" >/dev/null
        "$WSL_EXE" -d "$WSL_DISTRO_NAME" -u root -- chmod 660 "$leader_tty" >/dev/null
    fi
fi

LEADER_CAL="$HOME/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/aloha_leader.json"
LEROBOT_PY="$HOME/robot_ws/lerobot/.venv/bin/python"

test -r "$LEADER_PORT" && test -w "$LEADER_PORT" || {
    echo "PC1 leader serial is missing or inaccessible: $LEADER_PORT" >&2
    exit 3
}
test -r "$LEADER_CAL" || { echo "Missing leader calibration: $LEADER_CAL" >&2; exit 3; }
test -x "$LEROBOT_PY" || { echo "Missing LeRobot Python: $LEROBOT_PY" >&2; exit 3; }
ssh -o BatchMode=yes -o ConnectTimeout=5 "$UNITREE_HOST" true

echo "Deploying current control/video scripts to Unitree..."
scp -q \
    "$ROOT/unitree_launch_services.sh" \
    "$ROOT/unitree_follower_receiver.py" \
    "$ROOT/arm_udp_protocol.py" \
    "$ROOT/so101_bus.py" \
    "$ROOT/unitree_insta360_reframe_sender.sh" \
    "$ROOT/unitree_uvc_camera_sender.sh" \
    "$ROOT/unitree_realsense_sender.py" \
    "$UNITREE_HOST:~/arm_remote/"

if [[ "$ENABLE_VIDEO" == "1" ]]; then
    /usr/bin/python3 -c 'import cv2, numpy' >/dev/null 2>&1 || {
        echo "Missing PC1 Python OpenCV/NumPy for the resizable dashboard." >&2
        exit 3
    }
    for plugin in compositor fdsink rtpjitterbuffer rtph264depay h264parse avdec_h264 videoconvert videoscale; do
        gst-inspect-1.0 "$plugin" >/dev/null 2>&1 || {
            echo "Missing PC1 GStreamer plugin: $plugin" >&2
            exit 3
        }
    done
fi

PIDS=()
CRITICAL_PIDS=()
cleanup() {
    trap - EXIT INT TERM
    for pid in "${PIDS[@]:-}"; do
        kill -INT "$pid" 2>/dev/null || true
    done
    sleep 0.2
    for pid in "${PIDS[@]:-}"; do
        kill -TERM "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    echo "PC1 launch stopped. Logs: $LOG_DIR"
}
trap cleanup EXIT INT TERM

echo "Starting Unitree services over SSH..."
ssh -tt "$UNITREE_HOST" \
    "PC1_IP=$PC1_IP UNITREE_WIFI_IP=$UNITREE_WIFI_IP DURATION_SEC=$REMOTE_DURATION_SEC ENABLE_ARM=$ENABLE_ARM ENABLE_VIDEO=$ENABLE_VIDEO WRIST_WIDTH=$WRIST_WIDTH WRIST_HEIGHT=$WRIST_HEIGHT WRIST_FPS=$WRIST_FPS WRIST_BITRATE_KBPS=$WRIST_BITRATE_KBPS WRIST_OUTPUT_WIDTH=$WRIST_OUTPUT_WIDTH WRIST_OUTPUT_HEIGHT=$WRIST_OUTPUT_HEIGHT ARM_VIEW_VIDEO_PORT=$ARM_VIEW_VIDEO_PORT ARM_VIEW_WIDTH=$ARM_VIEW_WIDTH ARM_VIEW_HEIGHT=$ARM_VIEW_HEIGHT ARM_VIEW_FPS=$ARM_VIEW_FPS ARM_VIEW_BITRATE_KBPS=$ARM_VIEW_BITRATE_KBPS ARM_VIEW_INPUT_WIDTH=$ARM_VIEW_INPUT_WIDTH ARM_VIEW_INPUT_HEIGHT=$ARM_VIEW_INPUT_HEIGHT ARM_VIEW_INPUT_FPS=$ARM_VIEW_INPUT_FPS ARM_VIEW_MODE=$ARM_VIEW_MODE ARM_VIEW_DEVICE=$ARM_VIEW_DEVICE INSTA_YAW=$INSTA_YAW INSTA_PITCH=$INSTA_PITCH INSTA_ROLL=$INSTA_ROLL INSTA_H_FOV=$INSTA_H_FOV INSTA_V_FOV=$INSTA_V_FOV ARM_REAL_CONTROL=${ARM_REAL_CONTROL:-NO} ARM_FPS=$ARM_FPS ARM_PORT=$ARM_PORT ARM_MAX_RELATIVE_TARGET=$ARM_MAX_RELATIVE_TARGET ARM_STARTUP_MAX_DELTA=$ARM_STARTUP_MAX_DELTA ARM_STARTUP_SYNC_SPEED=$ARM_STARTUP_SYNC_SPEED ARM_STARTUP_SYNC_TOLERANCE=$ARM_STARTUP_SYNC_TOLERANCE bash ~/arm_remote/unitree_launch_services.sh" \
    >"$LOG_DIR/unitree_services_${RUN_TAG}.log" 2>&1 &
PIDS+=("$!")
CRITICAL_PIDS+=("$!")

sleep 2
if ! kill -0 "${PIDS[0]}" 2>/dev/null; then
    echo "Unitree services failed to start:" >&2
    sed -n '1,160p' "$LOG_DIR/unitree_services_${RUN_TAG}.log" >&2
    exit 4
fi

if [[ "$ENABLE_VIDEO" == "1" ]]; then
  echo "Opening one resizable three-camera dashboard (Main | Arm / Wrist)..."
  ( set +e
    MAIN_PORT="$MAIN_VIDEO_PORT" \
    WRIST_PORT="$WRIST_VIDEO_PORT" \
    ARM_VIEW_PORT="$ARM_VIEW_VIDEO_PORT" \
    MAIN_JITTER_MS=15 \
    WRIST_JITTER_MS="$WRIST_JITTER_MS" \
    ARM_VIEW_JITTER_MS="$ARM_VIEW_JITTER_MS" \
    ARM_VIEW_FPS="$ARM_VIEW_FPS" \
    DASHBOARD_FPS=20 \
      "$ROOT/video_dashboard.sh"
    status=$?
    echo "WARNING: video dashboard exited (status=$status); arm control remains active." >&2
  ) >"$LOG_DIR/video_dashboard_${RUN_TAG}.log" 2>&1 &
  PIDS+=("$!")
else
  echo "Video disabled: control-only test."
fi

echo "Starting leader sender for ${DURATION_SEC}s at ${ARM_FPS} Hz (enable_arm=${ENABLE_ARM})..."
"$LEROBOT_PY" "$ROOT/pc1_leader_sender.py" \
    --target "$UNITREE_WIFI_IP" \
    --port "$ARM_PORT" \
    --serial "$LEADER_PORT" \
    --calibration "$LEADER_CAL" \
    --fps "$ARM_FPS" \
    --duration "$DURATION_SEC" \
    --csv "$LOG_DIR/arm_sender_${RUN_TAG}.csv" \
    > >(tee "$LOG_DIR/arm_sender_${RUN_TAG}.log") 2>&1 &
PIDS+=("$!")
CRITICAL_PIDS+=("$!")

echo "LAUNCHED run_tag=$RUN_TAG duration=${DURATION_SEC}s enable_arm=$ENABLE_ARM video=$ENABLE_VIDEO"
echo "Startup: hard_limit=$ARM_STARTUP_MAX_DELTA sync_speed=$ARM_STARTUP_SYNC_SPEED tolerance=$ARM_STARTUP_SYNC_TOLERANCE"
echo "Press Ctrl+C once to stop all video and control functions."
wait -n "${CRITICAL_PIDS[@]}"
