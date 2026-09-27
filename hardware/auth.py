"""Password login for the local TomatoGuard dashboard and its APIs."""

from collections import deque
from datetime import timedelta
import ipaddress
import os
import secrets
import threading
import time

from flask import jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash


_failures = {}
_failure_lock = threading.Lock()
_WINDOW_SECONDS = 300
_MAX_FAILURES = 10


def _csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _safe_next(value):
    return (value if value and value.startswith("/") and not value.startswith("//")
            and "\\" not in value and not any(ord(char) < 32 for char in value) else "/")


def _failure_key():
    remote = request.remote_addr or "unknown"
    # cloudflared reaches Flask over loopback and supplies the visitor IP.
    # Ignore this header for direct LAN clients, which can forge it.
    if remote in {"127.0.0.1", "::1"}:
        forwarded = request.headers.get("CF-Connecting-IP", "")
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return remote


def _too_many_attempts(key):
    cutoff = time.monotonic() - _WINDOW_SECONDS
    with _failure_lock:
        attempts = _failures.setdefault(key, deque())
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        return len(attempts) >= _MAX_FAILURES


def _record_failure(key):
    with _failure_lock:
        _failures.setdefault(key, deque()).append(time.monotonic())


def _clear_failures(key):
    with _failure_lock:
        _failures.pop(key, None)


def init_auth(app):
    username = os.environ.get("DASHBOARD_USERNAME", "").strip()
    password_hash = os.environ.get("DASHBOARD_PASSWORD_HASH", "").strip()
    secret_key = os.environ.get("FLASK_SECRET_KEY", "").strip()
    configured = bool(username and password_hash and len(secret_key) >= 32)

    # Fail closed when credentials have not yet been generated. The temporary
    # key only lets the login page display its configuration message.
    app.secret_key = secret_key if configured else secrets.token_hex(32)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("DASHBOARD_COOKIE_SECURE", "1") != "0",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )

    @app.before_request
    def require_login():
        if request.endpoint in {"static", "login", "healthz"}:
            return None
        if not configured:
            return jsonify({"error": "Dashboard login is not configured"}), 503
        if session.get("username") != username:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login", next=_safe_next(request.full_path.rstrip("?"))))
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            token = request.headers.get("X-CSRF-Token", "") or request.form.get("csrf_token", "")
            if not token or not secrets.compare_digest(token, session.get("csrf_token") or ""):
                return jsonify({"error": "Invalid CSRF token"}), 403
        return None

    @app.route("/healthz")
    def healthz():
        return jsonify({"ok": True})

    @app.route("/login", methods=["GET", "POST"])
    def login():
        target = _safe_next(request.values.get("next", "/"))
        if not configured:
            return render_template("login.html", configured=False, csrf_token="", error=None, next_path=target), 503
        if request.method == "GET" and session.get("username") == username:
            return redirect(target)
        error = None
        status = 200
        if request.method == "POST":
            form_token = request.form.get("csrf_token", "")
            if not form_token or not secrets.compare_digest(form_token, session.get("csrf_token") or ""):
                error, status = "Phiên đăng nhập đã hết hạn. Vui lòng thử lại.", 403
            elif _too_many_attempts(_failure_key()):
                error, status = "Bạn đã thử quá nhiều lần. Vui lòng đợi 5 phút.", 429
            else:
                supplied_username = request.form.get("username", "")
                supplied_password = request.form.get("password", "")
                valid_user = secrets.compare_digest(supplied_username, username)
                try:
                    valid_password = bool(supplied_password) and check_password_hash(password_hash, supplied_password)
                except ValueError:
                    valid_password = False
                if valid_user and valid_password:
                    _clear_failures(_failure_key())
                    session.clear()
                    session["username"] = username
                    session["csrf_token"] = secrets.token_urlsafe(32)
                    session.permanent = True
                    return redirect(target)
                _record_failure(_failure_key())
                error, status = "Tài khoản hoặc mật khẩu không đúng.", 401
        return render_template("login.html", configured=True, csrf_token=_csrf_token(), error=error, next_path=target), status

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    return _csrf_token
