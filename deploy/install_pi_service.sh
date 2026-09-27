#!/usr/bin/env bash
set -euo pipefail

# Install TomatoGuard as a systemd service on Raspberry Pi OS.
# Run this script as the normal account that owns the project:
#   bash deploy/install_pi_service.sh

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="${SUDO_USER:-$USER}"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"
SERVICE_FILE="/etc/systemd/system/tomatoguard.service"

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Không tìm thấy $PYTHON_BIN"
    echo "Hãy chạy: bash setup_realtime.sh"
    exit 1
fi

if [[ ! -f "$PROJECT_DIR/app_pi_realtime.py" ]]; then
    echo "Không tìm thấy app_pi_realtime.py trong $PROJECT_DIR"
    exit 1
fi

sudo tee "$SERVICE_FILE" >/dev/null <<EOF
[Unit]
Description=TomatoGuard Flask, camera, AI and ESP32 HAT service
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$PROJECT_DIR
Environment=PYTHONUNBUFFERED=1
Environment=OMP_NUM_THREADS=4
EnvironmentFile=-$PROJECT_DIR/.env
ExecStart=$PYTHON_BIN $PROJECT_DIR/app_pi_realtime.py
Restart=on-failure
RestartSec=5
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
EOF

# UART and camera access take effect after the next login/reboot.
sudo usermod -aG dialout,video "$APP_USER"
sudo systemctl daemon-reload
sudo systemctl enable --now tomatoguard.service

echo
echo "Đã cài và khởi động tomatoguard.service"
echo "Trạng thái: sudo systemctl status tomatoguard --no-pager"
echo "Nhật ký:   journalctl -u tomatoguard -f"
echo "Kiểm tra:  curl http://127.0.0.1:5000/healthz"
echo "Hãy khởi động lại Pi nếu tài khoản vừa được thêm vào nhóm dialout/video."
