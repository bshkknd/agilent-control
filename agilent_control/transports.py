from __future__ import annotations

from dataclasses import dataclass, field


def list_pyvisa_resources() -> tuple[str, ...]:
    try:
        import pyvisa
    except ImportError as exc:
        raise RuntimeError(
            "pyvisa is required on the target machine. Install project dependencies first."
        ) from exc

    manager = pyvisa.ResourceManager()
    return tuple(str(resource) for resource in manager.list_resources())


def open_pyvisa_resource(resource_name: str, timeout_ms: int = 5000):
    try:
        import pyvisa
    except ImportError as exc:
        raise RuntimeError(
            "pyvisa is required on the target machine. Install project dependencies first."
        ) from exc

    manager = pyvisa.ResourceManager()
    resource = manager.open_resource(resource_name)
    resource.timeout = timeout_ms
    return resource


@dataclass(slots=True)
class FakeVisaResource:
    responses: dict[str, str] = field(default_factory=dict)
    writes: list[str] = field(default_factory=list)
    is_closed: bool = False

    def query(self, command: str) -> str:
        if command not in self.responses:
            raise KeyError(f"No fake response configured for {command!r}")
        return self.responses[command]

    def write(self, command: str) -> None:
        self.writes.append(command)

    def close(self) -> None:
        self.is_closed = True
