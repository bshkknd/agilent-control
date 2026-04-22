from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agilent_control.instrument import Keysight33600A
from agilent_control.sync import (
    FrequencyRange,
    PulseSyncConfig,
    PulseSyncState,
    PulseWidthSyncService,
    PulseWidthRange,
    RfGeneratorConfig,
    TcpPulseWidthClient,
    convert_frequency_to_hz,
    convert_pulse_width_to_seconds,
    load_pulse_sync_config,
    parse_pulsewidth_response,
    parse_rffrequency_response,
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


class ParseRfFrequencyResponseTest(unittest.TestCase):
    def test_accepts_valid_line(self) -> None:
        self.assertEqual(parse_rffrequency_response("VALUE 12.5"), 12.5)

    def test_rejects_invalid_prefix(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid RF frequency response"):
            parse_rffrequency_response("FREQ 12.5")


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

    def test_request_rf_frequency_uses_expected_command(self) -> None:
        class FakeSocket:
            def __init__(self) -> None:
                self.sent: list[bytes] = []

            def settimeout(self, _: float) -> None:
                return None

            def sendall(self, data: bytes) -> None:
                self.sent.append(data)

            def recv(self, _: int) -> bytes:
                return b"VALUE 1000000"

            def close(self) -> None:
                return None

        fake_socket = FakeSocket()
        client = TcpPulseWidthClient("127.0.0.1", 9000)

        with patch("socket.create_connection", return_value=fake_socket):
            response = client.request_rf_frequency()

        self.assertEqual(fake_socket.sent, [b"GET rffrequency\r\n"])
        self.assertEqual(response, "VALUE 1000000")


class ConvertPulseWidthToSecondsTest(unittest.TestCase):
    def test_supports_ns(self) -> None:
        self.assertAlmostEqual(convert_pulse_width_to_seconds(10, "ns"), 10e-9)

    def test_supports_us(self) -> None:
        self.assertAlmostEqual(convert_pulse_width_to_seconds(10, "us"), 10e-6)

    def test_supports_ms(self) -> None:
        self.assertAlmostEqual(convert_pulse_width_to_seconds(10, "ms"), 10e-3)


class ConvertFrequencyToHzTest(unittest.TestCase):
    def test_supports_hz(self) -> None:
        self.assertAlmostEqual(convert_frequency_to_hz(10, "Hz"), 10)

    def test_supports_khz(self) -> None:
        self.assertAlmostEqual(convert_frequency_to_hz(10, "kHz"), 10e3)

    def test_supports_mhz(self) -> None:
        self.assertAlmostEqual(convert_frequency_to_hz(10, "MHz"), 10e6)


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
            rf=RfGeneratorConfig(
                enabled=True,
                visa_resource="USB0::RF",
                amplitude_dbm=-7.5,
                source_unit="MHz",
                frequency_range=FrequencyRange(minimum_hz=1e6, maximum_hz=10e6),
            ),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "awg_tui_config.json"
            save_pulse_sync_config(path, config)
            loaded = load_pulse_sync_config(path)

        self.assertEqual(loaded.visa_resource, "USB0::TEST")
        self.assertEqual(loaded.tcp_host, "127.0.0.1")
        self.assertEqual(loaded.tcp_port, 9000)
        self.assertAlmostEqual(loaded.width_range.maximum_s, 1000e-6)
        self.assertTrue(loaded.rf.enabled)
        self.assertEqual(loaded.rf.visa_resource, "USB0::RF")
        self.assertAlmostEqual(loaded.rf.amplitude_dbm, -7.5)
        self.assertEqual(loaded.rf.source_unit, "MHz")
        self.assertAlmostEqual(loaded.rf.frequency_range.maximum_hz, 10e6)

    def test_loads_legacy_rf_amplitude_vpp_as_dbm_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "awg_tui_config.json"
            path.write_text(
                json.dumps(
                    {
                        "visa_resource": "USB0::TEST",
                        "tcp_host": "127.0.0.1",
                        "tcp_port": 9000,
                        "rf": {
                            "enabled": True,
                            "visa_resource": "USB0::RF",
                            "amplitude_vpp": -10.0,
                        },
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_pulse_sync_config(path)
            save_pulse_sync_config(path, loaded)
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertAlmostEqual(loaded.rf.amplitude_dbm, -10.0)
        self.assertEqual(saved["rf"]["amplitude_dbm"], -10.0)
        self.assertNotIn("amplitude_vpp", saved["rf"])

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

    def test_validate_rejects_enabled_rf_without_resource(self) -> None:
        config = PulseSyncConfig(
            visa_resource="USB0::TEST",
            tcp_host="127.0.0.1",
            tcp_port=9000,
            rf=RfGeneratorConfig(enabled=True),
        )
        with self.assertRaisesRegex(ValueError, "rf.visa_resource"):
            config.validate()

    def test_validate_accepts_negative_rf_dbm_and_rejects_non_finite(self) -> None:
        config = PulseSyncConfig(
            visa_resource="USB0::TEST",
            tcp_host="127.0.0.1",
            tcp_port=9000,
            rf=RfGeneratorConfig(amplitude_dbm=-20.0),
        )
        config.validate()

        config.rf.amplitude_dbm = float("inf")
        with self.assertRaisesRegex(ValueError, "amplitude_dbm"):
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

    def test_enabled_rf_configures_sine_output_on_startup(self) -> None:
        pulse_resource = FakeVisaResource()
        rf_resource = FakeVisaResource()
        pulse_instrument = Keysight33600A(resource=pulse_resource)
        rf_instrument = Keysight33600A(resource=rf_resource)
        config = PulseSyncConfig(
            visa_resource="USB0::TEST",
            tcp_host="127.0.0.1",
            tcp_port=9000,
            rf=RfGeneratorConfig(
                enabled=True,
                visa_resource="USB0::RF",
                amplitude_dbm=-10.0,
                source_unit="MHz",
                frequency_range=FrequencyRange(minimum_hz=1e6, maximum_hz=10e6),
            ),
        )
        service = PulseWidthSyncService(
            instrument=pulse_instrument,
            config=config,
            fetch_response=lambda: "VALUE 20.0",
            rf_instrument=rf_instrument,
            fetch_rf_response=lambda: "VALUE 2.5",
            state=PulseSyncState(),
        )

        state = service.poll_once(now=1.0)

        self.assertEqual(
            rf_resource.writes,
            [
                "FUNC SIN",
                "FREQ 2500000",
                "POW -10DBM",
                "OUTP:LOAD 50",
                "OUTP ON",
            ],
        )
        self.assertAlmostEqual(state.last_applied_rf_frequency_hz or 0.0, 2.5e6)

    def test_enabled_rf_changed_value_updates_frequency_only(self) -> None:
        pulse_resource = FakeVisaResource()
        rf_resource = FakeVisaResource()
        config = PulseSyncConfig(
            visa_resource="USB0::TEST",
            tcp_host="127.0.0.1",
            tcp_port=9000,
            rf=RfGeneratorConfig(
                enabled=True,
                visa_resource="USB0::RF",
                amplitude_dbm=-10.0,
                source_unit="MHz",
                frequency_range=FrequencyRange(minimum_hz=1e6, maximum_hz=10e6),
            ),
        )
        rf_responses = iter(["VALUE 2.5", "VALUE 3.0"])
        service = PulseWidthSyncService(
            instrument=Keysight33600A(resource=pulse_resource),
            config=config,
            fetch_response=lambda: "VALUE 20.0",
            rf_instrument=Keysight33600A(resource=rf_resource),
            fetch_rf_response=lambda: next(rf_responses),
            state=PulseSyncState(),
        )

        service.poll_once(now=1.0)
        service.poll_once(now=2.0)

        self.assertEqual(rf_resource.writes[-1], "FREQ 3000000")

    def test_rf_frequency_outside_safe_range_is_rejected(self) -> None:
        pulse_resource = FakeVisaResource()
        rf_resource = FakeVisaResource()
        config = PulseSyncConfig(
            visa_resource="USB0::TEST",
            tcp_host="127.0.0.1",
            tcp_port=9000,
            rf=RfGeneratorConfig(
                enabled=True,
                visa_resource="USB0::RF",
                source_unit="MHz",
                frequency_range=FrequencyRange(minimum_hz=1e6, maximum_hz=10e6),
            ),
        )
        rf_responses = iter(["VALUE 2.5", "VALUE 20.0"])
        service = PulseWidthSyncService(
            instrument=Keysight33600A(resource=pulse_resource),
            config=config,
            fetch_response=lambda: "VALUE 20.0",
            rf_instrument=Keysight33600A(resource=rf_resource),
            fetch_rf_response=lambda: next(rf_responses),
            state=PulseSyncState(),
        )

        service.poll_once(now=1.0)
        first_write_count = len(rf_resource.writes)
        state = service.poll_once(now=2.0)

        self.assertEqual(len(rf_resource.writes), first_write_count)
        self.assertIn("RF frequency must stay within", state.last_error or "")


if __name__ == "__main__":
    unittest.main()
