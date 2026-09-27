#!/bin/bash
# run_web.sh - Khởi động web app nhanh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source venv/bin/activate
export OMP_NUM_THREADS=4
python app_pi_realtime.py
