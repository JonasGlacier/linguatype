# LinguaType

A Windows system-tray translation tool that replaces selected (or all) text in any input field with a translated version, triggered by a configurable hotkey.

## Features

- **Global hotkeys** — assign different hotkeys to different target languages
- **Clipboard-only text pipeline** — uses simulated Ctrl+C / Ctrl+A / Ctrl+V for cross-app compatibility
- **Multiple engines** — Google Translate (free, no key), DeepL, or OpenAI (GPT-4o-mini)
- **System tray** — lives quietly in the notification area; right-click for quick actions
- **Floating status window** — appears near the text cursor during translation, then disappears
- **Long-text confirmation** — asks before replacing text above a configurable character limit

## Requirements

- Windows 10 / 11
- Python 3.10+
- PySide6 (install separately or via the requirements below)

## Installation

```bash
pip install -r requirements.txt
```

## Running

```bash
python main.py
```

## Configuration

Settings are stored at `%APPDATA%\LinguaType\config.json` and can be edited through the Settings dialog (double-click the tray icon).

### Translation engines

| Engine | API key required | Notes |
|--------|-----------------|-------|
| Google Translate | No | Uses the public endpoint; may rate-limit heavy use |
| DeepL | Yes (free tier available) | High quality, get key at deepl.com |
| OpenAI | Yes | Uses `gpt-4o-mini` by default; model is configurable |

### Default hotkeys

| Hotkey | Target language |
|--------|----------------|
| Ctrl+Shift+1 | English |
| Ctrl+Shift+2 | Chinese (Simplified) |

Both hotkeys and languages are fully customizable in Settings → Hotkeys.

## Packaging as an executable

```bash
pip install pyinstaller
python -m PyInstaller --onefile --windowed --name LinguaType --icon=assets/icon.ico --add-data "assets;assets" main.py
```
