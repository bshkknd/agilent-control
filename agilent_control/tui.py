from __future__ import annotations

import argparse
import os
import sys
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
    def __init__(self, config: PulseSyncConfig) -> None:
        self.config = config
        self.console = Console()
        self.state = PulseSyncState()
        self.instrument: Keysight33600A | None = None
        self.tcp_client: TcpPulseWidthClient | None = None
        self.service: PulseWidthSyncService | None = None
        self.should_exit = False
        self.next_poll_at = 0.0

    def run(self) -> int:
        with Live(self.render(), console=self.console, refresh_per_second=8, screen=True) as live:
            with KeyReader() as reader:
                self._connect_awg()
                self._ensure_tcp_client()
                self.next_poll_at = time.monotonic()
                while not self.should_exit:
                    self._handle_key(reader.read_key(), live)
                    now = time.monotonic()
                    if now >= self.next_poll_at:
                        self._poll(now)
                        self.next_poll_at = now + self.config.poll_interval_s
                    live.update(self.render())
                    time.sleep(0.05)
        self.close()
        return 0

    def close(self) -> None:
        if self.tcp_client is not None:
            self.tcp_client.close()
        if self.instrument is not None:
            self.instrument.close()

    def _connect_awg(self) -> None:
        if self.instrument is not None:
            self.instrument.close()
            self.instrument = None
        try:
            resource = open_pyvisa_resource(self.config.visa_resource)
            self.instrument = Keysight33600A(resource)
            self.state.awg_connected = True
            self.state.last_error = None
        except Exception as exc:
            self.state.awg_connected = False
            self.state.last_error = f"AWG connection failed: {exc}"
            return
        self._build_service()

    def _ensure_tcp_client(self) -> None:
        if self.tcp_client is not None:
            self.tcp_client.close()
        self.tcp_client = TcpPulseWidthClient(self.config.tcp_host, self.config.tcp_port)
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
        self.service.poll_once(now)

    def _handle_key(self, key: str | None, live: Live) -> None:
        if key is None:
            return
        if key.lower() == "q":
            self.should_exit = True
            return
        if key == " ":
            self.state.paused = not self.state.paused
            self.state.last_error = None
            return
        if key.lower() == "r":
            self._connect_awg()
            self._ensure_tcp_client()
            return
        if key.lower() == "u":
            current_index = VALID_SOURCE_UNITS.index(self.config.source_unit)
            self.config.source_unit = VALID_SOURCE_UNITS[(current_index + 1) % len(VALID_SOURCE_UNITS)]
            if self.service is not None:
                self.service.reset_startup()
            return
        if key.lower() == "t":
            self.config.trigger_slope = "NEG" if self.config.trigger_slope == "POS" else "POS"
            if self.service is not None:
                self.service.reset_startup()
            return
        if key.lower() == "x":
            self.config.reset_on_start = not self.config.reset_on_start
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
            setattr(self.config, field_name, caster(new_value))
            if field_name in {"tcp_host", "tcp_port"}:
                self._ensure_tcp_client()
            elif field_name == "visa_resource":
                self._connect_awg()
            elif self.service is not None:
                self.service.reset_startup()
        except Exception as exc:
            self.state.last_error = f"Input error: {exc}"
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
        table.add_row("AWG", "connected" if self.state.awg_connected else "disconnected")
        table.add_row("TCP", "connected" if self.state.tcp_connected else "disconnected")
        table.add_row("Sync", "paused" if self.state.paused else ("active" if self.state.sync_active else "idle"))
        table.add_row("Last poll", self._format_time(self.state.last_poll_started_at))
        table.add_row("Last success", self._format_time(self.state.last_success_at))
        table.add_row("Error", self.state.last_error or "-")
        return Panel(table, title="Status", border_style="green")

    def _render_value_panel(self) -> Panel:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="cyan")
        table.add_column()
        table.add_row("Raw response", self.state.last_response or "-")
        table.add_row(
            "Server value",
            "-" if self.state.last_server_value is None else f"{self.state.last_server_value:.12g} {self.config.source_unit}",
        )
        table.add_row("Converted width", self._format_width(self.state.last_width_s))
        table.add_row("Applied width", self._format_width(self.state.last_applied_width_s))
        return Panel(table, title="Pulse Width", border_style="blue")

    def _render_config_panel(self) -> Panel:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="cyan")
        table.add_column()
        entries = asdict(self.config)
        width_range = entries.pop("width_range")
        for key, value in entries.items():
            table.add_row(key, str(value))
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

    def _format_time(self, timestamp: float | None) -> str:
        if timestamp is None:
            return "-"
        return time.strftime("%H:%M:%S", time.localtime())

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
