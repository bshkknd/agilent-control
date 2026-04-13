from __future__ import annotations

import unittest

from agilent_control.instrument import Keysight33600A
from agilent_control.sync import (
    PulseSyncConfig,
    PulseSyncState,
    PulseWidthSyncService,
    PulseWidthRange,
    convert_pulse_width_to_seconds,
    parse_pulsewidth_response,
)
from agilent_control.transports import FakeVisaResource


class ParsePulseWidthResponseTest(unittest.TestCase):
    def test_accepts_valid_line(self) -> None:
        self.assertEqual(parse_pulsewidth_response("VALUE 0.010\n"), 0.01)

    def test_rejects_invalid_prefix(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid pulse-width response"):
            parse_pulsewidth_response("WIDTH 0.010")

    def test_rejects_missing_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing a numeric payload"):
            parse_pulsewidth_response("VALUE ")

    def test_rejects_non_numeric_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid pulse-width value"):
            parse_pulsewidth_response("VALUE abc")


class ConvertPulseWidthToSecondsTest(unittest.TestCase):
    def test_supports_ns(self) -> None:
        self.assertAlmostEqual(convert_pulse_width_to_seconds(10, "ns"), 10e-9)

    def test_supports_us(self) -> None:
        self.assertAlmostEqual(convert_pulse_width_to_seconds(10, "us"), 10e-6)

    def test_supports_ms(self) -> None:
        self.assertAlmostEqual(convert_pulse_width_to_seconds(10, "ms"), 10e-3)


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
            ["VALUE 20.0", "VALUE 500.0"],
            width_range=PulseWidthRange(minimum_s=10e-9, maximum_s=100e-6),
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
