from __future__ import annotations

import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agilent_control.sync import PulseSyncConfig, PulseSyncState

if importlib.util.find_spec("rich") is not None:
    from rich.console import Console

    from agilent_control.tui import AwgPulseSyncTui, CONFIG_FIELDS, CONFIG_GROUPS
else:
    AwgPulseSyncTui = None
    CONFIG_FIELDS = ()
    CONFIG_GROUPS = ()


@unittest.skipIf(AwgPulseSyncTui is None, "rich is not installed")
class AwgPulseSyncTuiTest(unittest.TestCase):
    def make_app(self) -> AwgPulseSyncTui:
        return AwgPulseSyncTui(
            PulseSyncConfig(
                visa_resource="USB0::TEST",
                tcp_host="127.0.0.1",
                tcp_port=9000,
            ),
            config_path=Path(tempfile.gettempdir()) / "test_awg_tui_config.json",
        )

    def select_config_field(self, app: AwgPulseSyncTui, key: str) -> None:
        app.config_index = next(index for index, field in enumerate(CONFIG_FIELDS) if field.key == key)

    def render_text(self, app: AwgPulseSyncTui) -> str:
        console = Console(file=io.StringIO(), record=True, width=120)
        console.print(app.render())
        return console.export_text()

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
        self.select_config_field(app, "reset_on_start")

        app._adjust_selected_field(direction=1)

        self.assertFalse(app.config.reset_on_start)

    def test_cycle_source_unit_marks_field_and_requests_reconfigure(self) -> None:
        app = self.make_app()
        self.select_config_field(app, "source_unit")

        app._adjust_selected_field(direction=1)

        self.assertEqual(app.config.source_unit, "ms")
        self.assertTrue(app.state.pending_reconfigure)
        self.assertTrue(app._is_highlighted("source_unit"))

    def test_cycle_rf_frequency_unit_marks_field_and_requests_reconfigure(self) -> None:
        app = self.make_app()
        self.select_config_field(app, "rf.source_unit")

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

            tcp_port = next(field for field in CONFIG_FIELDS if field.key == "tcp_port")
            app._apply_config_change(tcp_port, 9001)

            self.assertTrue(path.exists())
            self.assertEqual(app.config.tcp_port, 9001)

    def test_open_resource_picker_populates_items(self) -> None:
        app = self.make_app()

        with patch("agilent_control.tui.list_pyvisa_resources", return_value=("USB0::A", "TCPIP0::B")):
            app._open_resource_picker()

        self.assertTrue(app.resource_picker_active)
        self.assertEqual(app.resource_picker_items, ["USB0::A", "TCPIP0::B"])

    def test_resource_picker_selection_updates_config(self) -> None:
        app = self.make_app()
        self.select_config_field(app, "visa_resource")
        app.resource_picker_active = True
        app.resource_picker_items = ["USB0::A", "USB0::B"]
        app.resource_picker_index = 1

        app._handle_resource_picker_key("ENTER")

        self.assertFalse(app.resource_picker_active)
        self.assertEqual(app.config.visa_resource, "USB0::B")

    def test_resource_picker_selection_updates_rf_config(self) -> None:
        app = self.make_app()
        self.select_config_field(app, "rf.visa_resource")
        app.resource_picker_active = True
        app.resource_picker_items = ["USB0::A", "USB0::RF"]
        app.resource_picker_index = 1

        app._handle_resource_picker_key("ENTER")

        self.assertFalse(app.resource_picker_active)
        self.assertEqual(app.config.rf.visa_resource, "USB0::RF")

    def test_resource_picker_cancel_keeps_value(self) -> None:
        app = self.make_app()
        self.select_config_field(app, "visa_resource")
        app.resource_picker_active = True
        app.resource_picker_items = ["USB0::A"]
        app.resource_picker_index = 0
        original = app.config.visa_resource

        app._handle_resource_picker_key("ESC")

        self.assertFalse(app.resource_picker_active)
        self.assertEqual(app.config.visa_resource, original)

    def test_left_right_changes_config_group_when_field_is_not_adjustable(self) -> None:
        app = self.make_app()
        app.config_mode = True
        self.select_config_field(app, "tcp_host")

        app._handle_key("RIGHT", Mock())

        self.assertEqual(CONFIG_GROUPS[app.config_group_index].label, "Pulse AWG")
        self.assertEqual(app._selected_config_field().key, "visa_resource")

    def test_up_down_changes_selected_row_inside_active_config_group(self) -> None:
        app = self.make_app()
        app.config_mode = True
        self.select_config_field(app, "tcp_host")

        app._handle_key("DOWN", Mock())

        self.assertEqual(app._selected_config_field().key, "tcp_port")

    def test_left_right_toggles_choice_and_bool_fields(self) -> None:
        app = self.make_app()
        app.config.rf.visa_resource = "USB0::RF"
        app.config_mode = True
        self.select_config_field(app, "rf.enabled")

        app._handle_key("RIGHT", Mock())

        self.assertTrue(app.config.rf.enabled)
        self.assertEqual(CONFIG_GROUPS[app.config_group_index].label, "RF Generator")

    def test_enter_on_grouped_visa_fields_opens_picker(self) -> None:
        app = self.make_app()
        app.config_mode = True
        self.select_config_field(app, "rf.visa_resource")

        with patch("agilent_control.tui.list_pyvisa_resources", return_value=("USB0::RF",)):
            app._handle_key("ENTER", Mock())

        self.assertTrue(app.resource_picker_active)
        self.assertEqual(app.resource_picker_items, ["USB0::RF"])

    def test_normal_render_hides_configuration_and_inactive_picker(self) -> None:
        app = self.make_app()

        output = self.render_text(app)

        self.assertNotIn("Config:", output)
        self.assertNotIn("Configuration", output)
        self.assertNotIn("VISA Picker", output)
        self.assertNotIn("Config file", output)

    def test_config_render_shows_only_active_group(self) -> None:
        app = self.make_app()
        app.config_mode = True
        self.select_config_field(app, "tcp_host")

        output = self.render_text(app)

        self.assertIn("Config: TCP [1/4]", output)
        self.assertIn("Host", output)
        self.assertIn("Port", output)
        self.assertNotIn("High level volts", output)

    def test_rf_disabled_normal_render_is_compact(self) -> None:
        app = self.make_app()
        app.config.rf.enabled = False

        output = self.render_text(app)

        self.assertIn("RF Generator", output)
        self.assertIn("disabled", output)
        self.assertNotIn("Converted frequency", output)


if __name__ == "__main__":
    unittest.main()
