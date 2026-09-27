import json
import queue
import threading
import time
import unittest

from hardware.hat_client import HatClient, HatCommandError, HatTimeout, HatUnavailable, LineDecoder


def telemetry(**changes):
    packet = {
        "v": 1, "type": "telemetry", "seq": 1, "uptime_ms": 1000,
        "mode": "manual", "relays": {"1": False, "2": False, "3": False},
        "sensors": {"temp": 27.5, "humidity": 71, "light": 5000, "soil": 42, "soil_raw": 15000},
        "sensor_ok": {"sht31": True, "bh1750": True, "ads1115": True, "soil_calibrated": True},
        "errors": [],
    }
    packet.update(changes)
    return packet


class FakeSerial:
    def __init__(self, acknowledge=True):
        self.input = queue.Queue()
        self.writes = []
        self.closed = False
        self.acknowledge = acknowledge
        self.mode = "manual"
        self.relays = {"1": False, "2": False, "3": False}
        self.reject = False

    def emit(self, packet):
        self.input.put((json.dumps(packet) + "\n").encode())

    def read(self, size):
        if self.closed:
            raise OSError("Disconnected")
        try:
            return self.input.get(timeout=0.01)
        except queue.Empty:
            return b""

    def write(self, data):
        if self.closed:
            raise OSError("Disconnected")
        packet = json.loads(data)
        self.writes.append(packet)
        if packet["command"] == "ping":
            return len(data)
        if not self.reject:
            if packet["command"] == "set_mode":
                self.mode = packet["mode"]
            elif packet["command"] == "set_relay":
                self.relays[str(packet["relay"])] = packet["state"]
        if self.acknowledge:
            self.emit({"v": 1, "type": "ack", "id": packet["id"], "ok": not self.reject,
                       "mode": self.mode, "relays": dict(self.relays), "error": "rejected"})
        return len(data)

    def close(self):
        self.closed = True


