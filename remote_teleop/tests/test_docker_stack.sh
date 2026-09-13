#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

test_combined_stack_waits_for_docker_receiver() {
    local root="$TMP/pc1"
    mkdir -p "$root/bin" "$root/logs"
    cp "$SOURCE_ROOT/start_stack_ble_pc_remote.sh" "$root/"
    chmod +x "$root/start_stack_ble_pc_remote.sh"

    cat >"$root/pc1_ble_docker.py" <<'PY'
import os
import sys
import time

with open(os.environ["TEST_EVENTS"], "a", encoding="utf-8") as stream:
    stream.write("docker " + " ".join(sys.argv[1:]) + "\n")
print("TELEOP_READY", flush=True)
time.sleep(10)
PY

    cat >"$root/launch_pc1_operation.sh" <<'SH'
#!/usr/bin/env bash
echo arm >>"$TEST_EVENTS"
sleep 10
SH
    chmod +x "$root/launch_pc1_operation.sh"

    cat >"$root/bin/python.exe" <<'SH'
#!/usr/bin/env bash
echo "ble $*" >>"$TEST_EVENTS"
sleep 0.2
SH
    chmod +x "$root/bin/python.exe"

    cat >"$root/bin/ssh" <<'SH'
#!/usr/bin/env bash
exit 0
SH
    cat >"$root/bin/scp" <<'SH'
#!/usr/bin/env bash
echo "scp $*" >>"$TEST_EVENTS"
exit 0
SH
    chmod +x "$root/bin/ssh" "$root/bin/scp"

    : >"$root/events"
    set +e
    PATH="$root/bin:$PATH" \
    TEST_EVENTS="$root/events" \
    ARM_REAL_CONTROL=YES A2_REAL_CONTROL=YES \
    DURATION_SEC=30 UNITREE_HOST=unitree-robot \
    UNITREE_WIFI_IP=192.168.124.162 PC1_WIFI_IP=192.168.124.66 \
    WINDOWS_PYTHON="$root/bin/python.exe" WINDOWS_BLE_SCRIPT='D:\\sender.py' \
        timeout 12 "$root/start_stack_ble_pc_remote.sh" \
        >"$root/output" 2>&1
    local status=$?
    set -e

    [[ "$status" -eq 0 ]] || {
        cat "$root/output" >&2
        fail "combined launcher did not complete through the Docker receiver path"
    }
    grep -q '^docker --robot unitree-robot --pc1-ip 192.168.124.66 --real-control$' \
        "$root/events" || fail "Docker receiver arguments were not forwarded"
    grep -q '^arm$' "$root/events" || fail "arm/video stack was not started"
    grep -q '^ble .*--target 192.168.124.162' "$root/events" || \
        fail "Windows BLE sender was not started with the Unitree address"
    ! grep -q 'a2_network_bridge' "$root/events" || \
        fail "legacy receiver binary was still deployed"
}

test_missing_optional_cameras_do_not_stop_control() {
    local home="$TMP/unitree-home"
    local root="$home/arm_remote"
    mkdir -p "$root/logs" "$TMP/unitree-bin"
    cp "$SOURCE_ROOT/unitree_launch_services.sh" "$root/"

    cat >"$root/unitree_follower_receiver.py" <<'PY'
import time
time.sleep(2)
PY
    cat >"$TMP/unitree-bin/gst-launch-1.0" <<'SH'
#!/usr/bin/env bash
sleep 10
SH
    chmod +x "$TMP/unitree-bin/gst-launch-1.0"

    HOME="$home" PATH="$TMP/unitree-bin:$PATH" ENABLE_ARM=0 ENABLE_VIDEO=1 \
      WRIST_DEVICE=/definitely/missing DURATION_SEC=2 \
      bash "$root/unitree_launch_services.sh" >"$TMP/unitree-output" 2>&1 || {
        cat "$TMP/unitree-output" >&2
        fail "an optional camera stopped the Unitree control service"
      }

    grep -q 'WARNING.*wrist camera' "$TMP/unitree-output" || \
        fail "missing wrist camera warning was not logged"
    grep -q 'WARNING.*arm-view camera' "$TMP/unitree-output" || \
        fail "missing arm-view camera warning was not logged"
    grep -q '^READY ' "$TMP/unitree-output" || \
        fail "control receiver never became ready"
}

