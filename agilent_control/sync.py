from __future__ import annotations

import socket
from dataclasses import dataclass, field
from typing import Callable, Literal

from .instrument import Keysight33600A

SourceUnit = Literal["ns", "us", "ms"]
VALID_SOURCE_UNITS: tuple[SourceUnit, ...] = ("ns", "us", "ms")


def parse_pulsewidth_response(response: str) -> float:
    line = response.strip("\r\n")
    prefix = "VALUE "
    if not line.startswith(prefix):
        raise ValueError(f"Invalid pulse-width response: {response!r}")
    value = line[len(prefix) :].strip()
    if not value:
        raise ValueError("Pulse-width response is missing a numeric payload")
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid pulse-width value: {value!r}") from exc


def convert_pulse_width_to_seconds(value: float, source_unit: SourceUnit) -> float:
    if source_unit == "ns":
        return value * 1e-9
    if source_unit == "us":
        return value * 1e-6
    if source_unit == "ms":
        return value * 1e-3
    raise ValueError(f"Unsupported source unit: {source_unit!r}")


@dataclass(slots=True)
class PulseWidthRange:
    minimum_s: float = 10e-9
    maximum_s: float = 100e-6

    def validate(self, pulse_width_s: float) -> None:
        if pulse_width_s < self.minimum_s or pulse_width_s > self.maximum_s:
            raise ValueError(
                "pulse width must stay within "
                f"{self.minimum_s:.12g}s and {self.maximum_s:.12g}s"
            )


@dataclass(slots=True)
class PulseSyncConfig:
    visa_resource: str
    tcp_host: str
    tcp_port: int
    poll_interval_s: float = 0.5
    source_unit: SourceUnit = "us"
    frequency_hz: float = 10.0
    high_level_v: float = 5.0
    low_level_v: float = 0.0
    edge_time_s: float = 5e-9
    trigger_slope: str = "POS"
    reset_on_start: bool = True
    width_range: PulseWidthRange = field(default_factory=PulseWidthRange)


@dataclass(slots=True)
class PulseSyncState:
    tcp_connected: bool = False
    awg_connected: bool = False
    sync_active: bool = False
    paused: bool = False
    poll_in_progress: bool = False
    pending_reconfigure: bool = False
    startup_applied: bool = False
    last_response: str | None = None
    last_server_value: float | None = None
    last_width_s: float | None = None
    last_applied_width_s: float | None = None
    last_error: str | None = None
    last_poll_started_at: float | None = None
    last_success_at: float | None = None


class TcpPulseWidthClient:
    def __init__(self, host: str, port: int, timeout_s: float = 2.0) -> None:
        self.host = host
        self.port = port
        self.timeout_s = timeout_s
        self._socket: socket.socket | None = None

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None

    def _ensure_connected(self) -> socket.socket:
        if self._socket is None:
            self._socket = socket.create_connection((self.host, self.port), self.timeout_s)
            self._socket.settimeout(self.timeout_s)
        return self._socket

    def request_pulse_width(self) -> str:
        sock = self._ensure_connected()
        try:
            sock.sendall(b"GET pulsewidth\r\n")
            response = self._read_line(sock)
        except OSError:
            self.close()
            raise
        if response == "":
            self.close()
            raise ConnectionError("TCP server closed the connection without a response")
        return response

    def _read_line(self, sock: socket.socket) -> str:
        data = sock.recv(4096)
        if not data:
            return ""
        return data.decode("utf-8", "strict")


class PulseWidthSyncService:
    def __init__(
        self,
        instrument: Keysight33600A,
        config: PulseSyncConfig,
        fetch_response: Callable[[], str],
        state: PulseSyncState | None = None,
    ) -> None:
        self.instrument = instrument
        self.config = config
        self.fetch_response = fetch_response
        self.state = state or PulseSyncState()
        self.state.awg_connected = True

    def reset_startup(self) -> None:
        self.state.startup_applied = False
        self.state.sync_active = False
        self.state.pending_reconfigure = True

    def poll_once(self, now: float) -> PulseSyncState:
        self.state.last_poll_started_at = now
        if self.state.paused:
            self.state.sync_active = False
            self.state.last_error = None
            self.state.poll_in_progress = False
            return self.state

        self.state.poll_in_progress = True
        try:
            response = self.fetch_response()
            self.state.tcp_connected = True
            self.state.last_response = response.strip()
            server_value = parse_pulsewidth_response(response)
            pulse_width_s = convert_pulse_width_to_seconds(server_value, self.config.source_unit)
            self.config.width_range.validate(pulse_width_s)

            self.state.last_server_value = server_value
            self.state.last_width_s = pulse_width_s

            if not self.state.startup_applied:
                self.instrument.configure_ttl_single_pulse(
                    frequency_hz=self.config.frequency_hz,
                    pulse_width_s=pulse_width_s,
                    high_level_v=self.config.high_level_v,
                    low_level_v=self.config.low_level_v,
                    trigger_slope=self.config.trigger_slope,
                    edge_time_s=self.config.edge_time_s,
                    reset=self.config.reset_on_start,
                )
                self.state.startup_applied = True
                self.state.last_applied_width_s = pulse_width_s
            elif self.state.last_applied_width_s != pulse_width_s:
                self.instrument.set_pulse_width(pulse_width_s)
                self.state.last_applied_width_s = pulse_width_s

            self.state.sync_active = True
            self.state.pending_reconfigure = False
            self.state.last_error = None
            self.state.last_success_at = now
        except Exception as exc:
            self.state.sync_active = False
            self.state.last_error = str(exc)
            if isinstance(exc, OSError | ConnectionError):
                self.state.tcp_connected = False
        finally:
            self.state.poll_in_progress = False
        return self.state
