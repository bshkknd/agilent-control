from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from agilent_control.sync import PulseSyncConfig, PulseSyncState

if importlib.util.find_spec("rich") is not None:
    from agilent_control.tui import AwgPulseSyncTui, CONFIG_FIELDS
else:
    AwgPulseSyncTui = None
    CONFIG_FIELDS = ()


@unittest.skipIf(AwgPulseSyncTui is None, "rich is not installed")
class AwgPulseSyncTuiTest(unittest.TestCase):
    def make_app(self) -> AwgPulseSyncTui:
        return AwgPulseSyncTui(
            PulseSyncConfig(
                visa_resource="USB0::TEST",
                tcp_host="127.0.0.1",
                tcp_port=9000,
            ),
            config_path=Path.cwd() / "test_awg_tui_config.json",
        )

    def test_mark_changed_expires_after_ttl(self) -> None:
        app = self.make_app()

        app._mark_changed("source_unit", at=10.0)

        self.assertTrue(app._is_highlighted("source_unit", now=10.5))
        self.assertFalse(app._is_highlighted("source_unit", now=12.0))

    def test_set_paused_updates_status_immediately(self) -> None:
        app = self.make_app()
        app.state = PulseSyncState(sync_active=True)

        app._set_paused(True)

        self.assertTrue(app.state.paused)
        self.assertEqual(app._sync_status_text(), "paused")
        self.assertFalse(app._is_highlighted("sync_status"))

    def test_adjust_selected_field_toggles_reset(self) -> None:
        app = self.make_app()
        app.config_index = 10

        app._adjust_selected_field(direction=1)

        self.assertFalse(app.config.reset_on_start)

    def test_cycle_source_unit_marks_field_and_requests_reconfigure(self) -> None:
        app = self.make_app()
        app.config_index = 4

        app._adjust_selected_field(direction=1)

        self.assertEqual(app.config.source_unit, "ms")
        self.assertTrue(app.state.pending_reconfigure)
        self.assertTrue(app._is_highlighted("source_unit"))

    def test_cycle_rf_frequency_unit_marks_field_and_requests_reconfigure(self) -> None:
        app = self.make_app()
        app.config_index = next(index for index, field in enumerate(CONFIG_FIELDS) if field.key == "rf.source_unit")

        app._adjust_selected_field(direction=1)

        self.assertEqual(app.config.rf.source_unit, "kHz")
        self.assertTrue(app.state.pending_reconfigure)
        self.assertTrue(app._is_highlighted("rf.source_unit"))

    def test_apply_config_change_persists_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "awg_tui_config.json"
            app = AwgPulseSyncTui(
                PulseSyncConfig(visa_resource="USB0::TEST", tcp_host="127.0.0.1", tcp_port=9000),
                config_path=path,
            )

            app._apply_config_change(CONFIG_FIELDS[2], 9001)

            self.assertTrue(path.exists())
            self.assertEqual(app.config.tcp_port, 9001)

    def test_open_resource_picker_populates_items(self) -> None:
        app = self.make_app()

        from unittest.mock import patch

        with patch("agilent_control.tui.list_pyvisa_resources", return_value=("USB0::A", "TCPIP0::B")):
            app._open_resource_picker()

        self.assertTrue(app.resource_picker_active)
        self.assertEqual(app.resource_picker_items, ["USB0::A", "TCPIP0::B"])

    def test_resource_picker_selection_updates_config(self) -> None:
        app = self.make_app()
        app.config_index = 0
        app.resource_picker_active = True
        app.resource_picker_items = ["USB0::A", "USB0::B"]
        app.resource_picker_index = 1

        app._handle_resource_picker_key("ENTER")

        self.assertFalse(app.resource_picker_active)
        self.assertEqual(app.config.visa_resource, "USB0::B")

    def test_resource_picker_selection_updates_rf_config(self) -> None:
        app = self.make_app()
        app.config_index = next(index for index, field in enumerate(CONFIG_FIELDS) if field.key == "rf.visa_resource")
        app.resource_picker_active = True
        app.resource_picker_items = ["USB0::A", "USB0::RF"]
        app.resource_picker_index = 1

        app._handle_resource_picker_key("ENTER")

        self.assertFalse(app.resource_picker_active)
        self.assertEqual(app.config.rf.visa_resource, "USB0::RF")

    def test_resource_picker_cancel_keeps_value(self) -> None:
        app = self.make_app()
        app.config_index = 0
        app.resource_picker_active = True
        app.resource_picker_items = ["USB0::A"]
        app.resource_picker_index = 0
        original = app.config.visa_resource

        app._handle_resource_picker_key("ESC")

        self.assertFalse(app.resource_picker_active)
        self.assertEqual(app.config.visa_resource, original)


if __name__ == "__main__":
    unittest.main()
