# J.A.R.V.I.S. — Starter Dashboard

## Requirements
- Windows 10/11
- Python 3.11 recommended
- Internet connection for installing packages

## Install
Open this folder in VS Code, open Terminal > New Terminal, then run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

If PowerShell blocks activation, run this in the same terminal session:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

This is build 0.1: it contains the animated visual dashboard only. Microphone, wake-word detection, AI responses and speech will be added in later steps. Do not put API keys directly in source code.
