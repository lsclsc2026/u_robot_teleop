#!/usr/bin/env bash
# Generic UVC arm-view camera -> low-latency H.264/RTP. Camera failures are
# non-fatal: keep retrying the same stable device path and leave the PC panel black.

set -Eeuo pipefail

CAMERA_DEVICE="${CAMERA_DEVICE:-}"
PC1_IP="${PC1_IP:-}"
VIDEO_PORT="${VIDEO_PORT:-17202}"
PAYLOAD_TYPE="${PAYLOAD_TYPE:-97}"
DURATION_SEC="${DURATION_SEC:-3600}"
OUTPUT_WIDTH="${OUTPUT_WIDTH:-640}"
OUTPUT_HEIGHT="${OUTPUT_HEIGHT:-360}"
OUTPUT_FPS="${OUTPUT_FPS:-30}"
BITRATE_KBPS="${BITRATE_KBPS:-2500}"
INPUT_WIDTH="${INPUT_WIDTH:-$OUTPUT_WIDTH}"
INPUT_HEIGHT="${INPUT_HEIGHT:-$OUTPUT_HEIGHT}"
INPUT_FPS="${INPUT_FPS:-$OUTPUT_FPS}"
INPUT_FORMAT="${INPUT_FORMAT:-yuyv422}"

[[ -n "$CAMERA_DEVICE" ]] || { echo "CAMERA_DEVICE is required" >&2; exit 2; }
[[ -n "$PC1_IP" ]] || { echo "PC1_IP is required" >&2; exit 2; }

# Select the official SDK only for the explicitly selected D435i USB device.
properties="$(udevadm info -q property -n "$CAMERA_DEVICE" 2>/dev/null || true)"
if grep -qx 'ID_VENDOR_ID=8086' <<<"$properties" &&
   grep -qx 'ID_MODEL_ID=0b3a' <<<"$properties"; then
    export REALSENSE_SERIAL="${REALSENSE_SERIAL:-$(sed -n 's/^ID_SERIAL_SHORT=//p' <<<"$properties")}"
    exec /usr/bin/python3 "$(dirname "$0")/unitree_realsense_sender.py"
fi

deadline=$(( $(date +%s) + DURATION_SEC ))
restart_count=0
echo "Generic UVC camera=$CAMERA_DEVICE input=${INPUT_WIDTH}x${INPUT_HEIGHT}@${INPUT_FPS} ${INPUT_FORMAT} output=${OUTPUT_WIDTH}x${OUTPUT_HEIGHT}@${OUTPUT_FPS}"
echo "RTP -> ${PC1_IP}:${VIDEO_PORT}"

while (( $(date +%s) < deadline )); do
    if [[ ! -r "$CAMERA_DEVICE" ]]; then
        restart_count=$((restart_count + 1))
        echo "WARNING: arm-view camera is unavailable; panel remains black (retry=$restart_count)." >&2
        sleep 1
        continue
    fi

    remaining=$((deadline - $(date +%s)))
    (( remaining > 0 )) || break
    set +e
    timeout --foreground --signal=INT --kill-after=2 "${remaining}s" \
      ffmpeg -hide_banner -loglevel warning -nostats \
        -fflags nobuffer -flags low_delay -thread_queue_size 2 \
        -f v4l2 -input_format "$INPUT_FORMAT" \
        -video_size "${INPUT_WIDTH}x${INPUT_HEIGHT}" -framerate "$INPUT_FPS" \
        -i "$CAMERA_DEVICE" \
        -vf "fps=${OUTPUT_FPS},scale=${OUTPUT_WIDTH}:${OUTPUT_HEIGHT}:force_original_aspect_ratio=decrease:flags=fast_bilinear,pad=${OUTPUT_WIDTH}:${OUTPUT_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p" \
        -an -c:v libx264 -preset ultrafast -tune zerolatency \
        -b:v "${BITRATE_KBPS}k" -maxrate "${BITRATE_KBPS}k" -bufsize 200k \
        -g 10 -keyint_min 10 -sc_threshold 0 -bf 0 -threads 2 \
        -x264-params repeat-headers=1:annexb=1:scenecut=0 \
        -payload_type "$PAYLOAD_TYPE" -flush_packets 1 \
        -f rtp "rtp://${PC1_IP}:${VIDEO_PORT}?pkt_size=1200&buffer_size=262144&dscp=34"
    status=$?
    set -e

    if [[ "$status" -eq 124 || "$status" -eq 137 ]]; then
        break
    fi
    restart_count=$((restart_count + 1))
    echo "WARNING: arm-view camera stream exited (status=$status); control remains active and video will retry (retry=$restart_count)." >&2
    sleep 0.5
done
