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
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

5. Run the smoke test against the real VISA resource:

```powershell
python scripts\windows_smoke_test.py "USB0::0x0957::0x2C07::MY12345678::INSTR"
```

## Notes

- `pyvisa` is an API wrapper. The Windows PC still needs a working VISA implementation such as Keysight IO Libraries Suite or NI-VISA.
- Most logic should be tested through `FakeVisaResource`; reserve real-device tests for smoke checks and end-to-end validation.
