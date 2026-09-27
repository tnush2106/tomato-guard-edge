"""Flask API and button event handling, independent of camera/YOLO imports."""

import copy
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

from .hat_client import HatCommandError, HatTimeout, HatUnavailable


class HatService:
    def __init__(self, client, capture_dir, capture_frame, camera_ready=lambda: False,
                 allow_offline_controls=False):
        self.client = client
        self.capture_dir = Path(capture_dir)
        self.capture_frame = capture_frame
        self.camera_ready = camera_ready
        self.allow_offline_controls = allow_offline_controls
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._last_capture = None
        self._capture_error = None
        self._sim_mode = "manual"
        self._sim_relays = {str(i): False for i in (1, 2, 3)}
        self._sim_last_action = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.client.start()
        self._thread = threading.Thread(target=self._event_loop, name="hat-events", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.client.stop()
        if self._thread:
            self._thread.join(timeout=3)

    def snapshot(self):
        state = copy.deepcopy(self.client.snapshot())
        with self._lock:
            connected = state.get("hat", {}).get("connected") is True
            simulated = self.allow_offline_controls and not connected
            if simulated:
                state["relays"] = dict(self._sim_relays)
                state["control_mode"] = self._sim_mode
            state.setdefault("hat", {})["simulated"] = simulated
            state["hat"]["controls_available"] = connected or simulated
            state["hat"]["last_simulated_action"] = self._sim_last_action
            state["last_capture"] = copy.deepcopy(self._last_capture)
            state["last_capture_error"] = self._capture_error
        return state

    def command(self, command, **fields):
        self.client._validate_command(command, fields)
        if self.client.snapshot().get("hat", {}).get("connected") is True:
            return self.client.command(command, **fields)
        if not self.allow_offline_controls:
            return self.client.command(command, **fields)

        command_id = "sim-" + uuid.uuid4().hex
        capture_requested = False
        with self._lock:
            if command == "set_relay":
                if self._sim_mode != "manual":
                    raise HatCommandError("Switch to manual mode before controlling a relay")
                self._sim_relays[str(fields["relay"])] = fields["state"]
            elif command == "set_mode":
                self._sim_mode = fields["mode"]
            elif command == "action":
                self._sim_last_action = fields["action"]
                capture_requested = fields["action"] == "capture"
        if capture_requested:
            self._save_capture(source="web-simulation")
        return {"id": command_id, "ok": True, "simulated": True}

    def _save_capture(self, *, source, event_seq=None):
        if not self.camera_ready():
            raise RuntimeError("Camera is unavailable; no image was saved")
        now = datetime.now(timezone.utc)
        capture_id = uuid.uuid4().hex
        filename = f"hat_{now:%Y%m%dT%H%M%S}_{capture_id}.jpg"
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        target = self.capture_dir / filename
        self.capture_frame(target)
        if not target.is_file() or not target.stat().st_size:
            raise RuntimeError("Camera did not save an image")
        capture = {
            "id": capture_id, "filename": filename,
            "url": f"/captures/{filename}", "created_at": now.isoformat(),
            "source": source,
        }
        if event_seq is not None:
            capture["event_seq"] = event_seq
        with self._lock:
            self._last_capture = capture
            self._capture_error = None

    def process_events(self):
        for event in self.client.drain_events():
            if event["button"] != "capture":
                continue
            try:
                self._save_capture(source="hat", event_seq=event["seq"])
            except Exception as exc:
                with self._lock:
                    self._capture_error = str(exc)

    def _event_loop(self):
        while not self._stop.wait(0.1):
            self.process_events()


def create_hat_blueprint(service):
    blueprint = Blueprint("hat", __name__)

    def failure(message, status):
        return jsonify({"ok": False, "error": message, **service.snapshot()}), status

    def execute(command, **fields):
        try:
            ack = service.command(command, **fields)
            return jsonify({"ok": True, "ack_id": ack["id"], **service.snapshot()})
        except ValueError as exc:
            return failure(str(exc), 400)
        except HatTimeout as exc:
            return failure(str(exc), 504)
        except HatCommandError as exc:
            return failure(str(exc), 409)
        except HatUnavailable as exc:
            return failure(str(exc), 503)
        except RuntimeError as exc:
            return failure(str(exc), 503)

    def body_with(*keys):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != set(keys):
            return None
        return body

    @blueprint.get("/api/hat")
    def hat_status():
        return jsonify(service.snapshot())

    @blueprint.post("/api/relay")
    def relay():
        body = body_with("relay", "state")
        if body is None:
            return failure("Expected JSON with relay and state", 400)
        return execute("set_relay", **body)

    @blueprint.post("/api/hat/mode")
    def mode():
        body = body_with("mode")
        if body is None:
            return failure("Expected JSON with mode", 400)
        return execute("set_mode", **body)

    @blueprint.post("/api/hat/action")
    def action():
        body = body_with("action")
        if body is None:
            return failure("Expected JSON with action", 400)
        if body["action"] == "capture" and not service.camera_ready():
            return failure("Camera is unavailable; no capture command was sent", 503)
        return execute("action", **body)

    @blueprint.get("/captures/<filename>")
    def captured_image(filename):
        if not filename.startswith("hat_") or not filename.endswith(".jpg"):
            return failure("Capture not found", 404)
        return send_from_directory(service.capture_dir, filename)

    return blueprint
