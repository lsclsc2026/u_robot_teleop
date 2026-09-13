#!/usr/bin/env bash
# Run on the Unitree onboard PC. The PC1 launcher starts and stops this script over SSH.

set -Eeuo pipefail

PC1_IP="${PC1_IP:-172.18.21.232}"
UNITREE_WIFI_IP="${UNITREE_WIFI_IP:-172.18.20.152}"
DURATION_SEC="${DURATION_SEC:-3600}"
ENABLE_ARM="${ENABLE_ARM:-0}"
ENABLE_VIDEO="${ENABLE_VIDEO:-1}"
MAIN_VIDEO_PORT="${MAIN_VIDEO_PORT:-17200}"
WRIST_VIDEO_PORT="${WRIST_VIDEO_PORT:-17201}"
ARM_VIEW_VIDEO_PORT="${ARM_VIEW_VIDEO_PORT:-17202}"
WRIST_WIDTH="${WRIST_WIDTH:-1280}"
WRIST_HEIGHT="${WRIST_HEIGHT:-720}"
WRIST_FPS="${WRIST_FPS:-20}"
WRIST_BITRATE_KBPS="${WRIST_BITRATE_KBPS:-700}"
WRIST_OUTPUT_WIDTH="${WRIST_OUTPUT_WIDTH:-480}"
WRIST_OUTPUT_HEIGHT="${WRIST_OUTPUT_HEIGHT:-270}"
WRIST_DEVICE="${WRIST_DEVICE:-}"
ARM_VIEW_WIDTH="${ARM_VIEW_WIDTH:-480}"
ARM_VIEW_HEIGHT="${ARM_VIEW_HEIGHT:-270}"
ARM_VIEW_FPS="${ARM_VIEW_FPS:-20}"
ARM_VIEW_BITRATE_KBPS="${ARM_VIEW_BITRATE_KBPS:-800}"
ARM_VIEW_INPUT_WIDTH="${ARM_VIEW_INPUT_WIDTH:-640}"
ARM_VIEW_INPUT_HEIGHT="${ARM_VIEW_INPUT_HEIGHT:-360}"
ARM_VIEW_INPUT_FPS="${ARM_VIEW_INPUT_FPS:-30}"
ARM_VIEW_MODE="${ARM_VIEW_MODE:-uvc}"
ARM_VIEW_DEVICE="${ARM_VIEW_DEVICE:-}"
CAMERA_DETECT_TIMEOUT_SEC="${CAMERA_DETECT_TIMEOUT_SEC:-3}"
INSTA_YAW="${INSTA_YAW:-180}"
INSTA_PITCH="${INSTA_PITCH:-0}"
INSTA_ROLL="${INSTA_ROLL:-0}"
INSTA_H_FOV="${INSTA_H_FOV:-110}"
INSTA_V_FOV="${INSTA_V_FOV:-77.55}"
ARM_PORT="${ARM_PORT:-39101}"
ARM_FPS="${ARM_FPS:-100}"
ARM_MAX_RELATIVE_TARGET="${ARM_MAX_RELATIVE_TARGET:-8.0}"
ARM_STARTUP_MAX_DELTA="${ARM_STARTUP_MAX_DELTA:-25.0}"
ARM_STARTUP_SYNC_SPEED="${ARM_STARTUP_SYNC_SPEED:-30.0}"
ARM_STARTUP_SYNC_TOLERANCE="${ARM_STARTUP_SYNC_TOLERANCE:-2.0}"

ROOT="$HOME/arm_remote"
LOG_DIR="$ROOT/logs"
RUN_TAG="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"

is_usb_capture_device() {
    local device="$1" vendor="$2" product="$3" properties
    properties="$(udevadm info -q property -n "$device" 2>/dev/null || true)"
    grep -qx "ID_VENDOR_ID=$vendor" <<<"$properties" &&
        grep -qx "ID_MODEL_ID=$product" <<<"$properties" &&
        grep -q '^ID_V4L_CAPABILITIES=.*:capture:' <<<"$properties"
}

