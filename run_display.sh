#!/bin/bash
# run_display.sh - Khởi động display mode nhanh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source venv/bin/activate
export OMP_NUM_THREADS=4
python camera_pi_realtime.py
