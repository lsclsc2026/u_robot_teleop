#!/usr/bin/env bash
# Run on Unitree: Insta360 X5 UVC -> low-latency H.264/RTP -> PC1.

set -Eeuo pipefail

PC1_IP="${PC1_IP:-172.18.21.232}"
UNITREE_WIFI_IP="${UNITREE_WIFI_IP:-172.18.20.152}"
VIDEO_PORT="${VIDEO_PORT:-17203}"
DURATION_SEC="${DURATION_SEC:-60}"
WIDTH="${WIDTH:-1920}"
HEIGHT="${HEIGHT:-1080}"
FPS="${FPS:-30}"
BITRATE_KBPS="${BITRATE_KBPS:-3500}"

find_x5_capture_device() {
    local device properties
    for device in /dev/video*; do
        [[ -e "$device" ]] || continue
        properties="$(udevadm info -q property -n "$device" 2>/dev/null || true)"
        grep -qx 'ID_VENDOR_ID=2e1a' <<<"$properties" || continue
        grep -qx 'ID_MODEL_ID=0005' <<<"$properties" || continue
        grep -q '^ID_V4L_CAPABILITIES=.*:capture:' <<<"$properties" || continue
        printf '%s\n' "$device"
        return 0
    done
    return 1
}

DEVICE="${INSTA360_DEVICE:-}"
if [[ -z "$DEVICE" ]]; then
    for _ in {1..20}; do
        DEVICE="$(find_x5_capture_device || true)"
        [[ -n "$DEVICE" ]] && break
        sleep 0.5
    done
fi
if [[ -z "$DEVICE" || ! -r "$DEVICE" ]]; then
    echo "Cannot find readable Insta360 X5 UVC capture device (2e1a:0005)." >&2
    exit 3
fi

PIDS=()
cleanup() {
    trap - EXIT INT TERM HUP
    for pid in "${PIDS[@]:-}"; do
        kill -INT "$pid" 2>/dev/null || true
    done
    sleep 0.2
    for pid in "${PIDS[@]:-}"; do
        kill -TERM "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM HUP

echo "Insta360 X5 device: $DEVICE"
echo "Streaming ${WIDTH}x${HEIGHT}@${FPS}, ${BITRATE_KBPS} kbps -> ${PC1_IP}:${VIDEO_PORT}"

gst-launch-1.0 -q \
    v4l2src device="$DEVICE" do-timestamp=true \
    ! image/jpeg,width="$WIDTH",height="$HEIGHT",framerate="$FPS"/1 \
    ! queue leaky=downstream max-size-buffers=1 \
    ! jpegdec \
    ! videoconvert n-threads=2 \
    ! queue leaky=downstream max-size-buffers=1 \
    ! x264enc tune=zerolatency speed-preset=ultrafast bitrate="$BITRATE_KBPS" \
      vbv-buf-capacity=20 key-int-max=10 bframes=0 byte-stream=true aud=true \
      sliced-threads=true rc-lookahead=0 sync-lookahead=0 \
    ! h264parse config-interval=-1 \
    ! video/x-h264,stream-format=byte-stream,alignment=au \
    ! rtph264pay pt=98 config-interval=-1 aggregate-mode=zero-latency mtu=1200 \
    ! udpsink host="$PC1_IP" port="$VIDEO_PORT" bind-address="$UNITREE_WIFI_IP" \
      buffer-size=262144 qos-dscp=34 sync=false async=false &
PIDS+=("$!")

sleep 1
kill -0 "${PIDS[0]}" 2>/dev/null || {
    echo "Insta360 GStreamer sender exited during startup." >&2
    exit 4
}
echo "READY"

sleep "$DURATION_SEC" &
PIDS+=("$!")
wait -n "${PIDS[@]}"
