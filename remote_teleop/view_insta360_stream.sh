#!/usr/bin/env bash
# PC1 resizable low-latency Insta360 H.264/RTP viewer.

set -Eeuo pipefail

PORT="${VIDEO_PORT:-17203}"
JITTER_MS="${JITTER_MS:-25}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIFO="$(mktemp -u /tmp/insta360_view.XXXXXX.raw)"
mkfifo "$FIFO"

PIDS=()
cleanup() {
    trap - EXIT INT TERM
    for pid in "${PIDS[@]:-}"; do kill -TERM "$pid" 2>/dev/null || true; done
    wait 2>/dev/null || true
    rm -f "$FIFO"
}
trap cleanup EXIT INT TERM

gst-launch-1.0 -q \
    udpsrc address=0.0.0.0 port="$PORT" buffer-size=262144 \
      caps="application/x-rtp,media=video,encoding-name=H264,payload=98,clock-rate=90000" \
    ! rtpjitterbuffer latency="$JITTER_MS" drop-on-latency=true do-lost=true \
    ! rtph264depay wait-for-keyframe=true request-keyframe=true \
    ! h264parse \
    ! avdec_h264 max-threads=2 output-corrupt=false \
    ! queue leaky=downstream max-size-buffers=1 \
    ! videoconvert \
    ! videoscale method=0 \
    ! video/x-raw,width=1280,height=720,framerate=30/1,format=BGR \
    ! queue leaky=downstream max-size-buffers=1 \
    ! fdsink fd=1 sync=false >"$FIFO" &
PIDS+=("$!")

DASHBOARD_WIDTH=1280 \
DASHBOARD_HEIGHT=720 \
DASHBOARD_WINDOW_WIDTH=1280 \
DASHBOARD_WINDOW_HEIGHT=720 \
DASHBOARD_TITLE="Insta360 X5 - 1080p Low-Latency Stream" \
QT_QPA_FONTDIR=/usr/share/fonts/truetype/dejavu \
    /usr/bin/python3 "$ROOT/dashboard_viewer.py" <"$FIFO" &
PIDS+=("$!")

wait -n "${PIDS[@]}"