find_usb_capture_device() {
    local vendor="$1" product="$2" device
    for device in /dev/video*; do
        [[ -e "$device" ]] || continue
        if is_usb_capture_device "$device" "$vendor" "$product"; then
            printf '%s\n' "$device"
            return 0
        fi
    done
    return 1
}

find_generic_arm_view_device() {
    local device properties
    for device in /dev/video*; do
        [[ -r "$device" ]] || continue
        properties="$(udevadm info -q property -n "$device" 2>/dev/null || true)"
        grep -q '^ID_V4L_CAPABILITIES=.*:capture:' <<<"$properties" || continue
        # The known wrist camera has its own RTP path and must never be selected
        # as the overview camera.
        if grep -qx 'ID_VENDOR_ID=0c45' <<<"$properties" &&
           grep -qx 'ID_MODEL_ID=64ab' <<<"$properties"; then
            continue
        fi
        printf '%s\n' "$device"
        return 0
    done
    return 1
}

camera_detect_attempts() {
    if [[ "$CAMERA_DETECT_TIMEOUT_SEC" =~ ^[0-9]+$ ]]; then
        printf '%s\n' "$((CAMERA_DETECT_TIMEOUT_SEC * 4))"
    else
        echo "WARNING: invalid CAMERA_DETECT_TIMEOUT_SEC=$CAMERA_DETECT_TIMEOUT_SEC; using 3 seconds." >&2
        printf '%s\n' 12
    fi
}

wait_for_readable_device() {
    local device="$1" attempt attempts
    attempts="$(camera_detect_attempts)"
    for ((attempt = 0; attempt <= attempts; attempt++)); do
        if [[ -r "$device" ]]; then
            printf '%s\n' "$device"
            return 0
        fi
        ((attempt == attempts)) || sleep 0.25
    done
    return 1
}

wait_for_capture_lookup() {
    local attempt attempts device
    attempts="$(camera_detect_attempts)"
    for ((attempt = 0; attempt <= attempts; attempt++)); do
        device="$("$@" || true)"
        if [[ -n "$device" && -r "$device" ]]; then
            printf '%s\n' "$device"
            return 0
        fi
        ((attempt == attempts)) || sleep 0.25
    done
    return 1
}

