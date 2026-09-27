#!/usr/bin/env python3
"""Set TomatoGuard login credentials without storing a plaintext password."""

from getpass import getpass
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile

from werkzeug.security import generate_password_hash


ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9._-]{3,64}\Z")


def main():
    demo_default = sys.argv[1:] == ["--demo-default"]
    if sys.argv[1:] and not demo_default:
        raise SystemExit("Cách dùng: python deploy/set_dashboard_password.py [--demo-default]")
    username = "admin" if demo_default else (input("Tên tài khoản [admin]: ").strip() or "admin")
    if not USERNAME_PATTERN.fullmatch(username):
        raise SystemExit("Tên tài khoản cần 3–64 ký tự chữ, số, dấu chấm, gạch dưới hoặc gạch ngang.")
    if demo_default:
        password = "admin"
    else:
        password = getpass("Mật khẩu mới (ít nhất 12 ký tự): ")
        if len(password) < 12:
            raise SystemExit("Mật khẩu phải có ít nhất 12 ký tự.")
        if password != getpass("Nhập lại mật khẩu: "):
            raise SystemExit("Hai mật khẩu không khớp.")

    replacements = {
        "DASHBOARD_USERNAME": username,
        "DASHBOARD_PASSWORD_HASH": generate_password_hash(password),
        # Rotating this key logs out any sessions from the old password.
        "FLASK_SECRET_KEY": secrets.token_urlsafe(48),
    }
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    output = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in replacements:
            continue
        output.append(line)
    output.extend(f"{key}={value}" for key, value in replacements.items())

    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=ENV_FILE.parent, delete=False) as temp:
        temp.write("\n".join(output) + "\n")
        temp_name = temp.name
    try:
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, ENV_FILE)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

    print("Đã cập nhật tài khoản và mật khẩu băm trong .env; mật khẩu gốc không được lưu.")
    if demo_default:
        print("Tài khoản khởi tạo: admin / admin. Hãy đổi mật khẩu ngay sau khi thử đăng nhập.")
    print("Khởi động lại: sudo systemctl restart tomatoguard")


if __name__ == "__main__":
    main()
