#!/usr/bin/env bash
set -euo pipefail

if [[ "${A2_REAL_CONTROL:-}" != "YES" ]]; then
  echo "Refusing to start real A2 control."
  echo "After clearing the area, run with: A2_REAL_CONTROL=YES $0"
  exit 2
fi

BRIDGE="${BRIDGE:-$HOME/a2_joystick_lab/bin/a2_network_bridge}"
PC1_IP="${PC1_IP:-192.168.123.200}"
DURATION_SEC="${DURATION_SEC:-15}"
SOFT_TIMEOUT_MS="${SOFT_TIMEOUT_MS:-150}"
HARD_TIMEOUT_MS="${HARD_TIMEOUT_MS:-500}"
SPECIAL_ACTION_ARG=()
if [[ "${A2_NATIVE_SPECIAL_ACTIONS:-}" == "YES" ]]; then
  SPECIAL_ACTION_ARG+=(--enable-special-actions)
fi

export LD_LIBRARY_PATH="/opt/unitree_robotics/lib:/opt/unitree_robotics/lib/x86_64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

exec "$BRIDGE" \
  --mode receiver \
  --interface eth0 \
  --listen 0.0.0.0 \
  --port 39001 \
  --ack-port 39002 \
  --allowed-source "$PC1_IP" \
  --duration "$DURATION_SEC" \
  --command-hz 100 \
  --soft-timeout-ms "$SOFT_TIMEOUT_MS" \
  --hard-timeout-ms "$HARD_TIMEOUT_MS" \
  --axis-deadzone 0.05 \
  --lx-min -1.000 --lx-center 0.000 --lx-max 0.941 \
  --ly-min -0.797 --ly-center 0.000 --ly-max 0.870 \
  --rx-min -0.823 --rx-center 0.000 --rx-max 0.953 \
  --ry-min -1.000 --ry-center 0.000 --ry-max 1.000 \
  --deadman-button none \
  --native-button-map \
  "${SPECIAL_ACTION_ARG[@]}" \
  --enable-robot-command