stop_legacy_video_groups() {
    local escaped_ip="${PC1_IP//./[.]}" own_pgid pid pgid pattern
    local -a patterns=(
        "gst-launch-1.0.*udpsrc address=230[.]1[.]1[.]1.*udpsink host=${escaped_ip} port=${MAIN_VIDEO_PORT}"
        "gst-launch-1.0.*v4l2src.*udpsink host=${escaped_ip} port=${WRIST_VIDEO_PORT}"
        "ffmpeg.*rtp://${escaped_ip}:${ARM_VIEW_VIDEO_PORT}"
    )
    local -A groups=()
    own_pgid="$(ps -o pgid= -p $$ | tr -d ' ')"

    for pattern in "${patterns[@]}"; do
        while read -r pid; do
            [[ -n "$pid" && "$pid" != "$$" ]] || continue
            pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')"
            [[ -n "$pgid" && "$pgid" != "$own_pgid" ]] || continue
            groups["$pgid"]=1
        done < <(pgrep -f -- "$pattern" 2>/dev/null || true)
    done

    ((${#groups[@]} > 0)) || return 0
    echo "WARNING: removing ${#groups[@]} stale video process group(s) from an earlier run." >&2
    for pgid in "${!groups[@]}"; do
        kill -TERM -- "-$pgid" 2>/dev/null || true
    done
    sleep 0.2
    for pgid in "${!groups[@]}"; do
        kill -KILL -- "-$pgid" 2>/dev/null || true
    done
}

PIDS=()
VIDEO_PGIDS=()

start_video_job() {
    local log_file="$1" label="$2"
    shift 2
    VIDEO_LABEL="$label" setsid bash -c '
        set +e
        "$@"
        status=$?
        echo "WARNING: ${VIDEO_LABEL} exited (status=${status}); control remains active." >&2
        exit "$status"
    ' a2-video-job "$@" >"$log_file" 2>&1 &
    local pid=$!
    PIDS+=("$pid")
    VIDEO_PGIDS+=("$pid")
}

cleanup() {
    trap - EXIT INT TERM HUP
    # Each video job owns a separate process group. Signal the complete group,
    # not only its shell wrapper, otherwise gst-launch/ffmpeg becomes orphaned
    # and keeps both the camera and UDP destination busy after SSH disconnects.
    for pgid in "${VIDEO_PGIDS[@]:-}"; do
        kill -INT -- "-$pgid" 2>/dev/null || true
    done
    for pid in "${PIDS[@]:-}"; do
        kill -INT "$pid" 2>/dev/null || true
    done
    sleep 0.2
    for pgid in "${VIDEO_PGIDS[@]:-}"; do
        kill -TERM -- "-$pgid" 2>/dev/null || true
    done
    for pid in "${PIDS[@]:-}"; do
        kill -TERM "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    echo "Unitree services stopped."
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

if [[ "$ENABLE_ARM" == "1" && "${ARM_REAL_CONTROL:-}" != "YES" ]]; then
    echo "Refusing real follower control: ARM_REAL_CONTROL=YES is required." >&2
    exit 2
fi

if [[ "$ENABLE_VIDEO" == "1" ]]; then
  if [[ -z "$WRIST_DEVICE" ]]; then
      WRIST_DEVICE="$(wait_for_capture_lookup find_usb_capture_device 0c45 64ab || true)"
  else
      WRIST_DEVICE="$(wait_for_readable_device "$WRIST_DEVICE" || true)"
  fi

  if [[ -n "$WRIST_DEVICE" && -r "$WRIST_DEVICE" ]]; then
      echo "Detected wrist camera: $WRIST_DEVICE"
  else
      echo "WARNING: wrist camera is missing or unreadable; its dashboard panel will remain black." >&2
      WRIST_DEVICE=""
  fi

  ARM_VIEW_AVAILABLE=0
  case "$ARM_VIEW_MODE" in
    uvc)
      if [[ -z "$ARM_VIEW_DEVICE" ]]; then
          ARM_VIEW_DEVICE="$(wait_for_capture_lookup find_generic_arm_view_device || true)"
      else
          ARM_VIEW_DEVICE="$(wait_for_readable_device "$ARM_VIEW_DEVICE" || true)"
      fi
      if [[ -n "$ARM_VIEW_DEVICE" && -r "$ARM_VIEW_DEVICE" &&
            -x "$ROOT/unitree_uvc_camera_sender.sh" ]]; then
          ARM_VIEW_AVAILABLE=1
          echo "Using generic UVC arm-view camera $ARM_VIEW_DEVICE: ${ARM_VIEW_WIDTH}x${ARM_VIEW_HEIGHT}@${ARM_VIEW_FPS}"
      else
          echo "WARNING: arm-view camera is missing or unreadable; its dashboard panel will remain black." >&2
      fi
      ;;
    insta360)
      if [[ -x "$ROOT/unitree_insta360_reframe_sender.sh" ]]; then
          ARM_VIEW_AVAILABLE=1
          echo "Using Insta360 X5 forward view: ${ARM_VIEW_WIDTH}x${ARM_VIEW_HEIGHT}@${ARM_VIEW_FPS} yaw=${INSTA_YAW} pitch=${INSTA_PITCH} FOV=${INSTA_H_FOV}"
      else
          echo "WARNING: arm-view camera sender is missing; its dashboard panel will remain black." >&2
      fi
      ;;
    none)
      echo "WARNING: arm-view camera is disabled; its dashboard panel will remain black." >&2
      ;;
    *)
      echo "WARNING: unknown ARM_VIEW_MODE=$ARM_VIEW_MODE; arm-view panel will remain black." >&2
      ;;
  esac

  # Old versions stopped only the wrapper shell. Reap any surviving sender
  # targeting this PC/port tuple before opening the cameras again.
  stop_legacy_video_groups

  echo "Starting A2 main camera relay -> ${PC1_IP}:${MAIN_VIDEO_PORT}"
  start_video_job "$LOG_DIR/main_video_${RUN_TAG}.log" "A2 main camera relay" \
    gst-launch-1.0 -q \
    udpsrc address=230.1.1.1 port=1720 multicast-iface=eth0 auto-multicast=true buffer-size=131072 \
      caps="application/x-rtp,media=video,encoding-name=H264" \
    ! udpsink host="$PC1_IP" port="$MAIN_VIDEO_PORT" \
      bind-address="$UNITREE_WIFI_IP" buffer-size=262144 qos-dscp=34 sync=false async=false

  if [[ -n "$WRIST_DEVICE" ]]; then
    echo "Starting wrist camera ${WRIST_WIDTH}x${WRIST_HEIGHT}@${WRIST_FPS} -> ${WRIST_OUTPUT_WIDTH}x${WRIST_OUTPUT_HEIGHT} H.264/RTP -> ${PC1_IP}:${WRIST_VIDEO_PORT}"
    start_video_job "$LOG_DIR/wrist_video_${RUN_TAG}.log" "wrist camera stream" \
      gst-launch-1.0 -q \
      v4l2src device="$WRIST_DEVICE" do-timestamp=true io-mode=mmap \
      ! image/jpeg,width="$WRIST_WIDTH",height="$WRIST_HEIGHT",framerate=30/1 \
      ! queue leaky=downstream max-size-buffers=1 \
      ! jpegdec idct-method=ifast \
      ! videorate drop-only=true \
      ! video/x-raw,framerate="$WRIST_FPS"/1 \
      ! videoscale method=0 \
      ! video/x-raw,format=I420,width="$WRIST_OUTPUT_WIDTH",height="$WRIST_OUTPUT_HEIGHT",framerate="$WRIST_FPS"/1 \
      ! queue leaky=downstream max-size-buffers=1 \
      ! x264enc tune=zerolatency speed-preset=ultrafast bitrate="$WRIST_BITRATE_KBPS" \
        vbv-buf-capacity=20 key-int-max=10 bframes=0 byte-stream=true aud=true \
        sliced-threads=true threads=2 rc-lookahead=0 sync-lookahead=0 \
      ! h264parse config-interval=-1 \
      ! video/x-h264,stream-format=byte-stream,alignment=au \
      ! rtph264pay pt=96 config-interval=-1 aggregate-mode=zero-latency mtu=1200 \
      ! udpsink host="$PC1_IP" port="$WRIST_VIDEO_PORT" bind-address="$UNITREE_WIFI_IP" \
        buffer-size=262144 qos-dscp=34 sync=false async=false
  fi

  if [[ "$ARM_VIEW_AVAILABLE" == "1" && "$ARM_VIEW_MODE" == "insta360" ]]; then
    echo "Starting X5 forward view ${ARM_VIEW_WIDTH}x${ARM_VIEW_HEIGHT}@${ARM_VIEW_FPS} yaw=${INSTA_YAW} pitch=${INSTA_PITCH} FOV=${INSTA_H_FOV} -> ${PC1_IP}:${ARM_VIEW_VIDEO_PORT}"
    start_video_job "$LOG_DIR/arm_view_video_${RUN_TAG}.log" "arm-view camera stream" \
      env PC1_IP="$PC1_IP" UNITREE_WIFI_IP="$UNITREE_WIFI_IP" \
        VIDEO_PORT="$ARM_VIEW_VIDEO_PORT" PAYLOAD_TYPE=97 DURATION_SEC="$DURATION_SEC" \
        BITRATE_KBPS="$ARM_VIEW_BITRATE_KBPS" \
        YAW="$INSTA_YAW" PITCH="$INSTA_PITCH" ROLL="$INSTA_ROLL" \
        H_FOV="$INSTA_H_FOV" V_FOV="$INSTA_V_FOV" \
        OUTPUT_WIDTH="$ARM_VIEW_WIDTH" OUTPUT_HEIGHT="$ARM_VIEW_HEIGHT" \
        OUTPUT_FPS="$ARM_VIEW_FPS" \
        "$ROOT/unitree_insta360_reframe_sender.sh"
  elif [[ "$ARM_VIEW_AVAILABLE" == "1" && "$ARM_VIEW_MODE" == "uvc" ]]; then
    echo "Starting generic UVC arm view ${ARM_VIEW_WIDTH}x${ARM_VIEW_HEIGHT}@${ARM_VIEW_FPS} -> ${PC1_IP}:${ARM_VIEW_VIDEO_PORT}"
    start_video_job "$LOG_DIR/arm_view_video_${RUN_TAG}.log" "arm-view camera supervisor" \
      env CAMERA_DEVICE="$ARM_VIEW_DEVICE" PC1_IP="$PC1_IP" \
        VIDEO_PORT="$ARM_VIEW_VIDEO_PORT" PAYLOAD_TYPE=97 DURATION_SEC="$DURATION_SEC" \
        BITRATE_KBPS="$ARM_VIEW_BITRATE_KBPS" \
        INPUT_WIDTH="$ARM_VIEW_INPUT_WIDTH" INPUT_HEIGHT="$ARM_VIEW_INPUT_HEIGHT" \
        INPUT_FPS="$ARM_VIEW_INPUT_FPS" INPUT_FORMAT=yuyv422 \
        OUTPUT_WIDTH="$ARM_VIEW_WIDTH" OUTPUT_HEIGHT="$ARM_VIEW_HEIGHT" \
        OUTPUT_FPS="$ARM_VIEW_FPS" \
        "$ROOT/unitree_uvc_camera_sender.sh"
  fi
