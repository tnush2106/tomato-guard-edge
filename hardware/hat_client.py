"""Bounded, acknowledged UART transport. Importing this module never opens a port.

Only the worker owns serial I/O. Commands are sent once, are correlated by UUID,
and are never replayed after timeout or reconnection. Telemetry, not an open port
or a heartbeat ACK, establishes that sensor data is live.
"""

import copy
import json
import math
import os
import queue
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field


class HatError(RuntimeError):
    pass


class HatUnavailable(HatError):
    pass


class HatTimeout(HatError):
    pass


class HatCommandError(HatError):
    pass


@dataclass
class _Pending:
    packet: dict
    deadline: float
    done: threading.Event = field(default_factory=threading.Event)
    response: dict | None = None
    error: Exception | None = None


class LineDecoder:
    """Retain fragmented packets, discard oversized packets through their newline."""

    def __init__(self, limit=1024):
        self.limit = limit
        self.buffer = bytearray()
        self.discarding = False

    def feed(self, chunk):
        for byte in chunk:
            if byte == 10:
                if not self.discarding and self.buffer:
                    yield bytes(self.buffer).rstrip(b"\r")
                self.buffer.clear()
                self.discarding = False
            elif not self.discarding:
                if len(self.buffer) >= self.limit:
                    self.buffer.clear()
                    self.discarding = True
                else:
                    self.buffer.append(byte)


