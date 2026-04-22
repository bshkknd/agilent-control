from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import Keysight33600A, list_pyvisa_resources, open_pyvisa_resource
from .sync import (
    PulseSyncConfig,
    PulseSyncState,
    PulseWidthSyncService,
    TcpPulseWidthClient,
    VALID_FREQUENCY_UNITS,
    VALID_SOURCE_UNITS,
    load_pulse_sync_config,
    save_pulse_sync_config,
)

CONFIG_FILE_NAME = "awg_tui_config.json"


@dataclass(frozen=True, slots=True)
class ConfigField:
    key: str
    label: str
    value_type: str
    reconfigure: bool = True


@dataclass(frozen=True, slots=True)
class ConfigGroup:
    label: str
    fields: tuple[ConfigField, ...]


CONFIG_GROUPS: tuple[ConfigGroup, ...] = (
    ConfigGroup(
        "TCP",
        (
            ConfigField("tcp_host", "Host", "text", reconfigure=False),
            ConfigField("tcp_port", "Port", "int", reconfigure=False),
            ConfigField("poll_interval_s", "Poll interval seconds", "float"),
        ),
    ),
    ConfigGroup(
        "Pulse AWG",
        (
            ConfigField("visa_resource", "VISA resource", "text", reconfigure=False),
            ConfigField("source_unit", "Source unit", "choice"),
            ConfigField("frequency_hz", "Pulse frequency Hz", "float"),
            ConfigField("high_level_v", "High level volts", "float"),
            ConfigField("low_level_v", "Low level volts", "float"),
            ConfigField("edge_time_s", "Edge time seconds", "float"),
            ConfigField("trigger_slope", "Trigger slope", "choice"),
        ),
    ),
    ConfigGroup(
        "RF Generator",
        (
            ConfigField("rf.enabled", "Enabled", "bool"),
            ConfigField("rf.visa_resource", "VISA resource", "text", reconfigure=False),
            ConfigField("rf.amplitude_dbm", "Power dBm", "float"),
            ConfigField("rf.source_unit", "Frequency unit", "choice"),
        ),
    ),
    ConfigGroup(
        "Safety",
        (
            ConfigField("reset_on_start", "Reset on start", "bool"),
            ConfigField("width_range.minimum_s", "Width min seconds", "float", reconfigure=False),
            ConfigField("width_range.maximum_s", "Width max seconds", "float", reconfigure=False),
            ConfigField("rf.frequency_range.minimum_hz", "RF frequency min Hz", "float", reconfigure=False),
            ConfigField("rf.frequency_range.maximum_hz", "RF frequency max Hz", "float", reconfigure=False),
        ),
    ),
)
CONFIG_FIELDS: tuple[ConfigField, ...] = tuple(field for group in CONFIG_GROUPS for field in group.fields)


class KeyReader:
    def __enter__(self) -> "KeyReader":
        if os.name == "nt":
            import msvcrt

            self._msvcrt = msvcrt
            return self

        import termios
        import tty

        self._termios = termios
        self._stdin_fd = sys.stdin.fileno()
        self._old_settings = termios.tcgetattr(self._stdin_fd)
        tty.setcbreak(self._stdin_fd)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if os.name != "nt":
            self._termios.tcsetattr(self._stdin_fd, self._termios.TCSADRAIN, self._old_settings)

    def read_key(self) -> str | None:
        if os.name == "nt":
            return self._read_windows_key()
        return self._read_posix_key()

    def _read_windows_key(self) -> str | None:
        if not self._msvcrt.kbhit():
            return None
        key = self._msvcrt.getwch()
        if key in {"\x00", "\xe0"}:
            special = self._msvcrt.getwch()
            mapping = {"H": "UP", "P": "DOWN", "K": "LEFT", "M": "RIGHT", "\x0f": "SHIFT_TAB"}
            return mapping.get(special)
        if key == "\r":
            return "ENTER"
        if key == "\x1b":
            return "ESC"
        if key == "\t":
            return "TAB"
        if key == "\x0f":
            return "SHIFT_TAB"
        return key.lower()

    def _read_posix_key(self) -> str | None:
        import select

        readable, _, _ = select.select([sys.stdin], [], [], 0)
        if not readable:
            return None
        key = sys.stdin.read(1)
        if key == "\n":
            return "ENTER"
        if key == "\t":
            return "TAB"
        if key != "\x1b":
            return key.lower()
        readable, _, _ = select.select([sys.stdin], [], [], 0.01)
        if not readable:
            return "ESC"
        second = sys.stdin.read(1)
        if second != "[":
            return "ESC"
        third = sys.stdin.read(1)
        mapping = {"A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT", "Z": "SHIFT_TAB"}
        return mapping.get(third)


