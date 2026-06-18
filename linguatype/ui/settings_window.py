"""Settings dialog — four-tab CTkToplevel.

Tab 1 – Engine    : choose engine, enter API keys
Tab 2 – Hotkeys   : manage (label, target lang, shortcut) pairs
Tab 3 – General   : max-chars threshold, autostart toggle
Tab 4 – History   : read-only list of recent translations
"""

from __future__ import annotations

import threading
import webbrowser
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import customtkinter as ctk
import requests
import tkinter as tk

from linguatype.config import Config, HotkeyEntry, save_config, set_autostart, clear_history

_THEME = "#79A92A"
_BG_BASE = "#F4F4EF"
_BG_PANEL = "#F0EFE7"
_TEXT_PRIMARY = "#2E2A1F"
_TEXT_MUTED = "#6E695C"
_BORDER_SOFT = "#DDD7C8"
_DANGER = "#B63A3A"
_THEME_HOVER = "#6C9626"
_NEUTRAL_BTN = "#B9B3A5"
_NEUTRAL_BTN_HOVER = "#A8A292"

_ASSETS = Path(__file__).resolve().parents[2] / "assets"
_ICON_PATH = _ASSETS / "icon.ico"


def _set_window_icon(win: tk.Toplevel) -> None:
    if not _ICON_PATH.exists():
        return

    def _apply() -> None:
        try:
            win.iconbitmap(str(_ICON_PATH))
        except Exception:
            pass

    # CTkToplevel re-applies its own titlebar/icon ~200ms after creation
    # (it withdraws and re-shows the window), which clears any icon set
    # immediately. Apply now and again after that to make it stick.
    _apply()
    try:
        win.after(300, _apply)
    except Exception:
        pass

_LANGUAGES: list[tuple[str, str]] = [
    ("en", "English"),
    ("en-GB", "English (UK)"),
    ("zh-CN", "Chinese (Simplified)"),
    ("zh-TW", "Chinese (Traditional)"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("de", "German"),
    ("fr", "French"),
    ("es", "Spanish"),
    ("pt", "Portuguese"),
    ("pt-BR", "Portuguese (Brazil)"),
    ("it", "Italian"),
    ("ru", "Russian"),
    ("ar", "Arabic"),
    ("nl", "Dutch"),
    ("pl", "Polish"),
    ("tr", "Turkish"),
    ("vi", "Vietnamese"),
    ("th", "Thai"),
]

_LANG_CODE_TO_NAME = {code: name for code, name in _LANGUAGES}
_LANG_NAMES = [name for _, name in _LANGUAGES]

_ENGINE_DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-latest",
    "gemini": "gemini-1.5-flash",
    "grok": "grok-2",
    "openrouter": "google/gemini-2.5-flash",
}

_ENGINES = [
    ("google", "Google Translate  (free, no key required)"),
    ("deepl", "DeepL"),
    ("openai", "OpenAI (ChatGPT)"),
    ("anthropic", "Anthropic (Claude)"),
    ("gemini", "Google Gemini"),
    ("grok", "xAI (Grok)"),
    ("openrouter", "OpenRouter"),
]


def _extract_error_message(resp: requests.Response) -> str:
    try:
        payload = resp.json()
    except Exception:
        return resp.text.strip() or f"HTTP {resp.status_code}"
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
        if isinstance(err, str):
            return err
        if isinstance(payload.get("message"), str):
            return payload["message"]
    return f"HTTP {resp.status_code}"