test_dashboard_failure_does_not_stop_arm_control() {
    local home="$TMP/pc1-operation-home"
    local root="$TMP/pc1-operation"
    mkdir -p "$root" "$TMP/pc1-operation-bin" \
        "$home/.cache/huggingface/lerobot/calibration/teleoperators/so_leader" \
        "$home/robot_ws/lerobot/.venv/bin"
    cp "$SOURCE_ROOT/launch_pc1_operation.sh" "$root/"
    : >"$root/leader-device"
    : >"$home/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/aloha_leader.json"

    cat >"$home/robot_ws/lerobot/.venv/bin/python" <<'SH'
#!/usr/bin/env bash
echo leader-start >>"$TEST_EVENTS"
sleep 1
echo leader-done >>"$TEST_EVENTS"
SH
    cat >"$root/video_dashboard.sh" <<'SH'
#!/usr/bin/env bash
echo dashboard-failed >>"$TEST_EVENTS"
exit 7
SH
    cat >"$TMP/pc1-operation-bin/ssh" <<'SH'
#!/usr/bin/env bash
if [[ " $* " == *" true "* ]]; then
    exit 0
fi
sleep 10
SH
    cat >"$TMP/pc1-operation-bin/scp" <<'SH'
#!/usr/bin/env bash
exit 0
SH
    cat >"$TMP/pc1-operation-bin/gst-inspect-1.0" <<'SH'
#!/usr/bin/env bash
exit 0
SH
    chmod +x "$home/robot_ws/lerobot/.venv/bin/python" \
        "$root/video_dashboard.sh" "$TMP/pc1-operation-bin/ssh" \
        "$TMP/pc1-operation-bin/scp" "$TMP/pc1-operation-bin/gst-inspect-1.0"

    : >"$root/events"
    HOME="$home" PATH="$TMP/pc1-operation-bin:$PATH" \
      TEST_EVENTS="$root/events" LEADER_PORT="$root/leader-device" \
      PC1_IP=192.168.124.66 UNITREE_WIFI_IP=192.168.124.162 \
      UNITREE_HOST=unitree-robot ARM_REAL_CONTROL=YES \
      bash "$root/launch_pc1_operation.sh" --enable-arm --duration 3 \
      >"$root/output" 2>&1 || true

    grep -q '^dashboard-failed$' "$root/events" || \
        fail "dashboard failure fixture did not execute"
    grep -q '^leader-done$' "$root/events" || \
        fail "dashboard failure terminated otherwise healthy arm control"
}

test_explicit_uvc_arm_camera_uses_generic_sender() {
    local home="$TMP/unitree-uvc-home"
    local root="$home/arm_remote"
    local camera="$TMP/new-camera"
    mkdir -p "$root/logs" "$TMP/unitree-uvc-bin"
    cp "$SOURCE_ROOT/unitree_launch_services.sh" "$root/"
    : >"$camera"

    cat >"$root/unitree_follower_receiver.py" <<'PY'
import time
time.sleep(2)
PY
    cat >"$root/unitree_uvc_camera_sender.sh" <<'SH'
#!/usr/bin/env bash
echo "uvc device=$CAMERA_DEVICE output=${OUTPUT_WIDTH}x${OUTPUT_HEIGHT}@${OUTPUT_FPS} port=$VIDEO_PORT" >>"$TEST_EVENTS"
sleep 10
SH
    cat >"$TMP/unitree-uvc-bin/gst-launch-1.0" <<'SH'
#!/usr/bin/env bash
sleep 10
SH
    chmod +x "$root/unitree_uvc_camera_sender.sh" \
        "$TMP/unitree-uvc-bin/gst-launch-1.0"

    : >"$TMP/uvc-events"
    HOME="$home" PATH="$TMP/unitree-uvc-bin:$PATH" TEST_EVENTS="$TMP/uvc-events" \
      ENABLE_ARM=0 ENABLE_VIDEO=1 WRIST_DEVICE=/definitely/missing \
      ARM_VIEW_MODE=uvc ARM_VIEW_DEVICE="$camera" DURATION_SEC=2 \
      bash "$root/unitree_launch_services.sh" >"$TMP/uvc-output" 2>&1 || {
        cat "$TMP/uvc-output" >&2
        fail "explicit generic UVC arm-view camera stopped control"
      }

    grep -q "^uvc device=$camera output=480x270@20 port=17202$" \
        "$TMP/uvc-events" || fail "generic UVC sender did not receive the selected camera settings"
}

