import tempfile
import unittest
from pathlib import Path

from flask import Flask

from hardware.hat_client import HatClient, HatCommandError, HatTimeout, HatUnavailable
from hardware.web import HatService, create_hat_blueprint
from test_hat_client import FakeSerial, telemetry, wait_for


class FakeClient:
    def __init__(self):
        self.state = {"sensors": {}, "relays": {"1": False, "2": False, "3": False},
                      "control_mode": "manual", "hat": {"connected": True}}
        self.error = None
        self.calls = []
        self.events = []

    def snapshot(self):
        return dict(self.state)

    def command(self, command, **fields):
        HatClient._validate_command(command, fields)
        if self.error:
            raise self.error
        self.calls.append((command, fields))
        if command == "set_relay":
            self.state["relays"][str(fields["relay"])] = fields["state"]
        if command == "set_mode":
            self.state["control_mode"] = fields["mode"]
        return {"id": "ack-123", "ok": True}

    def drain_events(self):
        events, self.events = self.events, []
        return events


class HatWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.device = FakeClient()
        self.ready = True
        self.service = HatService(self.device, self.temp.name,
                                  lambda path: path.write_bytes(b"jpeg-test"), lambda: self.ready)
        self.app = Flask(__name__)
        self.app.register_blueprint(create_hat_blueprint(self.service))
        self.http = self.app.test_client()

    def test_acknowledged_relay_and_mode(self):
        result = self.http.post("/api/relay", json={"relay": 1, "state": True})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json["relays"]["1"])
        self.assertEqual(result.json["ack_id"], "ack-123")
        result = self.http.post("/api/hat/mode", json={"mode": "auto"})
        self.assertEqual(result.json["control_mode"], "auto")

    def test_reject_non_json_wrong_types_and_extra_command_fields(self):
        cases = [None, [], {"relay": 1, "state": "false"}, {"relay": True, "state": True},
                 {"relay": 4, "state": False}, {"relay": 1, "state": False, "command": "reset"}]
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(self.http.post("/api/relay", json=body).status_code, 400)
        self.assertEqual(self.device.calls, [])

    def test_failure_statuses_never_claim_success(self):
        for error, status in [(HatUnavailable("offline"), 503), (HatTimeout("unknown"), 504),
                              (HatCommandError("manual only"), 409)]:
            self.device.error = error
            result = self.http.post("/api/relay", json={"relay": 2, "state": True})
            self.assertEqual(result.status_code, status)
            self.assertFalse(result.json["ok"])
            self.assertFalse(result.json["relays"]["2"])

    def test_capture_event_saves_and_serves_image(self):
        self.device.events = [{"button": "capture", "seq": 10}]
        self.service.process_events()
        snapshot = self.http.get("/api/hat").json
        capture = snapshot["last_capture"]
        self.assertEqual(capture["event_seq"], 10)
        with self.http.get(capture["url"]) as response:
            self.assertEqual(response.data, b"jpeg-test")
        self.assertEqual(len(list(Path(self.temp.name).glob("*.jpg"))), 1)
        self.service.process_events()
        self.assertEqual(len(list(Path(self.temp.name).glob("*.jpg"))), 1)

    def test_no_camera_no_virtual_capture_command_and_physical_event_reports_error(self):
        self.ready = False
        result = self.http.post("/api/hat/action", json={"action": "capture"})
        self.assertEqual(result.status_code, 503)
        self.assertEqual(self.device.calls, [])
        self.device.events = [{"button": "capture", "seq": 11}]
        self.service.process_events()
        state = self.http.get("/api/hat").json
        self.assertIsNone(state["last_capture"])
        self.assertIn("unavailable", state["last_capture_error"])

    def test_offline_simulation_accepts_controls_without_claiming_hardware_connection(self):
        self.device.state["hat"] = {"connected": False, "stale": True, "error": "offline"}
        service = HatService(self.device, self.temp.name,
                             lambda path: path.write_bytes(b"jpeg-test"), lambda: True,
                             allow_offline_controls=True)
        app = Flask("offline-simulation")
        app.register_blueprint(create_hat_blueprint(service))
        with app.test_client() as http:
            state = http.get("/api/hat").json
            self.assertTrue(state["hat"]["simulated"])
            self.assertTrue(state["hat"]["controls_available"])
            self.assertEqual(state["control_mode"], "manual")
            response = http.post("/api/relay", json={"relay": 2, "state": True})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json["relays"]["2"])
            self.assertTrue(response.json["hat"]["simulated"])
            response = http.post("/api/hat/action", json={"action": "capture"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["last_capture"]["source"], "web-simulation")


class UartHttpRoundTripTests(unittest.TestCase):
    def test_http_command_crosses_serial_worker_and_returns_confirmed_mcu_state(self):
        serial = FakeSerial()
        serial.emit(telemetry())
        client = HatClient(serial_factory=lambda *args, **kwargs: serial, command_timeout=0.5)
        service = HatService(client, "unused-captures", lambda path: None)
        self.addCleanup(service.stop)
        app = Flask(__name__)
        app.register_blueprint(create_hat_blueprint(service))
        service.start()
        wait_for(lambda: client.snapshot()["hat"]["connected"])
        with app.test_client() as http:
            response = http.post("/api/relay", json={"relay": 2, "state": True})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json["relays"]["2"])
            packet = next(p for p in serial.writes if p["command"] == "set_relay")
            self.assertEqual(response.json["ack_id"], packet["id"])
            self.assertEqual(packet["relay"], 2)
            self.assertEqual(http.get("/api/hat").json["sensors"]["temp"], 27.5)
            self.assertEqual(http.post("/api/hat/mode", json={"mode": "auto"}).status_code, 200)
            self.assertEqual(http.post("/api/relay", json={"relay": 2, "state": False}).status_code, 409)


if __name__ == "__main__":
    unittest.main()
