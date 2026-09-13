#!/usr/bin/env bash
# Each decoder runs independently; the UI reads only its latest frame.
set -Eeuo pipefail
exec /usr/bin/python3 "$(dirname "$0")/dashboard_latest.py"
