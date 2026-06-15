"""Configuration management for LinguaType.

Config is stored as JSON at %APPDATA%\\LinguaType\\config.json.
A dataclass schema provides typed access and default values.
"""

from __future__ import annotations

import json
import os
import sys
import winreg
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

_APP_NAME = "LinguaType"
_REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

@dataclass
class HotkeyEntry:
    lang: str = "en"
    shortcut: str = "ctrl+shift+1"
    label: str = "→ English"

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "HotkeyEntry":
        return HotkeyEntry(
            lang=d.get("lang", "en"),
            shortcut=d.get("shortcut", "ctrl+shift+1"),
            label=d.get("label", "→ English"),
        )


@dataclass
class ApiKeys:
    deepl: str = ""
    openai: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic: str = ""
    anthropic_model: str = "claude-3-5-sonnet-latest"
    gemini: str = ""
    gemini_model: str = "gemini-1.5-flash"
    grok: str = ""
    grok_model: str = "grok-2"
    openrouter: str = ""
    openrouter_model: str = "google/gemini-2.5-flash"

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "ApiKeys":
        return ApiKeys(
            deepl=d.get("deepl", ""),
            openai=d.get("openai", ""),
            openai_model=d.get("openai_model", "gpt-4o-mini"),
            anthropic=d.get("anthropic", ""),
            anthropic_model=d.get("anthropic_model", "claude-3-5-sonnet-latest"),
            gemini=d.get("gemini", ""),
            gemini_model=d.get("gemini_model", "gemini-1.5-flash"),
            grok=d.get("grok", ""),
            grok_model=d.get("grok_model", "grok-2"),
            openrouter=d.get("openrouter", ""),
            openrouter_model=d.get("openrouter_model", "google/gemini-2.5-flash"),
        )


@dataclass
class Config:
    engine: str = "google"  # "google" | "deepl" | "openai" | "anthropic" | "gemini" | "grok" | "openrouter"
    api_keys: ApiKeys = field(default_factory=ApiKeys)
    hotkeys: list[HotkeyEntry] = field(default_factory=lambda: [
        HotkeyEntry("en", "ctrl+shift+1", "→ English"),
        HotkeyEntry("zh-CN", "ctrl+shift+2", "→ 中文"),
    ])
    max_chars_confirm: int = 500
    autostart: bool = False
    translation_history: list[dict[str, str]] = field(default_factory=list)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Config":
        cfg = Config()
        cfg.engine = d.get("engine", "google")
        if "api_keys" in d:
            cfg.api_keys = ApiKeys.from_dict(d["api_keys"])
        if "hotkeys" in d:
            cfg.hotkeys = [HotkeyEntry.from_dict(h) for h in d["hotkeys"]]
        cfg.max_chars_confirm = d.get("max_chars_confirm", 500)
        cfg.autostart = d.get("autostart", False)
        cfg.translation_history = d.get("translation_history", [])
        return cfg

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "api_keys": asdict(self.api_keys),
            "hotkeys": [asdict(h) for h in self.hotkeys],
            "max_chars_confirm": self.max_chars_confirm,
            "autostart": self.autostart,
            "translation_history": self.translation_history[-50:],  # keep last 50
        }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _config_path() -> Path:
    appdata = os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
    directory = Path(appdata) / _APP_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "config.json"


def load_config() -> Config:
    path = _config_path()
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return Config.from_dict(json.load(f))
        except Exception:
            pass
    return Config()


def save_config(cfg: Config) -> None:
    path = _config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Autostart (registry)
# ---------------------------------------------------------------------------

def _exe_path() -> str:
    """Return the command to use for the autostart registry value."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return f'"{sys.executable}" "{Path(sys.argv[0]).resolve()}"'


def set_autostart(enabled: bool) -> None:
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _REG_RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        )
        if enabled:
            winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _exe_path())
        else:
            try:
                winreg.DeleteValue(key, _APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except OSError:
        pass


def get_autostart() -> bool:
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _REG_RUN_KEY,
            0,
            winreg.KEY_READ,
        )
        try:
            winreg.QueryValueEx(key, _APP_NAME)
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            winreg.CloseKey(key)
            return False
    except OSError:
        return False


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------

_MAX_HISTORY = 50


def add_history(cfg: Config, source: str, result: str, lang: str) -> None:
    cfg.translation_history.append({
        "source": source[:200],
        "result": result[:200],
        "lang": lang,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    })
    if len(cfg.translation_history) > _MAX_HISTORY:
        cfg.translation_history = cfg.translation_history[-_MAX_HISTORY:]


def clear_history(cfg: Config) -> None:
    """Remove all translation history entries."""
    cfg.translation_history = []
