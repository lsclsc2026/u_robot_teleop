#!/usr/bin/env bash
# PC1: live X5 yaw/pitch/roll/FOV calibration and persistent preset.

set -Eeuo pipefail

DURATION_SEC=600
BITRATE_KBPS=2500
JITTER_MS=25
PC1_IP="172.18.21.232"
UNITREE_IP="172.18.20.152"
UNITREE_HOST="unitree-a2-wifi"
VIDEO_PORT=17203
ZMQ_PORT=5555

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
PRESET="$ROOT/insta360_view_preset.json"
LOG_DIR="$ROOT/logs"
RUN_TAG="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"

read -r YAW PITCH ROLL H_FOV V_FOV OUTPUT_WIDTH OUTPUT_HEIGHT < <(
    /usr/bin/python3 - "$PRESET" <<'PY'
import json, math, sys
p=json.load(open(sys.argv[1],encoding='utf-8'))
w=int(p.get('output_width',1280)); h=int(p.get('output_height',720))
hf=float(p.get('h_fov',100.0))
vf=math.degrees(2*math.atan(math.tan(math.radians(hf)/2)*h/w))
print(float(p.get('yaw',0)),float(p.get('pitch',0)),float(p.get('roll',0)),hf,vf,w,h)
PY
)

/usr/bin/python3 -c 'import cv2, numpy' >/dev/null 2>&1 || {
    echo "PC1 requires /usr/bin/python3 OpenCV and NumPy." >&2
    exit 3
}
ssh -o BatchMode=yes -o ConnectTimeout=5 "$UNITREE_HOST" true
scp -q "$ROOT/unitree_insta360_reframe_sender.sh" "$UNITREE_HOST:~/arm_remote/"

FIFO="$(mktemp -u /tmp/insta360_calibration.XXXXXX.raw)"
mkfifo "$FIFO"
PIDS=()
cleanup() {
    trap - EXIT INT TERM
    for pid in "${PIDS[@]:-}"; do kill -TERM "$pid" 2>/dev/null || true; done
    wait 2>/dev/null || true
    rm -f "$FIFO"
    echo "Calibration stopped. Preset: $PRESET"
}
trap cleanup EXIT INT TERM

ssh -tt "$UNITREE_HOST" \
    "PC1_IP=$PC1_IP VIDEO_PORT=$VIDEO_PORT ZMQ_PORT=$ZMQ_PORT DURATION_SEC=$DURATION_SEC BITRATE_KBPS=$BITRATE_KBPS YAW=$YAW PITCH=$PITCH ROLL=$ROLL H_FOV=$H_FOV V_FOV=$V_FOV OUTPUT_WIDTH=$OUTPUT_WIDTH OUTPUT_HEIGHT=$OUTPUT_HEIGHT bash ~/arm_remote/unitree_insta360_reframe_sender.sh" \
    >"$LOG_DIR/insta360_reframe_sender_${RUN_TAG}.log" 2>&1 &
PIDS+=("$!")

sleep 2
if ! kill -0 "${PIDS[0]}" 2>/dev/null || ! grep -q READY "$LOG_DIR/insta360_reframe_sender_${RUN_TAG}.log"; then
    echo "X5 sender failed:" >&2
    cat "$LOG_DIR/insta360_reframe_sender_${RUN_TAG}.log" >&2
    exit 4
fi

gst-launch-1.0 -q \
    udpsrc address=0.0.0.0 port="$VIDEO_PORT" buffer-size=262144 \
      caps="application/x-rtp,media=video,encoding-name=H264,payload=98,clock-rate=90000" \
    ! rtpjitterbuffer latency="$JITTER_MS" drop-on-latency=true do-lost=true \
    ! rtph264depay wait-for-keyframe=true request-keyframe=true \
    ! h264parse \
    ! avdec_h264 max-threads=2 output-corrupt=false \
    ! queue leaky=downstream max-size-buffers=1 \
    ! videoconvert \
    ! videoscale method=0 \
    ! video/x-raw,width=1280,height=720,format=BGR \
    ! queue leaky=downstream max-size-buffers=1 \
    ! fdsink fd=1 sync=false >"$FIFO" &
PIDS+=("$!")

echo "Opening X5 virtual-PTZ calibration panel..."
echo "Adjust sliders, then press S inside the video window to save."
/usr/bin/python3 "$ROOT/insta360_calibration_viewer.py" \
    --control "tcp://${UNITREE_IP}:${ZMQ_PORT}" \
    --preset "$PRESET" <"$FIFO"
