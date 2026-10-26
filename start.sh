#!/bin/sh
# Practice mode (simulated data). Use ./start.sh --live for Kite live data.
cd "$(dirname "$0")" && exec python3 run.py "$@"
