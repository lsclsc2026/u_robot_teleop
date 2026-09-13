#!/usr/bin/env bash
set -euo pipefail

BRIDGE="${BRIDGE:-$HOME/a2_joystick_lab/bin/a2_network_bridge}"
PC1_IP="${PC1_IP:-192.168.123.200}"
DURATION_SEC="${DURATION_SEC:-45}"

export LD_LIBRARY_PATH="/opt/unitree_robotics/lib:/opt/unitree_robotics/lib/x86_64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

exec "$BRIDGE" \
  --mode receiver \
  --listen 0.0.0.0 \
  --port 39001 \
  --ack-port 39002 \
  --allowed-source "$PC1_IP" \
  --duration "$DURATION_SEC"
