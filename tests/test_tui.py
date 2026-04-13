from __future__ import annotations

import importlib.util
import unittest

from agilent_control.sync import PulseSyncConfig, PulseSyncState

if importlib.util.find_spec("rich") is not None:
    from agilent_control.tui import AwgPulseSyncTui
else:
    AwgPulseSyncTui = None


@unittest.skipIf(AwgPulseSyncTui is None, "rich is not installed")
class AwgPulseSyncTuiTest(unittest.TestCase):
    def make_app(self) -> AwgPulseSyncTui:
        return AwgPulseSyncTui(
            PulseSyncConfig(
                visa_resource="USB0::TEST",
                tcp_host="127.0.0.1",
                tcp_port=9000,
            )
        )

    def test_mark_changed_expires_after_ttl(self) -> None:
        app = self.make_app()

        app._mark_changed("source_unit", at=10.0)

        self.assertTrue(app._is_highlighted("source_unit", now=10.5))
        self.assertFalse(app._is_highlighted("source_unit", now=12.0))

    def test_cycle_source_unit_marks_field_and_requests_reconfigure(self) -> None:
        app = self.make_app()

        app._cycle_source_unit()

        self.assertEqual(app.config.source_unit, "ms")
        self.assertTrue(app.state.pending_reconfigure)
        self.assertTrue(app._is_highlighted("source_unit"))

    def test_set_paused_updates_status_immediately(self) -> None:
        app = self.make_app()
        app.state = PulseSyncState(sync_active=True)

        app._set_paused(True)

        self.assertTrue(app.state.paused)
        self.assertEqual(app._sync_status_text(), "paused")
        self.assertTrue(app._is_highlighted("sync_status"))


if __name__ == "__main__":
    unittest.main()