def wait_for(predicate, timeout=1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting for test condition")


class HatClientTests(unittest.TestCase):
    def connected(self, serial=None, **options):
        device = serial or FakeSerial()
        device.emit(telemetry())
        client = HatClient(serial_factory=lambda *a, **k: device,
                           command_timeout=0.2, reconnect_after=0.02, **options)
        self.addCleanup(client.stop)
        client.start()
        wait_for(lambda: client.snapshot()["hat"]["connected"])
        return client, device

    def test_fragmentation_and_oversize_resynchronization(self):
        decoder = LineDecoder(limit=8)
        self.assertEqual(list(decoder.feed(b"abc")), [])
        self.assertEqual(list(decoder.feed(b"def\r\nxy\n")), [b"abcdef", b"xy"])
        self.assertEqual(list(decoder.feed(b"123456789")), [])
        self.assertEqual(list(decoder.feed(b'{}\nOK\n')), [b"OK"])

    def test_correlated_ack_and_no_optimistic_updates(self):
        client, device = self.connected(FakeSerial(acknowledge=False))
        answers = []
        thread = threading.Thread(target=lambda: answers.append(client.command("set_relay", relay=1, state=True)))
        thread.start()
        wait_for(lambda: any(p["command"] == "set_relay" for p in device.writes))
        self.assertFalse(client.snapshot()["relays"]["1"])
        command = next(p for p in device.writes if p["command"] == "set_relay")
        device.emit({"v": 1, "type": "ack", "id": "wrong", "ok": True, "mode": "manual", "relays": device.relays})
        time.sleep(0.02)
        self.assertFalse(answers)
        device.emit({"v": 1, "type": "ack", "id": command["id"], "ok": True, "mode": "manual", "relays": device.relays})
        thread.join(1)
        self.assertEqual(answers[0]["id"], command["id"])
        self.assertTrue(client.snapshot()["relays"]["1"])

    def test_timeout_does_not_replay_or_apply_late_ack(self):
        client, device = self.connected(FakeSerial(acknowledge=False))
        with self.assertRaises(HatTimeout):
            client.command("set_relay", relay=3, state=True)
        sent = [p for p in device.writes if p["command"] == "set_relay"]
        self.assertEqual(len(sent), 1)
        device.emit({"v": 1, "type": "ack", "id": sent[0]["id"], "ok": True, "mode": "manual", "relays": device.relays})
        time.sleep(0.025)
        self.assertIsNone(client.snapshot()["relays"]["3"])
        self.assertTrue(client.snapshot()["hat"]["outputs_uncertain"])
        with self.assertRaises(HatUnavailable):
            client.command("set_relay", relay=3, state=False)
        device.emit(telemetry(seq=2, uptime_ms=2000, relays=device.relays))
        wait_for(lambda: client.snapshot()["relays"]["3"] is True)

    def test_nack_and_manual_only_controls(self):
        client, device = self.connected()
        device.reject = True
        with self.assertRaises(HatCommandError):
            client.command("set_mode", mode="auto")
        self.assertEqual(client.snapshot()["control_mode"], "manual")
        device.reject = False
        client.command("set_mode", mode="auto")
        with self.assertRaises(HatCommandError):
            client.command("set_relay", relay=2, state=True)

    def test_stale_telemetry_nulls_readings_and_blocks_commands(self):
        client, device = self.connected(stale_after=0.05)
        wait_for(lambda: client.snapshot()["hat"]["stale"])
        state = client.snapshot()
        self.assertTrue(all(v is None for v in state["sensors"].values()))
        self.assertTrue(all(v is None for v in state["relays"].values()))
        self.assertIsNone(state["control_mode"])
        with self.assertRaises(HatUnavailable):
            client.command("set_mode", mode="manual")

    def test_disconnect_fails_pending_without_replay_on_new_connection(self):
        first, second = FakeSerial(False), FakeSerial()
        first.emit(telemetry())
        second.emit(telemetry(uptime_ms=3000))
        devices = iter((first, second))
        client = HatClient(serial_factory=lambda *a, **k: next(devices), command_timeout=1, reconnect_after=0.01)
        self.addCleanup(client.stop)
        client.start()
        wait_for(lambda: client.snapshot()["hat"]["connected"])
        failures = []

        def command():
            try:
                client.command("set_relay", relay=1, state=True)
            except HatUnavailable as exc:
                failures.append(exc)

        thread = threading.Thread(target=command)
        thread.start()
        wait_for(lambda: any(p["command"] == "set_relay" for p in first.writes))
        first.close()
        thread.join(1)
        self.assertEqual(len(failures), 1)
        wait_for(lambda: client.snapshot()["hat"]["uptime_ms"] == 3000)
        self.assertFalse(any(p["command"] == "set_relay" for p in second.writes))

    def test_sensor_errors_nan_and_uncalibrated_soil_are_not_measurements(self):
        client, device = self.connected()
        packet = telemetry(seq=2, uptime_ms=2000)
        packet["sensors"].update(temp=float("nan"), humidity=150, light=True)
        packet["sensor_ok"]["soil_calibrated"] = False
        device.emit(packet)
        wait_for(lambda: client.snapshot()["hat"]["uptime_ms"] == 2000)
        state = client.snapshot()["sensors"]
        self.assertIsNone(state["temp"])
        self.assertIsNone(state["humidity"])
        self.assertIsNone(state["light"])
        self.assertIsNone(state["soil"])
        self.assertEqual(state["soil_raw"], 15000)

    def test_invalid_packets_and_duplicate_events(self):
        client, device = self.connected()
        for line in (b"boot log", b"\xff", b"null", b'[]', b'{"v":true}', b'{"v":1,"type":"telemetry"}'):
            device.input.put(line + b"\n")
        event = {"v": 1, "type": "event", "seq": 5, "uptime_ms": 1100, "event": "button", "button": "capture"}
        device.emit(event)
        device.emit(event)
        wait_for(lambda: client.snapshot()["hat"]["last_event"] is not None)
        time.sleep(0.02)
        self.assertEqual(len(client.drain_events()), 1)
        self.assertEqual(client.drain_events(), [])
        self.assertTrue(client.snapshot()["hat"]["connected"])

    def test_heartbeat_stops_when_telemetry_is_stale_and_resumes_on_recovery(self):
        now = [0.0]
        client, device = self.connected(clock=lambda: now[0])
        wait_for(lambda: len(device.writes) >= 1)
        now[0] = 3.0
        wait_for(lambda: len(device.writes) >= 2)
        now[0] = 7.0
        time.sleep(0.025)
        count = len(device.writes)
        now[0] = 20.0
        time.sleep(0.025)
        self.assertEqual(len(device.writes), count)
        device.emit(telemetry(seq=2, uptime_ms=20000))
        wait_for(lambda: len(device.writes) > count)
        self.assertTrue(client.snapshot()["hat"]["connected"])

    def test_input_validation_and_disabled_import(self):
        client = HatClient(enabled=False)
        client.start()
        self.assertIsNone(client._thread)
        with self.assertRaises(ValueError):
            client.command("set_relay", relay=True, state=1)
        with self.assertRaises(ValueError):
            client.command("action", action="erase")
        with self.assertRaises(HatUnavailable):
            client.command("set_mode", mode="auto")


if __name__ == "__main__":
    unittest.main()