class AwgPulseSyncTui:
    HIGHLIGHT_TTL_S = 1.5

    def __init__(self, config: PulseSyncConfig, config_path: Path | None = None) -> None:
        self.config = config
        self.config_path = (config_path or Path.cwd() / CONFIG_FILE_NAME).resolve()
        self.console = Console()
        self.state = PulseSyncState()
        self.instrument: Keysight33600A | None = None
        self.rf_instrument: Keysight33600A | None = None
        self.tcp_client: TcpPulseWidthClient | None = None
        self.service: PulseWidthSyncService | None = None
        self.should_exit = False
        self.next_poll_at = 0.0
        self.config_mode = False
        self.config_group_index = 0
        self.config_field_index = 0
        self._poll_wake_event = threading.Event()
        self._poll_stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._highlighted_fields: dict[str, float] = {}
        self._highlight_lock = threading.Lock()
        self.resource_picker_active = False
        self.resource_picker_index = 0
        self.resource_picker_items: list[str] = []

    @property
    def config_index(self) -> int:
        index = 0
        for group_index, group in enumerate(CONFIG_GROUPS):
            if group_index == self.config_group_index:
                return index + self.config_field_index
            index += len(group.fields)
        return 0

    @config_index.setter
    def config_index(self, index: int) -> None:
        remaining = index % len(CONFIG_FIELDS)
        for group_index, group in enumerate(CONFIG_GROUPS):
            if remaining < len(group.fields):
                self.config_group_index = group_index
                self.config_field_index = remaining
                return
            remaining -= len(group.fields)
        self.config_group_index = 0
        self.config_field_index = 0

    def run(self) -> int:
        self._connect_awg()
        self._connect_rf()
        self._ensure_tcp_client()
        self.next_poll_at = time.monotonic()
        with Live(self.render(), console=self.console, refresh_per_second=12, screen=True) as live:
            with KeyReader() as reader:
                self._start_poll_worker()
                while not self.should_exit:
                    self._handle_key(reader.read_key(), live)
                    live.update(self.render())
                    time.sleep(0.02)
        self._stop_poll_worker()
        self.close()
        return 0

    def close(self) -> None:
        if self.tcp_client is not None:
            self.tcp_client.close()
        if self.instrument is not None:
            self.instrument.close()
        if self.rf_instrument is not None:
            self.rf_instrument.close()

    def _start_poll_worker(self) -> None:
        if self._poll_thread is not None and self._poll_thread.is_alive():
            return
        self._poll_stop_event.clear()
        self._poll_wake_event.set()
        self._poll_thread = threading.Thread(target=self._poll_worker, daemon=True)
        self._poll_thread.start()

    def _stop_poll_worker(self) -> None:
        self._poll_stop_event.set()
        self._poll_wake_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=2.5)
            self._poll_thread = None

    def _poll_worker(self) -> None:
        while not self._poll_stop_event.is_set():
            if self.service is None:
                self._poll_wake_event.wait(0.1)
                self._poll_wake_event.clear()
                continue

            wait_time = max(0.0, self.next_poll_at - time.monotonic())
            woke_early = self._poll_wake_event.wait(wait_time)
            self._poll_wake_event.clear()
            if self._poll_stop_event.is_set():
                break
            if woke_early and time.monotonic() < self.next_poll_at and not self.state.pending_reconfigure:
                continue
            self._poll(time.monotonic())

    def _connect_awg(self) -> None:
        if self.instrument is not None:
            self.instrument.close()
            self.instrument = None
        if not self.config.visa_resource:
            self.state.awg_connected = False
            self.state.last_error = "Missing AWG VISA resource"
            self._build_service()
            return
        try:
            resource = open_pyvisa_resource(self.config.visa_resource)
            self.instrument = Keysight33600A(resource)
            self.state.awg_connected = True
            self.state.last_error = None
        except Exception as exc:
            self.state.awg_connected = False
            self.state.last_error = f"AWG connection failed: {exc}"
            self._build_service()
            return
        self._build_service()

    def _connect_rf(self) -> None:
        if self.rf_instrument is not None:
            self.rf_instrument.close()
            self.rf_instrument = None
        if not self.config.rf.enabled:
            self.state.rf_connected = False
            self.state.last_applied_rf_frequency_hz = None
            self._build_service()
            return
        if not self.config.rf.visa_resource:
            self.state.rf_connected = False
            self.state.last_error = "Missing RF VISA resource"
            self._build_service()
            return
        try:
            resource = open_pyvisa_resource(self.config.rf.visa_resource)
            self.rf_instrument = Keysight33600A(resource)
            self.state.rf_connected = True
            self.state.last_error = None
        except Exception as exc:
            self.state.rf_connected = False
            self.state.last_error = f"RF connection failed: {exc}"
            self._build_service()
            return
        self._build_service()

    def _ensure_tcp_client(self) -> None:
        if self.tcp_client is not None:
            self.tcp_client.close()
        if not self.config.tcp_host or self.config.tcp_port <= 0:
            self.tcp_client = None
            self.state.tcp_connected = False
            if self.state.last_error is None:
                self.state.last_error = "Missing TCP host or port"
            self._build_service()
            return
        self.tcp_client = TcpPulseWidthClient(self.config.tcp_host, self.config.tcp_port)
        self.state.tcp_connected = False
        self._build_service()

    def _build_service(self) -> None:
        if self.instrument is None or self.tcp_client is None:
            self.service = None
            return
        self.service = PulseWidthSyncService(
            instrument=self.instrument,
            config=self.config,
            fetch_response=self.tcp_client.request_pulse_width,
            rf_instrument=self.rf_instrument,
            fetch_rf_response=self.tcp_client.request_rf_frequency,
            state=self.state,
        )
        self.service.reset_startup()

    def _poll(self, now: float) -> None:
        if self.service is None:
            self._connect_awg()
            self._ensure_tcp_client()
        if self.service is None:
            return
        before = self._state_snapshot()
        self.service.poll_once(now)
        self.next_poll_at = time.monotonic() + self.config.poll_interval_s
        self._mark_state_changes(before)

    def _handle_key(self, key: str | None, live: Live) -> None:
        if key is None:
            return
        if key == "q":
            self.should_exit = True
            return
        if key == " ":
            self._set_paused(not self.state.paused)
            return
        if key == "r":
            self._connect_awg()
            self._connect_rf()
            self._ensure_tcp_client()
            self._request_immediate_poll()
            return
        if key == "c":
            self.resource_picker_active = False
            self.config_mode = not self.config_mode
            return
        if not self.config_mode:
            return
        if self.resource_picker_active:
            self._handle_resource_picker_key(key)
            return
        if key == "ESC":
            self.config_mode = False
            return
        if key == "UP":
            self._move_config_field(-1)
            return
        if key == "DOWN":
            self._move_config_field(1)
            return
        if key == "TAB":
            self._move_config_group(1)
            return
        if key == "SHIFT_TAB":
            self._move_config_group(-1)
            return
        if key in {"LEFT", "RIGHT"}:
            self._adjust_selected_field(direction=1 if key == "RIGHT" else -1)
            return
        if key == "ENTER":
            self._edit_selected_field(live)

    def render(self) -> Group:
        renderables = [
            self._render_status_panel(),
            self._render_value_panel(),
            self._render_rf_panel(),
            self._render_help_panel(),
        ]
        if self.config_mode:
            renderables.insert(3, self._render_config_panel())
        if self.resource_picker_active:
            insert_at = 4 if self.config_mode else 3
            renderables.insert(insert_at, self._render_resource_picker_panel())
        return Group(*renderables)

    def _render_status_panel(self) -> Panel:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="cyan")
        table.add_column()
        table.add_row(self._connection_leds())
        table.add_row("Sync", self._sync_status_text())
        table.add_row("Last success", self._format_elapsed(self.state.last_success_at))
        table.add_row("Error", self.state.last_error or "-")
        if self.config_mode or self._has_config_error():
            table.add_row("Config file", str(self.config_path))
        return Panel(table, title="Status", border_style="green")

    def _render_value_panel(self) -> Panel:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="cyan")
        table.add_column()
        table.add_row(
            "Server value",
            self._styled_value(
                "last_server_value",
                "-" if self.state.last_server_value is None else f"{self.state.last_server_value:.12g} {self.config.source_unit}",
            ),
        )
        table.add_row("Converted width", self._styled_value("last_width_s", self._format_width(self.state.last_width_s)))
        table.add_row("Applied width", self._styled_value("last_applied_width_s", self._format_width(self.state.last_applied_width_s)))
        return Panel(table, title="Pulse Width", border_style="blue")

    def _render_rf_panel(self) -> Panel:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="cyan")
        table.add_column()
        if not self.config.rf.enabled:
            table.add_row("RF", "disabled")
            return Panel(table, title="RF Generator", border_style="cyan")
        table.add_row(
            "Server value",
            self._styled_value(
                "last_rf_server_value",
                "-"
                if self.state.last_rf_server_value is None
                else f"{self.state.last_rf_server_value:.12g} {self.config.rf.source_unit}",
            ),
        )
        table.add_row(
            "Converted frequency",
            self._styled_value("last_rf_frequency_hz", self._format_frequency(self.state.last_rf_frequency_hz)),
        )
        table.add_row(
            "Applied frequency",
            self._styled_value(
                "last_applied_rf_frequency_hz",
                self._format_frequency(self.state.last_applied_rf_frequency_hz),
            ),
        )
        return Panel(table, title="RF Generator", border_style="cyan")

    def _render_config_panel(self) -> Panel:
        group = CONFIG_GROUPS[self.config_group_index]
        table = Table.grid(padding=(0, 2))
        table.add_column(style="cyan")
        table.add_column()
        for index, field in enumerate(group.fields):
            label = field.label
            value_text = Text(self._display_config_value(field.key))
            if index == self.config_field_index:
                label = f"> {label}"
                value_text.stylize("bold white on dark_green")
            table.add_row(label, value_text)
        title = f"Config: {group.label} [{self.config_group_index + 1}/{len(CONFIG_GROUPS)}]"
        return Panel(table, title=title, border_style="yellow")

    def _render_help_panel(self) -> Panel:
        text = Text()
        text.append("space", style="bold")
        text.append(" pause  ")
        text.append("r", style="bold")
        text.append(" reconnect  ")
        text.append("c", style="bold")
        text.append(" config  ")
        text.append("q", style="bold")
        text.append(" quit")
        if self.config_mode:
            text.append("  ")
            text.append("up/down", style="bold")
            text.append(" select  ")
            text.append("left/right", style="bold")
            text.append(" change  ")
            text.append("tab", style="bold")
            text.append(" group  ")
            text.append("enter", style="bold")
            text.append(" edit  ")
            text.append("esc", style="bold")
            text.append(" exit")
        return Panel(text, title="Keys", border_style="magenta")

    def _render_resource_picker_panel(self) -> Panel:
        if not self.resource_picker_active:
            return Panel(Text(""), title="VISA Picker", border_style="dim")

        table = Table.grid(padding=(0, 2))
        table.add_column()
        if not self.resource_picker_items:
            table.add_row("No VISA resources discovered")
        else:
            for index, item in enumerate(self.resource_picker_items):
                value = Text(item)
                if index == self.resource_picker_index:
                    value.stylize("bold white on dark_blue")
                    table.add_row(f"> {value.plain}", value)
                else:
                    table.add_row(" ", value)
        return Panel(table, title="VISA Picker", border_style="cyan")

    def _sync_status_text(self) -> str:
        if self.state.paused:
            return "paused"
        if self.state.poll_in_progress:
            return "polling"
        if self.state.pending_reconfigure:
            return "reconfig pending"
        if self.state.last_error and not self.state.sync_active:
            return "error"
        if self.state.sync_active:
            return "active"
        return "idle"

    def _rf_status_text(self) -> str:
        if not self.config.rf.enabled:
            return "disabled"
        return "connected" if self.state.rf_connected else "disconnected"

    def _connection_leds(self) -> Text:
        text = Text()
        states = (
            ("AWG", "connected" if self.state.awg_connected else "disconnected"),
            ("RF", self._rf_status_text()),
            ("TCP", "connected" if self.state.tcp_connected else "disconnected"),
        )
        for index, (label, state) in enumerate(states):
            if index > 0:
                text.append("   ")
            text.append(label, style="cyan")
            text.append(" ")
            if state == "connected":
                text.append("●", style="green")
            elif state == "disabled":
                text.append("●", style="yellow")
            else:
                text.append("●", style="red")
            text.append(f" {state}")
        return text

    def _has_config_error(self) -> bool:
        if self.state.last_error is None:
            return False
        return self.state.last_error.startswith(("Config error:", "Input error:", "Config load error:"))

    def _set_paused(self, paused: bool) -> None:
        self.state.paused = paused
        self.state.last_error = None
        if paused:
            self.state.sync_active = False
        self._request_immediate_poll()

    def _display_config_value(self, key: str) -> str:
        return str(self._get_config_value(key))

    def _get_config_value(self, key: str) -> Any:
        value: Any = self.config
        for part in key.split("."):
            value = getattr(value, part)
        return value

    def _set_config_value(self, key: str, value: Any) -> None:
        parts = key.split(".")
        target: Any = self.config
        for part in parts[:-1]:
            target = getattr(target, part)
        setattr(target, parts[-1], value)

    def _selected_config_field(self) -> ConfigField:
        return CONFIG_GROUPS[self.config_group_index].fields[self.config_field_index]

    def _move_config_field(self, direction: int) -> None:
        group = CONFIG_GROUPS[self.config_group_index]
        self.config_field_index = (self.config_field_index + direction) % len(group.fields)

    def _move_config_group(self, direction: int) -> None:
        self.config_group_index = (self.config_group_index + direction) % len(CONFIG_GROUPS)
        group = CONFIG_GROUPS[self.config_group_index]
        self.config_field_index = min(self.config_field_index, len(group.fields) - 1)

    def _adjust_selected_field(self, direction: int) -> bool:
        field = self._selected_config_field()
        current = self._get_config_value(field.key)
        if field.key == "source_unit":
            index = VALID_SOURCE_UNITS.index(current)
            new_value = VALID_SOURCE_UNITS[(index + direction) % len(VALID_SOURCE_UNITS)]
        elif field.key == "rf.source_unit":
            index = VALID_FREQUENCY_UNITS.index(current)
            new_value = VALID_FREQUENCY_UNITS[(index + direction) % len(VALID_FREQUENCY_UNITS)]
        elif field.key == "trigger_slope":
            choices = ("POS", "NEG")
            index = choices.index(str(current).upper())
            new_value = choices[(index + direction) % len(choices)]
        elif field.key in {"reset_on_start", "rf.enabled"}:
            new_value = not bool(current)
        else:
            return False
        self._apply_config_change(field, new_value)
        return True

    def _edit_selected_field(self, live: Live) -> None:
        field = self._selected_config_field()
        if field.key in {"visa_resource", "rf.visa_resource"}:
            self._open_resource_picker()
            return
        if field.value_type in {"choice", "bool"}:
            return
        live.stop()
        try:
            current = self._get_config_value(field.key)
            self.console.print(f"{field.label} [{current}]: ", end="")
            raw_value = input().strip()
            if not raw_value:
                return
            value = self._cast_value(field.value_type, raw_value)
            self._apply_config_change(field, value)
        except Exception as exc:
            self.state.last_error = f"Input error: {exc}"
        finally:
            live.start()

    def _cast_value(self, value_type: str, raw_value: str) -> Any:
        if value_type == "text":
            return raw_value
        if value_type == "int":
            return int(raw_value)
        if value_type == "float":
            return float(raw_value)
        raise ValueError(f"Unsupported value type: {value_type}")

    def _apply_config_change(self, field: ConfigField, value: Any) -> None:
        previous = self._get_config_value(field.key)
        self._set_config_value(field.key, value)
        try:
            self.config.validate()
            self._persist_config()
        except Exception as exc:
            self._set_config_value(field.key, previous)
            self.state.last_error = f"Config error: {exc}"
            return
        self._mark_changed(field.key)
        if field.key in {"tcp_host", "tcp_port"}:
            self._ensure_tcp_client()
            self._request_immediate_poll()
            return
        if field.key == "visa_resource":
            self._connect_awg()
            self._request_immediate_poll()
            return
        if field.key in {"rf.enabled", "rf.visa_resource"}:
            self._connect_rf()
            self._request_reconfigure()
            return
        if field.reconfigure:
            self._request_reconfigure()

    def _persist_config(self) -> None:
        save_pulse_sync_config(self.config_path, self.config)

    def _request_reconfigure(self) -> None:
        if self.service is not None:
            self.service.reset_startup()
        else:
            self.state.pending_reconfigure = True
            self.state.sync_active = False
        self._request_immediate_poll()

    def _request_immediate_poll(self) -> None:
        self.next_poll_at = time.monotonic()
        self._poll_wake_event.set()

    def _state_snapshot(self) -> dict[str, object]:
        return {
            "last_response": self.state.last_response,
            "last_server_value": self.state.last_server_value,
            "last_width_s": self.state.last_width_s,
            "last_applied_width_s": self.state.last_applied_width_s,
            "last_rf_response": self.state.last_rf_response,
            "last_rf_server_value": self.state.last_rf_server_value,
            "last_rf_frequency_hz": self.state.last_rf_frequency_hz,
            "last_applied_rf_frequency_hz": self.state.last_applied_rf_frequency_hz,
        }

    def _mark_state_changes(self, before: dict[str, object]) -> None:
        after = self._state_snapshot()
        for field_name, value in after.items():
            if before.get(field_name) != value:
                self._mark_changed(field_name)

    def _mark_changed(self, *field_names: str, at: float | None = None) -> None:
        when = time.monotonic() if at is None else at
        with self._highlight_lock:
            for field_name in field_names:
                self._highlighted_fields[field_name] = when

    def _is_highlighted(self, field_name: str, now: float | None = None) -> bool:
        when = time.monotonic() if now is None else now
        with self._highlight_lock:
            changed_at = self._highlighted_fields.get(field_name)
            if changed_at is None:
                return False
            if when - changed_at > self.HIGHLIGHT_TTL_S:
                self._highlighted_fields.pop(field_name, None)
                return False
            return True

    def _styled_value(self, field_name: str, value: str) -> Text:
        if self._is_highlighted(field_name):
            return Text(str(value), style="bold black on bright_yellow")
        return Text(str(value))

    def _format_elapsed(self, timestamp: float | None) -> str:
        if timestamp is None:
            return "-"
        elapsed_s = max(0.0, time.monotonic() - timestamp)
        return f"{elapsed_s:.1f}s ago"

    def _format_width(self, pulse_width_s: float | None) -> str:
        if pulse_width_s is None:
            return "-"
        return f"{pulse_width_s:.12g} s / {pulse_width_s * 1e6:.12g} us"

    def _format_frequency(self, frequency_hz: float | None) -> str:
        if frequency_hz is None:
            return "-"
        return f"{frequency_hz:.12g} Hz / {frequency_hz / 1e6:.12g} MHz"

    def _open_resource_picker(self) -> None:
        try:
            self.resource_picker_items = list(list_pyvisa_resources())
            self.resource_picker_index = 0
            self.resource_picker_active = True
            if not self.resource_picker_items:
                self.state.last_error = "No VISA resources found"
        except Exception as exc:
            self.resource_picker_items = []
            self.resource_picker_active = False
            self.state.last_error = f"VISA discovery failed: {exc}"

    def _handle_resource_picker_key(self, key: str) -> None:
        if key == "ESC":
            self.resource_picker_active = False
            return
        if not self.resource_picker_items:
            return
        if key == "UP":
            self.resource_picker_index = (self.resource_picker_index - 1) % len(self.resource_picker_items)
            return
        if key == "DOWN":
            self.resource_picker_index = (self.resource_picker_index + 1) % len(self.resource_picker_items)
            return
        if key == "ENTER":
            self._apply_config_change(self._selected_config_field(), self.resource_picker_items[self.resource_picker_index])
            self.resource_picker_active = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live TUI for syncing AWG pulse width from a TCP server.")
    parser.add_argument("visa_resource", nargs="?", help="VISA resource string for the Keysight 33600A")
    parser.add_argument("tcp_host", nargs="?", help="TCP host providing pulse-width values")
    parser.add_argument("tcp_port", nargs="?", type=int, help="TCP port providing pulse-width values")
    parser.add_argument("--poll-interval", type=float, default=None, help="Polling interval in seconds")
    parser.add_argument(
        "--source-unit",
        choices=VALID_SOURCE_UNITS,
        default=None,
        help="Unit used by the numeric value returned from the TCP server",
    )
    parser.add_argument("--frequency", type=float, default=None, help="TTL pulse repetition frequency in Hz")
    parser.add_argument("--high-level", type=float, default=None, help="TTL high voltage level")
    parser.add_argument("--low-level", type=float, default=None, help="TTL low voltage level")
    parser.add_argument("--edge-time", type=float, default=None, help="Pulse edge time in seconds")
    parser.add_argument(
        "--trigger-slope",
        choices=("POS", "NEG"),
        default=None,
        help="External trigger slope used by the AWG",
    )
    parser.add_argument(
        "--no-reset-on-start",
        action="store_true",
        help="Skip *RST when applying the initial TTL pulse preset",
    )
    parser.add_argument("--rf-enable", action="store_true", help="Enable the second RF function generator")
    parser.add_argument("--rf-visa-resource", default=None, help="VISA resource string for the RF generator")
    parser.add_argument("--rf-amplitude", type=float, default=None, help="RF sine power in dBm")
    parser.add_argument(
        "--rf-source-unit",
        choices=VALID_FREQUENCY_UNITS,
        default=None,
        help="Unit used by the RF frequency value returned from the TCP server",
    )
    parser.add_argument("--rf-min-frequency", type=float, default=None, help="Minimum safe RF frequency in Hz")
    parser.add_argument("--rf-max-frequency", type=float, default=None, help="Maximum safe RF frequency in Hz")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = (Path.cwd() / CONFIG_FILE_NAME).resolve()
    config = PulseSyncConfig(visa_resource="", tcp_host="", tcp_port=0)
    if config_path.exists():
        try:
            config = load_pulse_sync_config(config_path, base=config)
        except Exception as exc:
            print(f"Config load error: {exc}", file=sys.stderr)
    overrides = {
        "visa_resource": args.visa_resource,
        "tcp_host": args.tcp_host,
        "tcp_port": args.tcp_port,
        "poll_interval_s": args.poll_interval,
        "source_unit": args.source_unit,
        "frequency_hz": args.frequency,
        "high_level_v": args.high_level,
        "low_level_v": args.low_level,
        "edge_time_s": args.edge_time,
        "trigger_slope": args.trigger_slope,
    }
    for key, value in overrides.items():
        if value is not None:
            setattr(config, key, value)
    if args.no_reset_on_start:
        config.reset_on_start = False
    if args.rf_enable:
        config.rf.enabled = True
    if args.rf_visa_resource is not None:
        config.rf.visa_resource = args.rf_visa_resource
    if args.rf_amplitude is not None:
        config.rf.amplitude_dbm = args.rf_amplitude
    if args.rf_source_unit is not None:
        config.rf.source_unit = args.rf_source_unit
    if args.rf_min_frequency is not None:
        config.rf.frequency_range.minimum_hz = args.rf_min_frequency
    if args.rf_max_frequency is not None:
        config.rf.frequency_range.maximum_hz = args.rf_max_frequency
    config.validate()
    app = AwgPulseSyncTui(config, config_path=config_path)
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
