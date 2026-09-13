#!/usr/bin/env bash
# Unitree: X5 full panorama -> saved/runtime-adjustable perspective -> H.264/RTP.

set -Eeuo pipefail

PC1_IP="${PC1_IP:-172.18.21.232}"
UNITREE_WIFI_IP="${UNITREE_WIFI_IP:-172.18.20.152}"
VIDEO_PORT="${VIDEO_PORT:-17203}"
PAYLOAD_TYPE="${PAYLOAD_TYPE:-98}"
ZMQ_PORT="${ZMQ_PORT:-5555}"
DURATION_SEC="${DURATION_SEC:-300}"
BITRATE_KBPS="${BITRATE_KBPS:-2500}"
YAW="${YAW:-180}"
PITCH="${PITCH:-0}"
ROLL="${ROLL:-0}"
H_FOV="${H_FOV:-100}"
V_FOV="${V_FOV:-67.67}"
OUTPUT_WIDTH="${OUTPUT_WIDTH:-1280}"
OUTPUT_HEIGHT="${OUTPUT_HEIGHT:-720}"
OUTPUT_FPS="${OUTPUT_FPS:-30}"

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

CURRENT_PID=""
TIMER_PID=""
cleanup() {
    trap - EXIT INT TERM HUP
    for pid in "$CURRENT_PID" "$TIMER_PID"; do
        [[ -n "$pid" ]] && kill -INT "$pid" 2>/dev/null || true
    done
    sleep 0.2
    for pid in "$CURRENT_PID" "$TIMER_PID"; do
        [[ -n "$pid" ]] && kill -TERM "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

echo "preset yaw=$YAW pitch=$PITCH roll=$ROLL h_fov=$H_FOV v_fov=$V_FOV"
echo "RTP -> ${PC1_IP}:${VIDEO_PORT}; live controls tcp://0.0.0.0:${ZMQ_PORT}"

deadline=$(( $(date +%s) + DURATION_SEC ))
ready_printed=0
restart_count=0

while (( $(date +%s) < deadline )); do
    DEVICE="${INSTA360_DEVICE:-}"
    if [[ -z "$DEVICE" || ! -r "$DEVICE" ]]; then
        DEVICE=""
        for _ in {1..20}; do
            DEVICE="$(find_x5_capture_device || true)"
            [[ -n "$DEVICE" && -r "$DEVICE" ]] && break
            DEVICE=""
            sleep 0.5
        done
    fi
    if [[ -z "$DEVICE" || ! -r "$DEVICE" ]]; then
        restart_count=$((restart_count + 1))
        echo "Insta360 X5 is still unavailable after 10 seconds; control remains active and video recovery will continue (retry=$restart_count)." >&2
        continue
    fi

    echo "X5=$DEVICE panorama=2880x1440@30 output=${OUTPUT_WIDTH}x${OUTPUT_HEIGHT}@${OUTPUT_FPS} restart=$restart_count"
    ffmpeg -hide_banner -loglevel fatal -nostats \
        -thread_queue_size 8 \
        -f v4l2 -input_format mjpeg -video_size 2880x1440 -framerate 30 -i "$DEVICE" \
        -vf "setpts=N/(30*TB),realtime,fps=fps=${OUTPUT_FPS}:round=near,v360@view=input=equirect:output=flat:w=${OUTPUT_WIDTH}:h=${OUTPUT_HEIGHT}:yaw=${YAW}:pitch=${PITCH}:roll=${ROLL}:h_fov=${H_FOV}:v_fov=${V_FOV}:interp=linear,zmq=bind_address='tcp\\://0.0.0.0\\:${ZMQ_PORT}'" \
        -an -c:v libx264 -preset ultrafast -tune zerolatency \
        -b:v "${BITRATE_KBPS}k" -maxrate "${BITRATE_KBPS}k" -bufsize 200k \
        -g 10 -keyint_min 10 -sc_threshold 0 -bf 0 -threads 4 \
        -x264-params repeat-headers=1:annexb=1:scenecut=0 \
        -payload_type "$PAYLOAD_TYPE" -flush_packets 1 \
        -f rtp "rtp://${PC1_IP}:${VIDEO_PORT}?pkt_size=1200&buffer_size=262144&dscp=34" &
    CURRENT_PID=$!

    sleep 1
    if ! kill -0 "$CURRENT_PID" 2>/dev/null; then
        set +e
        wait "$CURRENT_PID"
        status=$?
        set -e
        CURRENT_PID=""
        restart_count=$((restart_count + 1))
        echo "X5 sender exited during startup (status=$status); waiting for USB recovery, restart=$restart_count." >&2
        sleep 0.5
        continue
    fi

    if (( ready_printed == 0 )); then
        echo "READY"
        ready_printed=1
    fi

    remaining=$(( deadline - $(date +%s) ))
    (( remaining > 0 )) || break
    sleep "$remaining" &
    TIMER_PID=$!

    set +e
    wait -n "$CURRENT_PID" "$TIMER_PID"
    set -e

    if kill -0 "$CURRENT_PID" 2>/dev/null; then
        kill -INT "$CURRENT_PID" 2>/dev/null || true
        wait "$CURRENT_PID" 2>/dev/null || true
        CURRENT_PID=""
        TIMER_PID=""
        break
    fi

    set +e
    wait "$CURRENT_PID"
    status=$?
    set -e
    CURRENT_PID=""
    kill "$TIMER_PID" 2>/dev/null || true
    wait "$TIMER_PID" 2>/dev/null || true
    TIMER_PID=""
    restart_count=$((restart_count + 1))
    echo "X5 USB stream ended (status=$status); waiting for re-enumeration, restart=$restart_count." >&2
    sleep 0.5
done