test_main_relay_does_not_receive_shell_status_argument() {
    local home="$TMP/unitree-main-video-home"
    local root="$home/arm_remote"
    mkdir -p "$root/logs" "$TMP/unitree-main-video-bin"
    cp "$SOURCE_ROOT/unitree_launch_services.sh" "$root/"

    cat >"$root/unitree_follower_receiver.py" <<'PY'
import time
time.sleep(1)
PY
    cat >"$TMP/unitree-main-video-bin/gst-launch-1.0" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$@" >>"$TEST_GST_ARGS"
sleep 0.2
SH
    chmod +x "$TMP/unitree-main-video-bin/gst-launch-1.0"

    : >"$TMP/main-video-gst-args"
    HOME="$home" PATH="$TMP/unitree-main-video-bin:$PATH" \
      TEST_GST_ARGS="$TMP/main-video-gst-args" ENABLE_ARM=0 ENABLE_VIDEO=1 \
      WRIST_DEVICE=/definitely/missing ARM_VIEW_MODE=none DURATION_SEC=1 \
      bash "$root/unitree_launch_services.sh" >"$TMP/main-video-output" 2>&1 || true

    grep -q '^udpsink$' "$TMP/main-video-gst-args" || \
        fail "main video relay did not invoke GStreamer"
    ! grep -q '^status=' "$TMP/main-video-gst-args" || \
        fail "shell status assignment leaked into GStreamer arguments"
}

test_delayed_explicit_wrist_camera_is_started() {
    local home="$TMP/unitree-delayed-wrist-home"
    local root="$home/arm_remote"
    local camera="$TMP/delayed-wrist-camera"
    mkdir -p "$root/logs" "$TMP/unitree-delayed-wrist-bin"
    cp "$SOURCE_ROOT/unitree_launch_services.sh" "$root/"

    cat >"$root/unitree_follower_receiver.py" <<'PY'
import time
time.sleep(1)
PY
    cat >"$TMP/unitree-delayed-wrist-bin/gst-launch-1.0" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$@" >>"$TEST_GST_ARGS"
sleep 2
SH
    chmod +x "$TMP/unitree-delayed-wrist-bin/gst-launch-1.0"

    : >"$TMP/delayed-wrist-gst-args"
    ( sleep 0.2; : >"$camera" ) &
    HOME="$home" PATH="$TMP/unitree-delayed-wrist-bin:$PATH" \
      TEST_GST_ARGS="$TMP/delayed-wrist-gst-args" ENABLE_ARM=0 ENABLE_VIDEO=1 \
      WRIST_DEVICE="$camera" ARM_VIEW_MODE=none CAMERA_DETECT_TIMEOUT_SEC=1 \
      DURATION_SEC=1 bash "$root/unitree_launch_services.sh" \
      >"$TMP/delayed-wrist-output" 2>&1 || true

    grep -q "^device=$camera$" "$TMP/delayed-wrist-gst-args" || \
        fail "wrist sender did not wait for the delayed camera node"
}