def _fetch_models(engine: str, api_key: str) -> list[str]:
    timeout = 15
    headers: dict[str, str] = {"Content-Type": "application/json"}

    if engine == "openai":
        headers["Authorization"] = f"Bearer {api_key}"
        resp = requests.get("https://api.openai.com/v1/models", headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            raise RuntimeError(_extract_error_message(resp))
        data = resp.json().get("data", [])
        return sorted(
            item.get("id", "") for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
        )

    if engine == "anthropic":
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        resp = requests.get("https://api.anthropic.com/v1/models", headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            raise RuntimeError(_extract_error_message(resp))
        return [
            item.get("id", "") for item in resp.json().get("data", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
        ]

    if engine == "gemini":
        resp = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": api_key}, timeout=timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(_extract_error_message(resp))
        models = []
        for item in resp.json().get("models", []):
            if not isinstance(item, dict):
                continue
            if "generateContent" not in item.get("supportedGenerationMethods", []):
                continue
            raw_name = item.get("name", "")
            if isinstance(raw_name, str) and raw_name.startswith("models/"):
                models.append(raw_name.split("/", 1)[1])
        return sorted(set(models))

    if engine == "grok":
        headers["Authorization"] = f"Bearer {api_key}"
        resp = requests.get("https://api.x.ai/v1/models", headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            raise RuntimeError(_extract_error_message(resp))
        return sorted(
            item.get("id", "") for item in resp.json().get("data", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
        )

    if engine == "openrouter":
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/LinguaType/LinguaType",
            "X-Title": "LinguaType",
        }
        resp = requests.get("https://openrouter.ai/api/v1/models", headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            raise RuntimeError(_extract_error_message(resp))
        return sorted(
            item.get("id", "") for item in resp.json().get("data", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
        )

    raise RuntimeError(f"Model fetching not supported for engine: {engine}")


def _verify_api_key(engine: str, api_key: str) -> tuple[bool, str]:
    if not api_key.strip():
        return False, "API key is empty."
    try:
        if engine == "openrouter":
            headers = {
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://github.com/LinguaType/LinguaType",
                "X-Title": "LinguaType",
            }
            resp = requests.get("https://openrouter.ai/api/v1/key", headers=headers, timeout=12)
            if resp.status_code >= 400:
                return False, _extract_error_message(resp)
            return True, "API key is valid."
        models = _fetch_models(engine, api_key)
        if not models:
            return False, "API key worked, but no models were returned."
        return True, "API key is valid."
    except requests.RequestException as exc:
        return False, f"Network error: {exc}"
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"Unexpected error: {exc}"


def _confirm(parent: tk.Misc, title: str, message: str) -> bool:
    result = {"value": False}

    dlg = ctk.CTkToplevel(parent)
    dlg.title(title)
    dlg.configure(fg_color=_BG_BASE)
    _set_window_icon(dlg)
    dlg.transient(parent)
    dlg.grab_set()
    dlg.resizable(False, False)

    ctk.CTkLabel(dlg, text=message, wraplength=360, justify="left", text_color=_TEXT_PRIMARY).pack(
        padx=20, pady=(20, 12), anchor="w",
    )
    btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
    btn_row.pack(padx=20, pady=(0, 20), fill="x")

    def _yes() -> None:
        result["value"] = True
        dlg.destroy()

    def _no() -> None:
        dlg.destroy()

    ctk.CTkButton(
        btn_row,
        text="Yes",
        width=80,
        fg_color=_THEME,
        hover_color=_THEME_HOVER,
        command=_yes,
    ).pack(
        side="right", padx=(8, 0),
    )
    ctk.CTkButton(
        btn_row,
        text="No",
        width=80,
        fg_color=_NEUTRAL_BTN,
        hover_color=_NEUTRAL_BTN_HOVER,
        text_color=_TEXT_PRIMARY,
        command=_no,
    ).pack(side="right")
    dlg.wait_window()
    return result["value"]


def _format_timestamp(ts: str) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts).strftime("%b %d, %Y  %H:%M")
    except ValueError:
        return ts


_MODIFIER_MAP: dict[str, str] = {
    "Control_L": "ctrl", "Control_R": "ctrl",
    "Shift_L": "shift", "Shift_R": "shift",
    "Alt_L": "alt", "Alt_R": "alt",
    "Win_L": "win", "Win_R": "win",
    "Super_L": "win", "Super_R": "win",
}


# Shift + 主键盘数字在 Tkinter 里会被记录成符号名称，需要还原为对应数字。
_SHIFT_SYMBOL_MAP: dict[str, str] = {
    "exclam": "1", "at": "2", "numbersign": "3", "dollar": "4",
    "percent": "5", "asciicircum": "6", "ampersand": "7",
    "asterisk": "8", "parenleft": "9", "parenright": "0",
}

# NumLock 关闭或 NumLock+Shift 时，小键盘方向键 keysym 会被记录成导航键名称，
# 需要还原为对应的数字键。
_KP_NAV_MAP: dict[str, str] = {
    "kp_home": "7", "kp_up": "8", "kp_prior": "9",
    "kp_left": "4", "kp_begin": "5", "kp_right": "6",
    "kp_end": "1", "kp_down": "2", "kp_next": "3",
    "kp_insert": "0", "kp_delete": ".",
    "kp_0": "0", "kp_1": "1", "kp_2": "2", "kp_3": "3",
    "kp_4": "4", "kp_5": "5", "kp_6": "6",
    "kp_7": "7", "kp_8": "8", "kp_9": "9",
}


def _keysym_to_shortcut(event: tk.Event, modifiers: set[str]) -> str | None:
    key = event.keysym.lower()
    if key in {
        "control_l", "control_r", "shift_l", "shift_r",
        "alt_l", "alt_r", "win_l", "win_r", "super_l", "super_r",
        "caps_lock", "num_lock", "scroll_lock",
    }:
        return None
    parts: list[str] = []
    for mod in ("ctrl", "shift", "alt", "win"):
        if mod in modifiers:
            parts.append(mod)
    if key in {"control", "shift", "alt", "win", "super"}:
        return None
    if key in _SHIFT_SYMBOL_MAP:
        key = _SHIFT_SYMBOL_MAP[key]
    elif key in _KP_NAV_MAP:
        key = _KP_NAV_MAP[key]
    if len(key) == 1:
        parts.append(key)
    elif key.startswith("kp_"):
        parts.append(key[3:])
    else:
        parts.append(key)
    return "+".join(parts)


class HotkeyEntryWidget(ctk.CTkEntry):
    """Entry that captures a single key combination."""

    def __init__(self, master: Any, **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self._shortcut = ""
        self._pressed_modifiers: set[str] = set()
        self.bind("<KeyPress>", self._on_keypress)
        self.bind("<KeyRelease>", self._on_keyrelease)
        self.bind("<FocusIn>", lambda _e: self.configure(placeholder_text="Press keys…"))
        self.bind("<FocusOut>", lambda _e: self._pressed_modifiers.clear())

    def _on_keypress(self, event: tk.Event) -> str:
        if event.keysym in _MODIFIER_MAP:
            self._pressed_modifiers.add(_MODIFIER_MAP[event.keysym])
            return "break"
        shortcut = _keysym_to_shortcut(event, self._pressed_modifiers)
        if shortcut:
            self._shortcut = shortcut
            self.delete(0, "end")
            self.insert(0, shortcut)
        return "break"

    def _on_keyrelease(self, event: tk.Event) -> None:
        if event.keysym in _MODIFIER_MAP:
            self._pressed_modifiers.discard(_MODIFIER_MAP[event.keysym])

    def get_shortcut(self) -> str:
        return self._shortcut or self.get().strip().lower()

    def set_shortcut(self, shortcut: str) -> None:
        self._shortcut = shortcut
        self.delete(0, "end")
        self.insert(0, shortcut)


class _EngineTab(ctk.CTkFrame):
    def __init__(self, master: Any, cfg: Config, root: tk.Tk) -> None:
        super().__init__(master, fg_color="transparent")
        self._cfg = cfg
        self._app_root = root
        self._verified_keys: dict[str, str] = {}
        self._engine_var = tk.StringVar(value=cfg.engine)
        self._engine_controls: dict[str, dict[str, Any]] = {}
        self._config_frames: dict[str, ctk.CTkFrame] = {}

        self.pack(fill="both", expand=True)
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        ctk.CTkLabel(scroll, text="Translation Engine", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=16, pady=(16, 8),
        )
        engine_box = ctk.CTkFrame(scroll, fg_color="transparent")
        engine_box.pack(fill="x", padx=16, pady=(0, 8))
        for value, label in _ENGINES:
            ctk.CTkRadioButton(
                engine_box, text=label, variable=self._engine_var, value=value,
                command=self._on_engine_changed,
                fg_color=_THEME,
                hover_color=_THEME_HOVER,
                border_color="#5F5A49",
                text_color=_TEXT_PRIMARY,
            ).pack(anchor="w", padx=12, pady=4)

        ctk.CTkLabel(scroll, text="Engine Settings", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=16, pady=(16, 8),
        )
        self._settings_host = ctk.CTkFrame(scroll, fg_color="transparent")
        self._settings_host.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self._build_config_panels()
        self._on_engine_changed()
        self._load()

    def _build_config_panels(self) -> None:
        google = ctk.CTkFrame(self._settings_host, fg_color="transparent")
        ctk.CTkLabel(
            google,
            text="Google Translate is free and does not require an API key.\n"
                 "Heavy usage may be rate-limited by Google.",
            wraplength=480, justify="left",
        ).pack(anchor="w", padx=8, pady=8)
        self._config_frames["google"] = google

        deepl = ctk.CTkFrame(self._settings_host, fg_color="transparent")
        self._deepl_key = ctk.CTkEntry(deepl, show="*", placeholder_text="DeepL API key")
        self._deepl_key.pack(fill="x", padx=8, pady=4)
        ctk.CTkButton(
            deepl,
            text="Get free key",
            width=100,
            fg_color=_THEME,
            hover_color=_THEME_HOVER,
            command=lambda: webbrowser.open("https://www.deepl.com/pro-api"),
        ).pack(
            anchor="w", padx=8, pady=4,
        )
        self._config_frames["deepl"] = deepl

        for engine in ("openai", "anthropic", "gemini", "grok", "openrouter"):
            self._config_frames[engine] = self._make_api_panel(engine)

    def _make_api_panel(self, engine: str) -> ctk.CTkFrame:
        panel = ctk.CTkFrame(self._settings_host, fg_color="transparent")
        key_entry = ctk.CTkEntry(panel, show="*", placeholder_text=f"{engine.title()} API key")
        key_entry.pack(fill="x", padx=8, pady=4)

        links = {
            "openai": "https://platform.openai.com/api-keys",
            "anthropic": "https://console.anthropic.com/",
            "gemini": "https://aistudio.google.com/",
            "grok": "https://console.x.ai/",
            "openrouter": "https://openrouter.ai/keys",
        }
        btn_row = ctk.CTkFrame(panel, fg_color="transparent")
        btn_row.pack(fill="x", padx=8, pady=4)
        verify_btn = ctk.CTkButton(btn_row, text="Verify", width=70, fg_color=_THEME, hover_color=_THEME_HOVER)
        verify_btn.pack(side="left")
        fetch_btn = ctk.CTkButton(btn_row, text="Fetch", width=70, fg_color=_THEME, hover_color=_THEME_HOVER)
        fetch_btn.pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            btn_row,
            text="Get key",
            width=70,
            fg_color=_THEME,
            hover_color=_THEME_HOVER,
            command=lambda u=links[engine]: webbrowser.open(u),
        ).pack(side="left", padx=(8, 0))
        status = ctk.CTkLabel(btn_row, text="")
        status.pack(side="left", padx=(12, 0))

        ctk.CTkLabel(panel, text="Model").pack(anchor="w", padx=8, pady=(4, 0))
        model_combo = ctk.CTkComboBox(panel, values=[_ENGINE_DEFAULT_MODELS[engine]])
        model_combo.pack(fill="x", padx=8, pady=4)

        setattr(self, f"_{engine}_key", key_entry)
        self._engine_controls[engine] = {
            "key": key_entry, "model": model_combo,
            "verify": verify_btn, "fetch": fetch_btn, "status": status,
        }
        key_entry.bind("<KeyRelease>", lambda _e, e=engine: self._on_key_changed(e))
        verify_btn.configure(command=lambda e=engine: self._on_verify_clicked(e))
        fetch_btn.configure(command=lambda e=engine: self._on_fetch_clicked(e))
        return panel

    def _on_engine_changed(self) -> None:
        for frame in self._config_frames.values():
            frame.pack_forget()
        engine = self._engine_var.get()
        self._config_frames[engine].pack(fill="both", expand=True)

    def _load(self) -> None:
        self._engine_var.set(self._cfg.engine)
        self._deepl_key.insert(0, self._cfg.api_keys.deepl)
        for engine in self._engine_controls:
            keys = self._cfg.api_keys
            key_val = getattr(keys, engine)
            model_val = getattr(keys, f"{engine}_model") or _ENGINE_DEFAULT_MODELS[engine]
            self._engine_controls[engine]["key"].insert(0, key_val)
            self._set_model_value(engine, model_val)
        self._on_engine_changed()

    def _set_model_value(self, engine: str, model_name: str) -> None:
        combo = self._engine_controls[engine]["model"]
        values = list(combo.cget("values"))
        if model_name not in values:
            values.insert(0, model_name)
            combo.configure(values=values)
        combo.set(model_name)

    def _on_key_changed(self, engine: str) -> None:
        self._verified_keys.pop(engine, None)
        self._set_status(engine, "", ok=False, visible=False)

    def _set_status(self, engine: str, text: str, ok: bool, visible: bool = True) -> None:
        status = self._engine_controls[engine]["status"]
        status.configure(text=text)
        if visible:
            status.configure(text_color=_THEME if ok else _DANGER)

    def _with_controls_enabled(self, engine: str, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._engine_controls[engine]["verify"].configure(state=state)
        self._engine_controls[engine]["fetch"].configure(state=state)

    def _run_async(self, engine: str, fn: Callable[[], tuple[bool, str] | list[str]]) -> None:
        def worker() -> None:
            try:
                result = fn()
            except Exception as exc:
                result = (False, str(exc))
            self._app_root.after(0, lambda: self._async_done(engine, result))

        self._with_controls_enabled(engine, False)
        threading.Thread(target=worker, daemon=True).start()

    def _async_done(self, engine: str, result: Any) -> None:
        self._with_controls_enabled(engine, True)
        if isinstance(result, tuple):
            ok, message = result
            if ok:
                key = self._engine_controls[engine]["key"].get().strip()
                self._verified_keys[engine] = key
                self._set_status(engine, "Verified", ok=True)
            else:
                self._verified_keys.pop(engine, None)
                self._set_status(engine, message, ok=False)
        elif isinstance(result, list):
            models = [m for m in result if m]
            if not models:
                self._set_status(engine, "No models returned", ok=False)
                return
            combo = self._engine_controls[engine]["model"]
            current = combo.get().strip()
            combo.configure(values=models)
            if current in models:
                combo.set(current)
            elif models:
                combo.set(models[0])
            self._set_status(engine, f"Fetched {len(models)} models", ok=True)

    def _on_verify_clicked(self, engine: str) -> None:
        key = self._engine_controls[engine]["key"].get().strip()
        if not key:
            self._set_status(engine, "API key is empty", ok=False)
            return
        self._run_async(engine, lambda: _verify_api_key(engine, key))

    def _on_fetch_clicked(self, engine: str) -> None:
        key = self._engine_controls[engine]["key"].get().strip()
        if not key:
            self._set_status(engine, "Enter API key before fetching models", ok=False)
            return

        def worker() -> list[str]:
            return _fetch_models(engine, key)

        engine_name = engine
        self._with_controls_enabled(engine_name, False)

        def run() -> None:
            try:
                models = worker()
            except Exception as exc:
                self._app_root.after(0, lambda: self._async_done(engine_name, (False, str(exc))))
                return
            self._app_root.after(0, lambda: self._async_done(engine_name, models))

        threading.Thread(target=run, daemon=True).start()

    def save_to(self, cfg: Config) -> None:
        cfg.engine = self._engine_var.get()
        cfg.api_keys.deepl = self._deepl_key.get().strip()
        for engine in self._engine_controls:
            setattr(cfg.api_keys, engine, self._engine_controls[engine]["key"].get().strip())
            model = self._engine_controls[engine]["model"].get().strip()
            setattr(cfg.api_keys, f"{engine}_model", model or _ENGINE_DEFAULT_MODELS[engine])


class _HotkeyRow:
    def __init__(self, parent: ctk.CTkFrame, entry: HotkeyEntry, on_remove: Callable[[], None]) -> None:
        self.frame = ctk.CTkFrame(parent, fg_color=_BG_BASE, border_width=1, border_color=_BORDER_SOFT)
        self.frame.pack(fill="x", pady=4)
        self.label_entry = ctk.CTkEntry(self.frame, width=100, placeholder_text="Label")
        self.label_entry.pack(side="left", padx=(8, 4))
        self.lang_combo = ctk.CTkComboBox(self.frame, values=_LANG_NAMES, width=180,
                                          command=self._sync_label)
        self.lang_combo.pack(side="left", padx=4)
        self.shortcut_entry = HotkeyEntryWidget(self.frame, width=140, placeholder_text="Shortcut")
        self.shortcut_entry.pack(side="left", padx=4)
        ctk.CTkButton(
            self.frame,
            text="−",
            width=30,
            fg_color=_DANGER,
            hover_color="#9A3131",
            command=on_remove,
        ).pack(side="right", padx=8)
        self._load_entry(entry)

    def _load_entry(self, entry: HotkeyEntry) -> None:
        self.label_entry.insert(0, entry.label)
        name = _LANG_CODE_TO_NAME.get(entry.lang, _LANG_NAMES[0])
        self.lang_combo.set(name)
        self.shortcut_entry.set_shortcut(entry.shortcut)

    def _sync_label(self, _choice: str | None = None) -> None:
        name = self.lang_combo.get()
        for code, lang_name in _LANGUAGES:
            if lang_name == name:
                iso = code.split("-", 1)[0]
                self.label_entry.delete(0, "end")
                self.label_entry.insert(0, f"→ {iso}")
                break

    def get_entry(self) -> HotkeyEntry | None:
        shortcut = self.shortcut_entry.get_shortcut()
        if not shortcut:
            return None
        name = self.lang_combo.get()
        lang = "en"
        for code, lang_name in _LANGUAGES:
            if lang_name == name:
                lang = code
                break
        return HotkeyEntry(lang=lang, shortcut=shortcut, label=self.label_entry.get().strip())


class _HotkeysTab(ctk.CTkFrame):
    def __init__(self, master: Any, cfg: Config) -> None:
        super().__init__(master, fg_color="transparent")
        self._rows: list[_HotkeyRow] = []
        ctk.CTkLabel(
            self,
            text="Each row maps a keyboard shortcut to a target language.\n"
                 "Click the Shortcut field and press your key combination.",
            wraplength=480, justify="left", text_color=_TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(16, 8))
        self._list = ctk.CTkScrollableFrame(self, fg_color=_BG_PANEL)
        self._list.pack(fill="both", expand=True, padx=16, pady=4)
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(4, 16))
        ctk.CTkButton(
            btn_row,
            text="+ Add",
            width=80,
            fg_color=_THEME,
            hover_color=_THEME_HOVER,
            command=self._add_row,
        ).pack(side="left")
        for entry in cfg.hotkeys:
            self._append_entry(entry)

    def _append_entry(self, entry: HotkeyEntry) -> None:
        holder: list[_HotkeyRow | None] = [None]

        def on_remove() -> None:
            if holder[0] is not None:
                self._remove_row(holder[0])

        row = _HotkeyRow(self._list, entry, on_remove)
        holder[0] = row
        self._rows.append(row)

    def _add_row(self) -> None:
        self._append_entry(HotkeyEntry("en", "ctrl+shift+3", "→ New"))

    def _remove_row(self, row: _HotkeyRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
            row.frame.destroy()

    def save_to(self, cfg: Config) -> None:
        entries: list[HotkeyEntry] = []
        for row in self._rows:
            entry = row.get_entry()
            if entry:
                entries.append(entry)
        cfg.hotkeys = entries


class _GeneralTab(ctk.CTkFrame):
    def __init__(self, master: Any, cfg: Config) -> None:
        super().__init__(master, fg_color="transparent")
        ctk.CTkLabel(self, text="Behaviour", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=16, pady=(16, 8),
        )
        chars_row = ctk.CTkFrame(self, fg_color="transparent")
        chars_row.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(chars_row, text="Ask confirmation when text exceeds:").pack(side="left")
        self._max_chars = ctk.CTkEntry(chars_row, width=80)
        self._max_chars.pack(side="left", padx=(8, 4))
        self._max_chars.insert(0, str(cfg.max_chars_confirm))
        ctk.CTkLabel(chars_row, text="chars").pack(side="left")

        ctk.CTkLabel(self, text="System", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=16, pady=(16, 8),
        )
        self._autostart = ctk.CTkCheckBox(
            self,
            text="Start LinguaType automatically when Windows starts",
            fg_color=_THEME,
            hover_color=_THEME_HOVER,
            border_color="#5F5A49",
            text_color=_TEXT_PRIMARY,
        )
        if cfg.autostart:
            self._autostart.select()
        self._autostart.pack(anchor="w", padx=16, pady=4)

    def save_to(self, cfg: Config) -> None:
        try:
            cfg.max_chars_confirm = int(self._max_chars.get().strip())
        except ValueError:
            cfg.max_chars_confirm = 500
        cfg.autostart = bool(self._autostart.get())


class _HistoryTab(ctk.CTkFrame):
    def __init__(self, master: Any, cfg: Config, root: tk.Tk) -> None:
        super().__init__(master, fg_color="transparent")
        self._cfg = cfg
        self._app_root = root
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(header, text="Recent translations, newest first (read-only).",
                     text_color=_TEXT_MUTED).pack(side="left")
        self._clear_btn = ctk.CTkButton(header, text="Clear All", width=80, fg_color=_DANGER, hover_color="#9A3131",
                                        command=self._clear_all)
        self._clear_btn.pack(side="right")
        self._scroll = ctk.CTkScrollableFrame(self, fg_color=_BG_PANEL)
        self._scroll.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.reload(cfg)

    def _clear_all(self) -> None:
        if not self._cfg.translation_history:
            return
        if not _confirm(self._app_root, "LinguaType — Clear History",
                        "Delete all translation history?\nThis action cannot be undone."):
            return
        clear_history(self._cfg)
        save_config(self._cfg)
        self.reload(self._cfg)

    def reload(self, cfg: Config) -> None:
        self._cfg = cfg
        for child in self._scroll.winfo_children():
            child.destroy()
        self._clear_btn.configure(state="normal" if cfg.translation_history else "disabled")
        if not cfg.translation_history:
            ctk.CTkLabel(self._scroll, text="No translations yet.", text_color=_TEXT_MUTED).pack(pady=20)
            return
        for item in reversed(cfg.translation_history[-50:]):
            self._add_card(item)

    def _add_card(self, item: dict[str, str]) -> None:
        card = ctk.CTkFrame(self._scroll, fg_color=_BG_BASE, border_width=1, border_color=_BORDER_SOFT)
        card.pack(fill="x", pady=6, padx=4)
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(8, 4))
        lang_code = item.get("lang", "")
        lang_name = _LANG_CODE_TO_NAME.get(lang_code, lang_code.upper())
        ctk.CTkLabel(header, text=f"{lang_name} ({lang_code.upper()})",
                     fg_color=_THEME, corner_radius=4, padx=6).pack(side="left")
        ts = _format_timestamp(item.get("timestamp", ""))
        if ts:
            ctk.CTkLabel(header, text=ts, text_color=_TEXT_MUTED, font=ctk.CTkFont(size=11)).pack(side="right")
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=12, pady=(0, 8))
        src_frame = ctk.CTkFrame(body, fg_color="transparent")
        src_frame.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(src_frame, text="SOURCE", font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=_TEXT_MUTED).pack(anchor="w")
        ctk.CTkLabel(src_frame, text=item.get("source", ""), wraplength=200, justify="left").pack(anchor="w")
        ctk.CTkLabel(body, text="→", font=ctk.CTkFont(size=18), text_color=_TEXT_MUTED).pack(side="left", padx=8)
        res_frame = ctk.CTkFrame(body, fg_color="transparent")
        res_frame.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(res_frame, text="TRANSLATION", font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=_THEME).pack(anchor="w")
        ctk.CTkLabel(res_frame, text=item.get("result", ""), wraplength=200, justify="left").pack(anchor="w")


class SettingsWindow:
    """Four-tab settings dialog. Calls on_save after the user clicks OK."""

    def __init__(
        self,
        root: tk.Tk,
        cfg: Config,
        on_save: Callable[[Config], None],
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self._root = root
        self._cfg = cfg
        self._on_save = on_save
        self._on_close = on_close

        self._win = ctk.CTkToplevel(root)
        self._win.title("LinguaType - Settings")
        self._win.geometry("580x520")
        self._win.minsize(520, 460)
        self._win.configure(fg_color=_BG_BASE)
        _set_window_icon(self._win)

        self._tabs = ctk.CTkTabview(
            self._win,
            fg_color=_BG_BASE,
            segmented_button_selected_color=_THEME,
            segmented_button_selected_hover_color=_THEME_HOVER,
            segmented_button_unselected_color="#D9D3C3",
            segmented_button_unselected_hover_color="#CAC3B2",
            text_color=_TEXT_PRIMARY,
        )
        self._tabs.pack(fill="both", expand=True, padx=12, pady=(12, 8))
        self._tabs.add("Engine")
        self._tabs.add("Hotkeys")
        self._tabs.add("General")
        self._tabs.add("History")
        for tab_name in ("Engine", "Hotkeys", "General", "History"):
            self._tabs.tab(tab_name).configure(fg_color=_BG_PANEL)

        self._engine_tab = _EngineTab(self._tabs.tab("Engine"), cfg, root)
        self._engine_tab.pack(fill="both", expand=True)
        self._hotkeys_tab = _HotkeysTab(self._tabs.tab("Hotkeys"), cfg)
        self._hotkeys_tab.pack(fill="both", expand=True)
        self._general_tab = _GeneralTab(self._tabs.tab("General"), cfg)
        self._general_tab.pack(fill="both", expand=True)
        self._history_tab = _HistoryTab(self._tabs.tab("History"), cfg, root)
        self._history_tab.pack(fill="both", expand=True)

        btn_row = ctk.CTkFrame(self._win, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkButton(
            btn_row,
            text="Cancel",
            width=100,
            fg_color=_NEUTRAL_BTN,
            hover_color=_NEUTRAL_BTN_HOVER,
            text_color=_TEXT_PRIMARY,
            command=self._close,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_row, text="OK", width=100, fg_color=_THEME, hover_color=_THEME_HOVER, command=self._save).pack(
            side="right",
        )

        self._win.protocol("WM_DELETE_WINDOW", self._close)

    @property
    def win(self) -> ctk.CTkToplevel:
        return self._win

    def is_visible(self) -> bool:
        try:
            return self._win.winfo_exists() and self._win.state() != "withdrawn"
        except tk.TclError:
            return False

    def show(self) -> None:
        self._win.deiconify()
        self._win.lift()
        self._win.focus_force()

    def show_history_tab(self) -> None:
        self._history_tab.reload(self._cfg)
        self._tabs.set("History")

    def refresh_history(self) -> None:
        self._history_tab.reload(self._cfg)

    def update_config(self, cfg: Config) -> None:
        self._cfg = cfg
        self.refresh_history()

    def _save(self) -> None:
        self._engine_tab.save_to(self._cfg)
        self._hotkeys_tab.save_to(self._cfg)
        self._general_tab.save_to(self._cfg)
        save_config(self._cfg)
        set_autostart(self._cfg.autostart)
        self._on_save(self._cfg)
        self._close()

    def _close(self) -> None:
        self._win.destroy()
        if self._on_close is not None:
            self._on_close()
