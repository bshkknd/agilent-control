param(
    [string]$Python = "py -3"
)

$ErrorActionPreference = "Stop"

Invoke-Expression "$Python -m venv .venv"
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "Windows environment is ready."
Write-Host "Next: .\.venv\Scripts\Activate.ps1"
Write-Host 'Then: python scripts\windows_smoke_test.py "USB0::...::INSTR"'