else
  echo "Video disabled: starting arm receiver only."
fi

RECEIVER=(
    "$ROOT/unitree_follower_receiver.py"
    --port "$ARM_PORT"
    --allowed-sender "$PC1_IP"
    --duration "$DURATION_SEC"
    --max-relative-target "$ARM_MAX_RELATIVE_TARGET"
    --startup-max-delta "$ARM_STARTUP_MAX_DELTA"
    --startup-sync-speed "$ARM_STARTUP_SYNC_SPEED"
    --startup-sync-tolerance "$ARM_STARTUP_SYNC_TOLERANCE"
    --csv "$LOG_DIR/arm_receiver_${RUN_TAG}.csv"
)

if [[ "$ENABLE_ARM" == "1" ]]; then
    echo "Starting REAL follower control for ${DURATION_SEC}s"
    export PYTHONPATH="$ROOT/lerobot_src"
    ARM_REAL_CONTROL=YES "$ROOT/.venv/bin/python" "${RECEIVER[@]}" --enable-motors \
        >"$LOG_DIR/arm_receiver_${RUN_TAG}.log" 2>&1 &
else
    echo "Starting follower receiver in DRY-RUN mode for ${DURATION_SEC}s"
    python3 "${RECEIVER[@]}" >"$LOG_DIR/arm_receiver_${RUN_TAG}.log" 2>&1 &
fi
RECEIVER_PID="$!"
PIDS+=("$RECEIVER_PID")

sleep 1
if ! kill -0 "$RECEIVER_PID" 2>/dev/null; then
    echo "The follower control receiver exited during startup. Log: $LOG_DIR/arm_receiver_${RUN_TAG}.log" >&2
    exit 4
fi

echo "READY run_tag=$RUN_TAG arm_fps=$ARM_FPS enable_arm=$ENABLE_ARM"
# Camera processes are auxiliary. A transient USB/video failure must not
# terminate the follower receiver and therefore must not stop dog control.
# The receiver has its own duration and watchdog, so it is the authoritative
# lifetime for this group of Unitree services.
wait "$RECEIVER_PID"
