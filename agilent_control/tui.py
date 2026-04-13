from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from dataclasses import asdict
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import Keysight33600A, open_pyvisa_resource
from .sync import (
    PulseSyncConfig,
    PulseSyncState,
    PulseWidthSyncService,
    TcpPulseWidthClient,
    VALID_SOURCE_UNITS,
)


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
            if not self._msvcrt.kbhit():
                return None
            key = self._msvcrt.getwch()
            if key in {"\x00", "\xe0"}:
                self._msvcrt.getwch()
                return None
            return key

        import select

        readable, _, _ = select.select([sys.stdin], [], [], 0)
        if not readable:
            return None
        return sys.stdin.read(1)


class AwgPulseSyncTui:
    HIGHLIGHT_TTL_S = 1.5

    def __init__(self, config: PulseSyncConfig) -> None:
        self.config = config
        self.console = Console()
        self.state = PulseSyncState()
        self.instrument: Keysight33600A | None = None
        self.tcp_client: TcpPulseWidthClient | None = None
        self.service: PulseWidthSyncService | None = None
        self.should_exit = False
        self.next_poll_at = 0.0
        self._poll_wake_event = threading.Event()
        self._poll_stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._highlighted_fields: dict[str, float] = {}
        self._highlight_lock = threading.Lock()

    def run(self) -> int:
        with Live(self.render(), console=self.console, refresh_per_second=12, screen=True) as live:
            with KeyReader() as reader:
                self._connect_awg()
                self._ensure_tcp_client()
                self.next_poll_at = time.monotonic()
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
        try:
            resource = open_pyvisa_resource(self.config.visa_resource)
            self.instrument = Keysight33600A(resource)
            self.state.awg_connected = True
            self.state.last_error = None
            self._mark_changed("awg_connected", "error")
        except Exception as exc:
            self.state.awg_connected = False
            self.state.last_error = f"AWG connection failed: {exc}"
            self._mark_changed("awg_connected", "error")
            return
        self._build_service()

    def _ensure_tcp_client(self) -> None:
        if self.tcp_client is not None:
            self.tcp_client.close()
        self.tcp_client = TcpPulseWidthClient(self.config.tcp_host, self.config.tcp_port)
        self.state.tcp_connected = False
        self._mark_changed("tcp_connected")
        self._build_service()

    def _build_service(self) -> None:
        if self.instrument is None or self.tcp_client is None:
            self.service = None
            return
        self.service = PulseWidthSyncService(
            instrument=self.instrument,
            config=self.config,
            fetch_response=self.tcp_client.request_pulse_width,
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
        if key.lower() == "q":
            self.should_exit = True
            return
        if key == " ":
            self._set_paused(not self.state.paused)
            return
        if key.lower() == "r":
            self._connect_awg()
            self._ensure_tcp_client()
            self._request_immediate_poll()
            return
        if key.lower() == "u":
            self._cycle_source_unit()
            return
        if key.lower() == "t":
            self.config.trigger_slope = "NEG" if self.config.trigger_slope == "POS" else "POS"
            self._mark_changed("trigger_slope")
            self._request_reconfigure()
            return
        if key.lower() == "x":
            self.config.reset_on_start = not self.config.reset_on_start
            self._mark_changed("reset_on_start")
            self._request_reconfigure()
            return

        prompts: dict[str, tuple[str, str, type[Any]]] = {
            "h": ("tcp_host", "TCP host", str),
            "o": ("tcp_port", "TCP port", int),
            "v": ("visa_resource", "AWG VISA resource", str),
            "i": ("poll_interval_s", "Poll interval seconds", float),
            "f": ("frequency_hz", "Pulse frequency Hz", float),
            "g": ("high_level_v", "High level volts", float),
            "l": ("low_level_v", "Low level volts", float),
            "e": ("edge_time_s", "Edge time seconds", float),
        }
        if key.lower() not in prompts:
            return

        field_name, prompt_label, caster = prompts[key.lower()]
        live.stop()
        try:
            current = getattr(self.config, field_name)
            self.console.print(f"{prompt_label} [{current}]: ", end="")
            new_value = input().strip()
            if not new_value:
                return
            self._set_config_field(field_name, caster(new_value))
        except Exception as exc:
            self.state.last_error = f"Input error: {exc}"
            self._mark_changed("error")
        finally:
            live.start()

    def render(self) -> Group:
        return Group(
            self._render_status_panel(),
            self._render_value_panel(),
            self._render_config_panel(),
            self._render_help_panel(),
        )

    def _render_status_panel(self) -> Panel:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="cyan")
        table.add_column()
        table.add_row("AWG", self._styled_value("awg_connected", "connected" if self.state.awg_connected else "disconnected"))
        table.add_row("TCP", self._styled_value("tcp_connected", "connected" if self.state.tcp_connected else "disconnected"))
        table.add_row("Sync", self._styled_value("sync_status", self._sync_status_text()))
        table.add_row("Last poll", self._styled_value("last_poll_started_at", self._format_elapsed(self.state.last_poll_started_at)))
        table.add_row("Last success", self._styled_value("last_success_at", self._format_elapsed(self.state.last_success_at)))
        table.add_row("Error", self._styled_value("error", self.state.last_error or "-"))
        return Panel(table, title="Status", border_style="green")

    def _render_value_panel(self) -> Panel:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="cyan")
        table.add_column()
        table.add_row("Raw response", self._styled_value("last_response", self.state.last_response or "-"))
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

    def _render_config_panel(self) -> Panel:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="cyan")
        table.add_column()
        entries = asdict(self.config)
        width_range = entries.pop("width_range")
        for key, value in entries.items():
            table.add_row(key, self._styled_value(key, str(value)))
        table.add_row("width_min_s", str(width_range["minimum_s"]))
        table.add_row("width_max_s", str(width_range["maximum_s"]))
        return Panel(table, title="Configuration", border_style="yellow")

    def _render_help_panel(self) -> Panel:
        text = Text()
        text.append("space", style="bold")
        text.append(" pause/resume  ")
        text.append("r", style="bold")
        text.append(" reconnect  ")
        text.append("u", style="bold")
        text.append(" cycle unit  ")
        text.append("t", style="bold")
        text.append(" toggle slope  ")
        text.append("x", style="bold")
        text.append(" toggle reset  ")
        text.append("h/o/v/i/f/g/l/e", style="bold")
        text.append(" edit config  ")
        text.append("q", style="bold")
        text.append(" quit")
        return Panel(text, title="Keys", border_style="magenta")

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

    def _set_paused(self, paused: bool) -> None:
        self.state.paused = paused
        self.state.last_error = None
        if paused:
            self.state.sync_active = False
        self._mark_changed("sync_status", "error")
        self._request_immediate_poll()

    def _cycle_source_unit(self) -> None:
        current_index = VALID_SOURCE_UNITS.index(self.config.source_unit)
        self.config.source_unit = VALID_SOURCE_UNITS[(current_index + 1) % len(VALID_SOURCE_UNITS)]
        self._mark_changed("source_unit")
        self._request_reconfigure()

    def _set_config_field(self, field_name: str, value: Any) -> None:
        setattr(self.config, field_name, value)
        self._mark_changed(field_name)
        if field_name in {"tcp_host", "tcp_port"}:
            self._ensure_tcp_client()
            self._request_immediate_poll()
            return
        if field_name == "visa_resource":
            self._connect_awg()
            self._request_immediate_poll()
            return
        self._request_reconfigure()

    def _request_reconfigure(self) -> None:
        if self.service is not None:
            self.service.reset_startup()
        else:
            self.state.pending_reconfigure = True
            self.state.sync_active = False
        self._mark_changed("sync_status")
        self._request_immediate_poll()

    def _request_immediate_poll(self) -> None:
        self.next_poll_at = time.monotonic()
        self._poll_wake_event.set()

    def _state_snapshot(self) -> dict[str, object]:
        return {
            "awg_connected": self.state.awg_connected,
            "tcp_connected": self.state.tcp_connected,
            "sync_status": self._sync_status_text(),
            "error": self.state.last_error,
            "last_response": self.state.last_response,
            "last_server_value": self.state.last_server_value,
            "last_width_s": self.state.last_width_s,
            "last_applied_width_s": self.state.last_applied_width_s,
            "last_poll_started_at": self.state.last_poll_started_at,
            "last_success_at": self.state.last_success_at,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live TUI for syncing AWG pulse width from a TCP server.")
    parser.add_argument("visa_resource", help="VISA resource string for the Keysight 33600A")
    parser.add_argument("tcp_host", help="TCP host providing pulse-width values")
    parser.add_argument("tcp_port", type=int, help="TCP port providing pulse-width values")
    parser.add_argument("--poll-interval", type=float, default=0.5, help="Polling interval in seconds")
    parser.add_argument(
        "--source-unit",
        choices=VALID_SOURCE_UNITS,
        default="us",
        help="Unit used by the numeric value returned from the TCP server",
    )
    parser.add_argument("--frequency", type=float, default=10.0, help="TTL pulse repetition frequency in Hz")
    parser.add_argument("--high-level", type=float, default=5.0, help="TTL high voltage level")
    parser.add_argument("--low-level", type=float, default=0.0, help="TTL low voltage level")
    parser.add_argument("--edge-time", type=float, default=5e-9, help="Pulse edge time in seconds")
    parser.add_argument(
        "--trigger-slope",
        choices=("POS", "NEG"),
        default="POS",
        help="External trigger slope used by the AWG",
    )
    parser.add_argument(
        "--no-reset-on-start",
        action="store_true",
        help="Skip *RST when applying the initial TTL pulse preset",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = PulseSyncConfig(
        visa_resource=args.visa_resource,
        tcp_host=args.tcp_host,
        tcp_port=args.tcp_port,
        poll_interval_s=args.poll_interval,
        source_unit=args.source_unit,
        frequency_hz=args.frequency,
        high_level_v=args.high_level,
        low_level_v=args.low_level,
        edge_time_s=args.edge_time,
        trigger_slope=args.trigger_slope,
        reset_on_start=not args.no_reset_on_start,
    )
    app = AwgPulseSyncTui(config)
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
