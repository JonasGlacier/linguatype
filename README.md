# LinguaType

A Windows system-tray translation tool that replaces selected (or all) text in any input field with a translated version, triggered by a configurable hotkey.

## Features

- **Global hotkeys** — assign different hotkeys to different target languages
- **Clipboard-only text pipeline** — uses simulated Ctrl+C / Ctrl+A / Ctrl+V for cross-app compatibility
- **Multiple engines** — Google Translate (free, no key), DeepL, OpenAI, Anthropic, Gemini, Grok, or OpenRouter
- **System tray** — lives quietly in the notification area; right-click for quick actions
- **Floating status window** — appears near the text cursor during translation, then disappears
- **Long-text confirmation** — asks before replacing text above a configurable character limit

## Requirements

- Windows 10 / 11
- Python 3.10+

## Installation

```bash
pip install -r requirements.txt
```

Key GUI dependencies: **CustomTkinter** (windows and widgets), **pystray** (system tray), and **Pillow** (tray icon).

## Running

```bash
python main.py
```

## Configuration

Settings are stored at `%APPDATA%\LinguaType\config.json` and can be edited through the Settings dialog (left-click the tray icon, or choose **Settings…** from the tray menu).

### Translation engines

| Engine | API key required | Notes |
|--------|-----------------|-------|
| Google Translate | No | Uses the public endpoint; may rate-limit heavy use |
| DeepL | Yes (free tier available) | High quality; get a key at [deepl.com](https://www.deepl.com/pro-api) |
| OpenAI | Yes | Uses `gpt-4o-mini` by default; model is configurable |
| Anthropic (Claude) | Yes | Uses `claude-3-5-sonnet-latest` by default |
| Google Gemini | Yes | Uses `gemini-1.5-flash` by default |
| xAI (Grok) | Yes | Uses `grok-2` by default |
| OpenRouter | Yes | Uses `google/gemini-2.5-flash` by default |

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
