# agilent-control

Python control helpers for the Keysight 33600A with a development workflow that supports local development and Windows hardware validation.

## Layout

- `agilent_control/`: instrument logic and transport helpers
- `agilent_control/tui.py`: Rich-based live operator TUI for TCP-to-AWG pulse-width and optional RF frequency sync
- `scripts/simple_tcp_client.py`: minimal raw `connect/send/recv` probe matching the known-good snippet
- `scripts/tcp_smoke_test.py`: one-shot raw TCP protocol diagnostic for the lab server
- `scripts/windows_smoke_test.py`: minimal real-device validation script for Windows
- `tests/`: unit tests that run without VISA drivers or hardware

## Recommended workflow

1. Edit and run unit tests locally.
2. Push changes to git.
3. Pull on the Windows test PC that has the actual VISA stack and instrument attached.
4. Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

5. Run the smoke test against the real VISA resource:

```powershell
python -m scripts.windows_smoke_test "USB0::0x0957::0x2C07::MY12345678::INSTR"
```

6. Run the TUI against the lab TCP server and the AWG:

```powershell
python -m agilent_control.tui "USB0::0x0957::0x0407::MY44036401::0::INSTR" 192.168.1.20 9000 --source-unit us
```

The TUI polls the TCP server by sending `GET pulsewidth\r\n`, accepts replies like `VALUE 0.010` or `VALUE 0.010\r\n`, converts the value using the selected source unit (`ns`, `us`, or `ms`), applies the full TTL pulse preset once, and then updates only the pulse width when the server value changes.

The optional second RF generator is disabled by default. Enable it in config mode or with `--rf-enable`, set its VISA resource, power in dBm, frequency unit (`Hz`, `kHz`, or `MHz`), and safe frequency limits. When enabled, the TUI sends `GET rffrequency\r\n` to the same TCP server, accepts `VALUE <number>` replies, configures the second generator as sine output with fixed dBm power and output ON, and then updates only frequency when it changes.

If TCP exchange is suspicious, run the raw protocol smoke test first:

```powershell
python -m scripts.tcp_smoke_test 192.168.1.20 9000 --timeout 2
```

It connects once, sends the exact production request bytes, prints the raw sent/received bytes, and reports whether the reply matches the expected `VALUE <number>` protocol, with or without a trailing CRLF.

If you want the smallest possible probe that matches the manual working snippet, run:

```powershell
python -m scripts.simple_tcp_client 192.168.1.20 9000 --timeout 0.1
```

This script does exactly one `recv(1024)` after sending `GET pulsewidth\r\n` and prints the raw decoded reply without applying the stricter CRLF/protocol validation used by `tcp_smoke_test.py`.

## TTL Single Pulse Example

Configure a single `0 V` to `5 V` pulse on the main output, with `10 Hz` base frequency, `10 us` width, and one pulse per external rising-edge trigger:

```python
import pyvisa

from agilent_control import Keysight33600A

rm = pyvisa.ResourceManager("@ivi")
inst = Keysight33600A(rm.open_resource("USB0::0x0957::0x0407::MY44036401::0::INSTR"))
inst.configure_ttl_single_pulse()
print(inst.read_ttl_single_pulse_config())
inst.close()
```

## Notes

- `pyvisa` is an API wrapper. The Windows PC still needs a working VISA implementation such as Keysight IO Libraries Suite or NI-VISA.
- The TUI uses `Rich` and is intended to run on the Windows lab PC with the AWG and VISA stack available.
- Most logic should be tested through `FakeVisaResource`; reserve real-device tests for smoke checks and end-to-end validation.
