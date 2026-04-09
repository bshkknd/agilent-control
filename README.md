# agilent-control

Python control helpers for the Keysight 33600A with a development workflow that supports macOS coding and Windows hardware validation.

## Layout

- `agilent_control/`: instrument logic and transport helpers
- `scripts/windows_smoke_test.py`: minimal real-device validation script for Windows
- `tests/`: unit tests that run without VISA drivers or hardware

## Recommended workflow

1. Edit and run unit tests on the MacBook.
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
- Most logic should be tested through `FakeVisaResource`; reserve real-device tests for smoke checks and end-to-end validation.