def _number(value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        return None
    return value


def _outputs(packet):
    mode = packet.get("mode")
    relays = packet.get("relays")
    if mode not in ("manual", "auto") or not isinstance(relays, dict):
        raise ValueError("Invalid HAT output state")
    if any(type(relays.get(str(i))) is not bool for i in (1, 2, 3)):
        raise ValueError("Invalid HAT relay state")
    return mode, {str(i): relays[str(i)] for i in (1, 2, 3)}


class HatClient:
    def __init__(self, port="/dev/serial0", baudrate=115200, *, enabled=True,
                 stale_after=6.0, command_timeout=2.5, reconnect_after=2.0,
                 serial_factory=None, clock=time.monotonic):
        if baudrate <= 0 or any(not math.isfinite(v) or v <= 0 for v in (stale_after, command_timeout, reconnect_after)):
            raise ValueError("HAT baudrate and timeouts must be positive")
        self.port = port
        self.baudrate = baudrate
        self.enabled = enabled
        self.stale_after = stale_after
        self.command_timeout = command_timeout
        self.reconnect_after = reconnect_after
        self._factory = serial_factory
        self._clock = clock
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._serial = None
        self._pending = {}
        self._outgoing = queue.Queue(maxsize=16)
        self._events = deque(maxlen=32)
        self._event_ids = deque(maxlen=32)
        self._last_seen = None
        self._last_uptime = None
        self._mode = None
        self._outputs_uncertain = True
        self._relays = {str(i): None for i in (1, 2, 3)}
        self._sensors = dict.fromkeys(("temp", "humidity", "light", "soil", "soil_raw"))
        self._sensor_ok = {}
        self._errors = []
        self._last_event = None
        self._selected_relay = None
        self._error = "HAT disabled" if not enabled else "Waiting for HAT telemetry"

    def start(self):
        with self._lock:
            if not self.enabled or (self._thread and self._thread.is_alive()):
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="hat-uart", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._disconnect("HAT service stopped")
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)

    def _fresh(self):
        return (self.enabled and self._serial is not None and self._last_seen is not None
                and self._clock() - self._last_seen <= self.stale_after)

    def snapshot(self):
        with self._lock:
            fresh = self._fresh()
            outputs_known = fresh and not self._outputs_uncertain
            age = None if self._last_seen is None else max(0, self._clock() - self._last_seen)
            error = self._error
            if not fresh and self._last_seen is not None:
                error = error or "HAT telemetry timed out"
            return {
                "sensors": dict(self._sensors) if fresh else dict.fromkeys(self._sensors),
                "relays": dict(self._relays) if outputs_known else dict.fromkeys(self._relays),
                "control_mode": self._mode if outputs_known else None,
                "hat": {
                    "enabled": self.enabled, "connected": fresh, "stale": not fresh,
                    "outputs_uncertain": self._outputs_uncertain,
                    "port": self.port, "baudrate": self.baudrate,
                    "last_seen_age_s": round(age, 2) if age is not None else None,
                    "uptime_ms": self._last_uptime if fresh else None,
                    "sensor_ok": dict(self._sensor_ok) if fresh else {},
                    "errors": list(self._errors) if fresh else [], "error": error,
                    "selected_relay": self._selected_relay if fresh else None,
                    "last_event": copy.deepcopy(self._last_event),
                },
            }

    def drain_events(self):
        with self._lock:
            events = list(self._events)
            self._events.clear()
            return events

    @staticmethod
    def _validate_command(command, fields):
        if command == "set_relay":
            if set(fields) != {"relay", "state"} or type(fields["relay"]) is not int or fields["relay"] not in (1, 2, 3) or type(fields["state"]) is not bool:
                raise ValueError("relay must be 1, 2 or 3 and state must be a JSON boolean")
        elif command == "set_mode":
            if set(fields) != {"mode"} or fields["mode"] not in ("manual", "auto"):
                raise ValueError("mode must be manual or auto")
        elif command == "action":
            if set(fields) != {"action"} or fields["action"] not in ("capture", "up", "ok", "down"):
                raise ValueError("Unknown HAT button action")
        elif command != "ping" or fields:
            raise ValueError("Unknown HAT command")

    def command(self, command, **fields):
        self._validate_command(command, fields)
        packet = {"v": 1, "type": "command", "id": uuid.uuid4().hex,
                  "command": command, **fields}
        pending = _Pending(packet, self._clock() + self.command_timeout)
        with self._lock:
            if not self._fresh():
                raise HatUnavailable(self._error or "No fresh HAT telemetry")
            if self._outputs_uncertain:
                raise HatUnavailable("Waiting for telemetry to confirm relay state after an unacknowledged command")
            if command == "set_relay" and self._mode != "manual":
                raise HatCommandError("Switch to manual mode before controlling a relay")
            if len(self._pending) >= 16:
                raise HatUnavailable("HAT command queue is busy")
            self._pending[packet["id"]] = pending
            try:
                self._outgoing.put_nowait(packet["id"])
            except queue.Full:
                self._pending.pop(packet["id"], None)
                raise HatUnavailable("HAT command queue is busy") from None
        try:
            if not pending.done.wait(self.command_timeout):
                with self._lock:
                    self._outputs_uncertain = True
                raise HatTimeout("No ACK from ESP32; command outcome is unknown. Check telemetry before retrying.")
            if pending.error:
                raise pending.error
            return pending.response
        finally:
            with self._lock:
                self._pending.pop(packet["id"], None)

    def _fail_pending(self, message):
        for pending in self._pending.values():
            if not pending.done.is_set():
                pending.error = HatUnavailable(message)
                pending.done.set()

    def _disconnect(self, message):
        with self._lock:
            connection, self._serial = self._serial, None
            self._error = message
            self._last_seen = None
            self._last_uptime = None
            self._outputs_uncertain = True
            self._event_ids.clear()
            self._events.clear()
            self._fail_pending(message)
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    def _open(self):
        if self._factory is not None:
            return self._factory(self.port, self.baudrate, timeout=0.2, write_timeout=0.5)
        import serial
        # Set control lines before opening; UART0/CP2102 is not this protocol port.
        connection = serial.Serial(port=None, baudrate=self.baudrate,
                                   timeout=0.2, write_timeout=0.5,
                                   exclusive=True if os.name == "posix" else None)
        connection.dtr = False
        connection.rts = False
        connection.port = self.port
        connection.open()
        return connection

    def _write(self, connection, packet):
        payload = (json.dumps(packet, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
        if len(payload) > 1024:
            raise ValueError("HAT command is too large")
        if connection.write(payload) != len(payload):
            raise OSError("Incomplete UART write; command was not retried")

    def _run(self):
        while not self._stop.is_set():
            try:
                connection = self._open()
                with self._lock:
                    if self._stop.is_set():
                        connection.close()
                        break
                    self._serial = connection
                    self._error = "Waiting for HAT telemetry"
                decoder = LineDecoder()
                opened_at = self._clock()
                next_ping = 0.0
                while not self._stop.is_set():
                    now = self._clock()
                    # A broken receive direction must not keep actuators alive
                    # forever. Give a new port one telemetry window to bootstrap.
                    with self._lock:
                        can_heartbeat = self._fresh() or (self._last_seen is None and now - opened_at <= self.stale_after)
                    if now >= next_ping and can_heartbeat:
                        self._write(connection, {"v": 1, "type": "command", "command": "ping",
                                                 "id": "ping-" + uuid.uuid4().hex[:16]})
                        next_ping = now + 2.0
                    try:
                        command_id = self._outgoing.get_nowait()
                    except queue.Empty:
                        command_id = None
                    if command_id is not None:
                        with self._lock:
                            pending = self._pending.get(command_id)
                            if pending and not pending.done.is_set() and now < pending.deadline:
                                if not self._fresh() or self._outputs_uncertain:
                                    pending.error = HatUnavailable("HAT telemetry is stale or relay state is unknown")
                                    pending.done.set()
                                else:
                                    self._write(connection, pending.packet)
                    for line in decoder.feed(connection.read(256)):
                        self._receive(line)
            except Exception as exc:
                self._disconnect(f"UART unavailable: {exc}")
                self._stop.wait(self.reconnect_after)
            finally:
                self._disconnect("HAT service stopped" if self._stop.is_set() else self._error)

    def _receive(self, line):
        try:
            packet = json.loads(line)
            if not isinstance(packet, dict) or type(packet.get("v")) is not int or packet["v"] != 1:
                return
            with self._lock:
                if packet.get("type") == "telemetry":
                    self._telemetry(packet)
                elif packet.get("type") == "ack":
                    self._ack(packet)
                elif packet.get("type") == "event":
                    self._event(packet)
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
            # Noise, boot logs and malformed packets must not kill the reader.
            return

    def _telemetry(self, packet):
        mode, relays = _outputs(packet)
        uptime = packet.get("uptime_ms")
        seq = packet.get("seq")
        sensors, status = packet.get("sensors"), packet.get("sensor_ok")
        if (type(uptime) is not int or not 0 <= uptime <= 0xFFFFFFFF or type(seq) is not int
                or not 0 <= seq <= 0xFFFFFFFF or not isinstance(sensors, dict) or not isinstance(status, dict)):
            return
        if self._last_uptime is not None and uptime < self._last_uptime:
            self._fail_pending("ESP32 restarted; command outcome is unknown")
            self._events.clear()
            self._event_ids.clear()
        sensor_ok = {key: status.get(key) is True for key in ("sht31", "bh1750", "ads1115", "soil_calibrated")}
        readings = {
            "temp": _number(sensors.get("temp"), -40, 125) if sensor_ok["sht31"] else None,
            "humidity": _number(sensors.get("humidity"), 0, 100) if sensor_ok["sht31"] else None,
            "light": _number(sensors.get("light"), 0, 200000) if sensor_ok["bh1750"] else None,
            "soil_raw": _number(sensors.get("soil_raw"), -32768, 32767) if sensor_ok["ads1115"] else None,
            "soil": _number(sensors.get("soil"), 0, 100) if sensor_ok["ads1115"] and sensor_ok["soil_calibrated"] else None,
        }
        errors = packet.get("errors", [])
        if not isinstance(errors, list) or any(not isinstance(e, str) for e in errors):
            return
        self._sensors, self._sensor_ok = readings, sensor_ok
        self._errors = [e[:160] for e in errors[:8]]
        self._mode, self._relays = mode, relays
        self._outputs_uncertain = False
        self._last_seen, self._last_uptime = self._clock(), uptime
        self._selected_relay = packet.get("selected_relay") if type(packet.get("selected_relay")) is int and packet["selected_relay"] in (1, 2, 3) else None
        self._error = None

    def _ack(self, packet):
        command_id = packet.get("id")
        if not isinstance(command_id, str) or type(packet.get("ok")) is not bool:
            return
        pending = self._pending.get(command_id)
        if not pending or pending.done.is_set() or self._clock() > pending.deadline:
            return
        if not packet["ok"]:
            pending.error = HatCommandError(str(packet.get("error", "ESP32 rejected the command"))[:240])
        else:
            mode, relays = _outputs(packet)
            requested = pending.packet
            if requested["command"] == "set_relay" and relays[str(requested["relay"])] != requested["state"]:
                self._outputs_uncertain = True
                pending.error = HatCommandError("ESP32 ACK does not match the requested relay state")
            elif requested["command"] == "set_mode" and mode != requested["mode"]:
                self._outputs_uncertain = True
                pending.error = HatCommandError("ESP32 ACK does not match the requested mode")
            else:
                self._mode, self._relays = mode, relays
                self._outputs_uncertain = False
                pending.response = packet
        pending.done.set()

    def _event(self, packet):
        if (packet.get("event") != "button" or packet.get("button") not in ("capture", "up", "ok", "down")
                or type(packet.get("seq")) is not int or type(packet.get("uptime_ms")) is not int
                or not self._fresh()):
            return
        key = packet["seq"], packet["uptime_ms"]
        if key in self._event_ids:
            return
        self._event_ids.append(key)
        event = {"button": packet["button"], "seq": packet["seq"], "uptime_ms": packet["uptime_ms"]}
        self._last_event = event
        self._events.append(event)
