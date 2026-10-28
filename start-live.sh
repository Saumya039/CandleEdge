#!/usr/bin/env bash
# Live Kite data (read-only, no orders). Asks once for your API key and secret.
cd "$(dirname "$0")" && python3 run.py --live "$@"
