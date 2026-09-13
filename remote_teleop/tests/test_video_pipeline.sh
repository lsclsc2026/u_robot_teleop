#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

test_wrist_is_encoded_at_dashboard_resolution() {
    local home="$TMP/wrist-home"
    local root="$home/arm_remote"
    local camera="$TMP/wrist-camera"
    mkdir -p "$root/logs" "$TMP/wrist-bin"
    cp "$SOURCE_ROOT/unitree_launch_services.sh" "$root/"
    : >"$camera"

    cat >"$root/unitree_follower_receiver.py" <<'PY'
import time
time.sleep(1)
PY
    cat >"$TMP/wrist-bin/gst-launch-1.0" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$@" >>"$TEST_GST_ARGS"
sleep 0.1
SH
    chmod +x "$TMP/wrist-bin/gst-launch-1.0"

    : >"$TMP/wrist-gst-args"
    HOME="$home" PATH="$TMP/wrist-bin:$PATH" TEST_GST_ARGS="$TMP/wrist-gst-args" \
      ENABLE_ARM=0 ENABLE_VIDEO=1 WRIST_DEVICE="$camera" ARM_VIEW_MODE=none \
      DURATION_SEC=1 bash "$root/unitree_launch_services.sh" \
      >"$TMP/wrist-output" 2>&1 || true

    grep -Fqx 'video/x-raw,format=I420,width=480,height=270,framerate=20/1' \
      "$TMP/wrist-gst-args" ||
        fail "wrist H.264 pipeline did not use the low-bandwidth 480x270@20 profile"
}

test_arm_view_requests_a_native_realtime_capture_mode() {
    local camera="$TMP/arm-view-camera"
    mkdir -p "$TMP/arm-view-bin"
    : >"$camera"

    cat >"$TMP/arm-view-bin/ffmpeg" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$@" >>"$TEST_FFMPEG_ARGS"
exit 0
SH
    chmod +x "$TMP/arm-view-bin/ffmpeg"

    : >"$TMP/arm-view-ffmpeg-args"
    PATH="$TMP/arm-view-bin:$PATH" TEST_FFMPEG_ARGS="$TMP/arm-view-ffmpeg-args" \
      CAMERA_DEVICE="$camera" PC1_IP=192.0.2.20 DURATION_SEC=1 \
      OUTPUT_WIDTH=640 OUTPUT_HEIGHT=360 OUTPUT_FPS=30 \
      bash "$SOURCE_ROOT/unitree_uvc_camera_sender.sh" \
      >"$TMP/arm-view-output" 2>&1 || true

    grep -Fqx -- '-input_format' "$TMP/arm-view-ffmpeg-args" &&
      grep -Fqx -- 'yuyv422' "$TMP/arm-view-ffmpeg-args" &&
      grep -Fqx -- '-video_size' "$TMP/arm-view-ffmpeg-args" &&
      grep -Fqx -- '640x360' "$TMP/arm-view-ffmpeg-args" &&
      grep -Fqx -- '-framerate' "$TMP/arm-view-ffmpeg-args" ||
        fail "arm-view sender did not request 640x360 YUYV at the target frame rate"
}

test_dashboard_opens_at_native_canvas_size() {
    mkdir -p "$TMP/dashboard-python"
    cat >"$TMP/dashboard-python/cv2.py" <<'PY'
import os

WINDOW_NORMAL = 1
WINDOW_KEEPRATIO = 2
WND_PROP_VISIBLE = 3

def namedWindow(*args):
    pass

def resizeWindow(_title, width, height):
    with open(os.environ["TEST_WINDOW_SIZE"], "w", encoding="utf-8") as stream:
        stream.write(f"{width}x{height}\n")

def destroyAllWindows():
    pass
PY
    cat >"$TMP/dashboard-python/numpy.py" <<'PY'
uint8 = object()
PY

    PYTHONPATH="$TMP/dashboard-python" TEST_WINDOW_SIZE="$TMP/window-size" \
      python3 "$SOURCE_ROOT/dashboard_viewer.py" </dev/null

    grep -qx '1280x480' "$TMP/window-size" ||
      fail "dashboard did not open at the low-overhead 1280x480 canvas size"
}

test_unitree_startup_reaps_a_legacy_duplicate_relay() {
    local home="$TMP/stale-home"
    local root="$home/arm_remote"
    mkdir -p "$root/logs" "$TMP/stale-bin"
    cp "$SOURCE_ROOT/unitree_launch_services.sh" "$root/"

    cat >"$root/unitree_follower_receiver.py" <<'PY'
import time
time.sleep(1)
PY
    cat >"$TMP/stale-bin/gst-launch-1.0" <<'SH'
#!/usr/bin/env bash
sleep 0.1
SH
    chmod +x "$TMP/stale-bin/gst-launch-1.0"

    setsid bash -c \
      'exec -a "gst-launch-1.0 -q udpsrc address=230.1.1.1 port=1720 ! udpsink host=192.0.2.20 port=17200" sleep 30' &
    local stale_pid=$!

    HOME="$home" PATH="$TMP/stale-bin:$PATH" PC1_IP=192.0.2.20 \
      ENABLE_ARM=0 ENABLE_VIDEO=1 WRIST_DEVICE=/definitely/missing \
      ARM_VIEW_MODE=none DURATION_SEC=1 \
      bash "$root/unitree_launch_services.sh" >"$TMP/stale-output" 2>&1 || true

    local still_running=0
    if kill -0 "$stale_pid" 2>/dev/null; then
        still_running=1
        kill -TERM -- "-$stale_pid" 2>/dev/null || true
    fi
    [[ "$still_running" -eq 0 ]] ||
      fail "Unitree startup did not reap an old relay targeting the same UDP port"
}

test_dashboard_uses_small_nonzero_wifi_jitter_budget() {
    local root="$TMP/dashboard-jitter"
    mkdir -p "$root" "$TMP/dashboard-bin"
    cp "$SOURCE_ROOT/video_dashboard.sh" "$root/"
    cat >"$root/dashboard_viewer.py" <<'PY'
raise SystemExit(0)
PY
    cat >"$TMP/dashboard-bin/gst-launch-1.0" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$@" >"$TEST_GST_ARGS"
sleep 1
SH
    chmod +x "$TMP/dashboard-bin/gst-launch-1.0"

    PATH="$TMP/dashboard-bin:$PATH" TEST_GST_ARGS="$TMP/dashboard-jitter-args" \
      bash "$root/video_dashboard.sh" >"$TMP/dashboard-jitter-output" 2>&1 || true

    [[ "$(grep -cx 'latency=12' "$TMP/dashboard-jitter-args")" -eq 2 ]] ||
      fail "wrist and arm-view streams do not use the 12 ms Wi-Fi jitter budget"
}

test_wrist_is_encoded_at_dashboard_resolution
test_arm_view_requests_a_native_realtime_capture_mode
test_dashboard_opens_at_native_canvas_size
test_unitree_startup_reaps_a_legacy_duplicate_relay
test_dashboard_uses_small_nonzero_wifi_jitter_budget
echo "PASS: low-latency video pipeline arguments"
