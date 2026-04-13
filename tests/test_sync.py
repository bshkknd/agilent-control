from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agilent_control.instrument import Keysight33600A
from agilent_control.sync import (
    PulseSyncConfig,
    PulseSyncState,
    PulseWidthSyncService,
    PulseWidthRange,
    TcpPulseWidthClient,
    convert_pulse_width_to_seconds,
    load_pulse_sync_config,
    parse_pulsewidth_response,
    save_pulse_sync_config,
)
from agilent_control.transports import FakeVisaResource


class ParsePulseWidthResponseTest(unittest.TestCase):
    def test_accepts_valid_line(self) -> None:
        self.assertEqual(parse_pulsewidth_response("VALUE 0.010"), 0.01)

    def test_accepts_integer_payload(self) -> None:
        self.assertEqual(parse_pulsewidth_response("VALUE 123"), 123.0)

    def test_accepts_crlf_terminated_payload(self) -> None:
        self.assertEqual(parse_pulsewidth_response("VALUE 123\r\n"), 123.0)

    def test_accepts_trailing_space(self) -> None:
        self.assertEqual(parse_pulsewidth_response("VALUE 123 "), 123.0)

    def test_rejects_invalid_prefix(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid pulse-width response"):
            parse_pulsewidth_response("WIDTH 0.010")

    def test_rejects_missing_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing a numeric payload"):
            parse_pulsewidth_response("VALUE ")

    def test_rejects_non_numeric_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid pulse-width value"):
            parse_pulsewidth_response("VALUE abc")


class TcpPulseWidthClientTest(unittest.TestCase):
    def test_request_uses_crlf_and_returns_plain_payload(self) -> None:
        class FakeSocket:
            def __init__(self) -> None:
                self.sent: list[bytes] = []
                self.timeout: float | None = None

            def settimeout(self, timeout: float) -> None:
                self.timeout = timeout

            def sendall(self, data: bytes) -> None:
                self.sent.append(data)

            def recv(self, _: int) -> bytes:
                return b"VALUE 123"

            def close(self) -> None:
                return None

        fake_socket = FakeSocket()
        client = TcpPulseWidthClient("127.0.0.1", 9000)

        with patch("socket.create_connection", return_value=fake_socket):
            response = client.request_pulse_width()

        self.assertEqual(fake_socket.sent, [b"GET pulsewidth\r\n"])
        self.assertEqual(response, "VALUE 123")

    def test_request_accepts_crlf_payload(self) -> None:
        class FakeSocket:
            def __init__(self) -> None:
                self.sent: list[bytes] = []
                self.timeout: float | None = None

            def settimeout(self, timeout: float) -> None:
                self.timeout = timeout

            def sendall(self, data: bytes) -> None:
                self.sent.append(data)

            def recv(self, _: int) -> bytes:
                return b"VALUE 123\r\n"

            def close(self) -> None:
                return None

        fake_socket = FakeSocket()
        client = TcpPulseWidthClient("127.0.0.1", 9000)

        with patch("socket.create_connection", return_value=fake_socket):
            response = client.request_pulse_width()

        self.assertEqual(response, "VALUE 123\r\n")


class ConvertPulseWidthToSecondsTest(unittest.TestCase):
    def test_supports_ns(self) -> None:
        self.assertAlmostEqual(convert_pulse_width_to_seconds(10, "ns"), 10e-9)

    def test_supports_us(self) -> None:
        self.assertAlmostEqual(convert_pulse_width_to_seconds(10, "us"), 10e-6)

    def test_supports_ms(self) -> None:
        self.assertAlmostEqual(convert_pulse_width_to_seconds(10, "ms"), 10e-3)


class PulseSyncConfigPersistenceTest(unittest.TestCase):
    def test_default_maximum_width_is_1000_us(self) -> None:
        config = PulseSyncConfig(visa_resource="USB0::TEST", tcp_host="127.0.0.1", tcp_port=9000)
        self.assertAlmostEqual(config.width_range.maximum_s, 1000e-6)

    def test_save_and_load_config_round_trip(self) -> None:
        config = PulseSyncConfig(
            visa_resource="USB0::TEST",
            tcp_host="127.0.0.1",
            tcp_port=9000,
            width_range=PulseWidthRange(minimum_s=20e-9, maximum_s=1000e-6),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "awg_tui_config.json"
            save_pulse_sync_config(path, config)
            loaded = load_pulse_sync_config(path)

        self.assertEqual(loaded.visa_resource, "USB0::TEST")
        self.assertEqual(loaded.tcp_host, "127.0.0.1")
        self.assertEqual(loaded.tcp_port, 9000)
        self.assertAlmostEqual(loaded.width_range.maximum_s, 1000e-6)

    def test_load_rejects_invalid_json_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "awg_tui_config.json"
            path.write_text(json.dumps(["bad"]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON object"):
                load_pulse_sync_config(path)

    def test_validate_rejects_invalid_width_range(self) -> None:
        config = PulseSyncConfig(
            visa_resource="USB0::TEST",
            tcp_host="127.0.0.1",
            tcp_port=9000,
            width_range=PulseWidthRange(minimum_s=1e-3, maximum_s=1e-4),
        )
        with self.assertRaisesRegex(ValueError, "maximum_s must be greater"):
            config.validate()


class PulseWidthSyncServiceTest(unittest.TestCase):
    def make_service(
        self,
        responses: list[str],
        *,
        source_unit: str = "us",
        width_range: PulseWidthRange | None = None,
    ) -> tuple[PulseWidthSyncService, FakeVisaResource, PulseSyncState]:
        resource = FakeVisaResource()
        instrument = Keysight33600A(resource=resource)
        config = PulseSyncConfig(
            visa_resource="USB0::TEST",
            tcp_host="127.0.0.1",
            tcp_port=9000,
            source_unit=source_unit,
            width_range=width_range or PulseWidthRange(),
        )
        state = PulseSyncState()
        iterator = iter(responses)
        service = PulseWidthSyncService(
            instrument=instrument,
            config=config,
            fetch_response=lambda: next(iterator),
            state=state,
        )
        return service, resource, state

    def test_startup_applies_full_preset_once(self) -> None:
        service, resource, state = self.make_service(["VALUE 20.0"])

        service.poll_once(now=1.0)

        self.assertTrue(state.startup_applied)
        self.assertEqual(resource.writes[0], "*RST")
        self.assertIn("FUNC:PULS:WIDT 2e-05", resource.writes)
        self.assertAlmostEqual(state.last_applied_width_s or 0.0, 20e-6)

    def test_unchanged_value_does_not_rewrite_width(self) -> None:
        service, resource, _ = self.make_service(["VALUE 20.0", "VALUE 20.0"])

        service.poll_once(now=1.0)
        first_write_count = len(resource.writes)
        service.poll_once(now=2.0)

        self.assertEqual(len(resource.writes), first_write_count)

    def test_changed_value_updates_width_only(self) -> None:
        service, resource, _ = self.make_service(["VALUE 20.0", "VALUE 25.0"])

        service.poll_once(now=1.0)
        service.poll_once(now=2.0)

        self.assertEqual(resource.writes[-1], "FUNC:PULS:WIDT 2.5e-05")

    def test_invalid_width_is_rejected_and_keeps_last_good_value(self) -> None:
        service, resource, state = self.make_service(
            ["VALUE 20.0", "VALUE 5000.0"],
            width_range=PulseWidthRange(minimum_s=10e-9, maximum_s=1000e-6),
        )

        service.poll_once(now=1.0)
        first_write_count = len(resource.writes)
        service.poll_once(now=2.0)

        self.assertEqual(len(resource.writes), first_write_count)
        self.assertAlmostEqual(state.last_applied_width_s or 0.0, 20e-6)
        self.assertIn("pulse width must stay within", state.last_error or "")

    def test_tcp_failure_sets_error_without_exiting(self) -> None:
        resource = FakeVisaResource()
        instrument = Keysight33600A(resource=resource)
        config = PulseSyncConfig(visa_resource="USB0::TEST", tcp_host="127.0.0.1", tcp_port=9000)
        state = PulseSyncState()
        service = PulseWidthSyncService(
            instrument=instrument,
            config=config,
            fetch_response=lambda: (_ for _ in ()).throw(ConnectionError("server down")),
            state=state,
        )

        service.poll_once(now=1.0)

        self.assertFalse(state.sync_active)
        self.assertFalse(state.tcp_connected)
        self.assertEqual(state.last_error, "server down")

    def test_reset_startup_marks_reconfigure_pending(self) -> None:
        service, _, state = self.make_service(["VALUE 20.0"])

        service.reset_startup()

        self.assertFalse(state.sync_active)
        self.assertTrue(state.pending_reconfigure)

    def test_successful_poll_clears_reconfigure_and_polling_flags(self) -> None:
        service, _, state = self.make_service(["VALUE 20.0"])
        service.reset_startup()

        service.poll_once(now=1.0)

        self.assertFalse(state.poll_in_progress)
        self.assertFalse(state.pending_reconfigure)
        self.assertTrue(state.sync_active)

    def test_pause_skips_polling(self) -> None:
        service, resource, state = self.make_service(["VALUE 20.0"])
        state.paused = True

        service.poll_once(now=1.0)

        self.assertFalse(state.sync_active)
        self.assertFalse(state.poll_in_progress)
        self.assertEqual(resource.writes, [])


if __name__ == "__main__":
    unittest.main()