test_delayed_explicit_arm_camera_is_started() {
    local home="$TMP/unitree-delayed-arm-home"
    local root="$home/arm_remote"
    local camera="$TMP/delayed-arm-camera"
    mkdir -p "$root/logs" "$TMP/unitree-delayed-arm-bin"
    cp "$SOURCE_ROOT/unitree_launch_services.sh" "$root/"

    cat >"$root/unitree_follower_receiver.py" <<'PY'
import time
time.sleep(1)
PY
    cat >"$root/unitree_uvc_camera_sender.sh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$CAMERA_DEVICE" >>"$TEST_ARM_CAMERA"
sleep 2
SH
    cat >"$TMP/unitree-delayed-arm-bin/gst-launch-1.0" <<'SH'
#!/usr/bin/env bash
sleep 2
SH
    chmod +x "$root/unitree_uvc_camera_sender.sh" \
        "$TMP/unitree-delayed-arm-bin/gst-launch-1.0"

    : >"$TMP/delayed-arm-camera-result"
    ( sleep 0.2; : >"$camera" ) &
    HOME="$home" PATH="$TMP/unitree-delayed-arm-bin:$PATH" \
      TEST_ARM_CAMERA="$TMP/delayed-arm-camera-result" ENABLE_ARM=0 ENABLE_VIDEO=1 \
      WRIST_DEVICE=/definitely/missing ARM_VIEW_MODE=uvc ARM_VIEW_DEVICE="$camera" \
      CAMERA_DETECT_TIMEOUT_SEC=1 DURATION_SEC=1 \
      bash "$root/unitree_launch_services.sh" >"$TMP/delayed-arm-output" 2>&1 || true

    grep -qx "$camera" "$TMP/delayed-arm-camera-result" || \
        fail "arm-view sender did not wait for the delayed camera node"
}

test_dashboard_waits_for_first_camera_packet() {
    command -v gst-launch-1.0 >/dev/null || fail "GStreamer is required for dashboard lifecycle test"
    local root="$TMP/dashboard-wait"
    mkdir -p "$root"
    cp "$SOURCE_ROOT/video_dashboard.sh" "$root/"
    cat >"$root/dashboard_viewer.py" <<'PY'
import sys
while sys.stdin.buffer.read(65536):
    pass
PY

    set +e
    MAIN_PORT=28200 WRIST_PORT=28201 ARM_VIEW_PORT=28202 \
      timeout 2 "$root/video_dashboard.sh" >"$TMP/dashboard-wait-output" 2>&1
    local status=$?
    set -e

    [[ "$status" -eq 124 ]] || {
        cat "$TMP/dashboard-wait-output" >&2
        fail "dashboard exited before any camera packet arrived (status=$status)"
    }
}

test_unitree_service_cleanup_terminates_video_descendants() {
    local home="$TMP/unitree-cleanup-home"
    local root="$home/arm_remote"
    mkdir -p "$root/logs" "$TMP/unitree-cleanup-bin"
    cp "$SOURCE_ROOT/unitree_launch_services.sh" "$root/"

    cat >"$root/unitree_follower_receiver.py" <<'PY'
import time
time.sleep(1)
PY
    cat >"$TMP/unitree-cleanup-bin/gst-launch-1.0" <<'SH'
#!/usr/bin/env bash
sleep 30 &
child=$!
echo "$child" >>"$TEST_VIDEO_CHILDREN"
wait "$child"
SH
    chmod +x "$TMP/unitree-cleanup-bin/gst-launch-1.0"

    : >"$TMP/video-children"
    HOME="$home" PATH="$TMP/unitree-cleanup-bin:$PATH" \
      TEST_VIDEO_CHILDREN="$TMP/video-children" ENABLE_ARM=0 ENABLE_VIDEO=1 \
      WRIST_DEVICE=/definitely/missing ARM_VIEW_MODE=none DURATION_SEC=1 \
      bash "$root/unitree_launch_services.sh" >"$TMP/unitree-cleanup-output" 2>&1 || true

    local leaked=0 pid
    while read -r pid; do
        [[ -n "$pid" ]] || continue
        if kill -0 "$pid" 2>/dev/null; then
            leaked=1
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done <"$TMP/video-children"
    [[ "$leaked" -eq 0 ]] || \
        fail "Unitree service cleanup left a video descendant running"
}

test_combined_stack_waits_for_docker_receiver
test_missing_optional_cameras_do_not_stop_control
test_dashboard_failure_does_not_stop_arm_control
test_explicit_uvc_arm_camera_uses_generic_sender
test_main_relay_does_not_receive_shell_status_argument
test_delayed_explicit_wrist_camera_is_started
test_delayed_explicit_arm_camera_is_started
test_dashboard_waits_for_first_camera_packet
test_unitree_service_cleanup_terminates_video_descendants
echo "PASS: Docker teleop integration and optional-camera degradation"
