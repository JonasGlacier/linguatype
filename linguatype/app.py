"""Main application: orchestrates all components.

Responsibilities
----------------
- Own the system tray icon and its context menu
- Listen for hotkey callbacks and run the translation pipeline
- Manage the floating window lifecycle
- Provide the confirmation dialog for long texts
- Wire config reloads after settings are saved
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import customtkinter as ctk
import pystray
import tkinter as tk
from PIL import Image, ImageDraw

from linguatype.config import Config, load_config
from linguatype.hotkey_manager import HotkeyManager
from linguatype.text_handler import TextHandler, TextResult
from linguatype.translators.base import TranslationError
from linguatype.translators import (
    GoogleTranslator,
    DeepLTranslator,
    OpenAITranslator,
    AnthropicTranslator,
    GeminiTranslator,
    GrokTranslator,
    OpenRouterTranslator,
)
from linguatype.ui.floating_window import FloatingWindow
from linguatype.ui.settings_window import SettingsWindow

log = logging.getLogger(__name__)

_ASSETS = Path(__file__).parent.parent / "assets"


def _confirm_long_text(root: tk.Tk, char_count: int) -> bool:
    result = {"value": False}

    dlg = ctk.CTkToplevel(root)
    dlg.title("LinguaType — Long Text")
    dlg.transient(root)
    dlg.grab_set()
    dlg.resizable(False, False)

    msg = (
        f"The selected text is {char_count} characters long.\n"
        "Translating long texts may take a moment and use more API quota.\n\n"
        "Continue?"
    )
    ctk.CTkLabel(dlg, text=msg, wraplength=360, justify="left").pack(
        padx=20, pady=(20, 12), anchor="w",
    )
    btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
    btn_row.pack(padx=20, pady=(0, 20), fill="x")

    def _yes() -> None:
        result["value"] = True
        dlg.destroy()

    def _no() -> None:
        dlg.destroy()

    ctk.CTkButton(btn_row, text="Yes", width=80, fg_color="#79A92A", hover_color="#6C9626", command=_yes).pack(side="right", padx=(8, 0))
    ctk.CTkButton(btn_row, text="No", width=80, fg_color="#ADA576", hover_color="#A8A292", command=_no).pack(side="right")

    dlg.update_idletasks()
    w, h = dlg.winfo_width(), dlg.winfo_height()
    x = (dlg.winfo_screenwidth() - w) // 2
    y = (dlg.winfo_screenheight() - h) // 2
    dlg.geometry(f"+{x}+{y}")

    dlg.wait_window()
    return result["value"]


class App:
    """Top-level application object. Owns the tray icon and orchestrates all sub-components."""

    def __init__(self, root: tk.Tk) -> None:
        self._root = root
        self._cfg = load_config()
        self._enabled = True

        self._text_handler = TextHandler()
        self._hotkey_mgr = HotkeyManager(root, self._on_hotkey)
        self._floating = FloatingWindow(root)
        self._settings_win: Optional[SettingsWindow] = None

        self._executor = ThreadPoolExecutor(max_workers=2)
        self._pending_result: Optional[TextResult] = None

        self._tray_icon: Optional[pystray.Icon] = None
        self._build_tray()
        self._apply_config()

    # ------------------------------------------------------------------
    # Config application
    # ------------------------------------------------------------------

    def _apply_config(self) -> None:
        self._translator = self._build_translator()
        self._hotkey_mgr.update(self._cfg.hotkeys)
        self._update_tray_menu()

    def _build_translator(self):
        engine = self._cfg.engine
        if engine == "deepl":
            return DeepLTranslator(self._cfg.api_keys.deepl)
        if engine == "openai":
            return OpenAITranslator(
                self._cfg.api_keys.openai,
                model=self._cfg.api_keys.openai_model or "gpt-4o-mini",
            )
        if engine == "anthropic":
            return AnthropicTranslator(
                self._cfg.api_keys.anthropic,
                model=self._cfg.api_keys.anthropic_model or "claude-3-5-sonnet-latest",
            )
        if engine == "gemini":
            return GeminiTranslator(
                self._cfg.api_keys.gemini,
                model=self._cfg.api_keys.gemini_model or "gemini-1.5-flash",
            )
        if engine == "grok":
            return GrokTranslator(
                self._cfg.api_keys.grok,
                model=self._cfg.api_keys.grok_model or "grok-2",
            )
        if engine == "openrouter":
            return OpenRouterTranslator(
                self._cfg.api_keys.openrouter,
                model=self._cfg.api_keys.openrouter_model or "google/gemini-2.5-flash",
            )
        return GoogleTranslator()

    # ------------------------------------------------------------------
    # Translation pipeline
    # ------------------------------------------------------------------

    def _on_hotkey(self, target_lang: str) -> None:
        if not self._enabled:
            return

        result = self._text_handler.get_text()
        if result is None or not result.text.strip():
            pos = self._cursor_pos()
            self._floating.show_translating(pos)
            self._floating.show_error("No text found in the focused control.")
            return

        text = result.text.strip()
        if len(text) > self._cfg.max_chars_confirm:
            if not _confirm_long_text(self._root, len(text)):
                return

        pos = self._text_handler.get_caret_screen_pos(result)
        self._floating.show_translating(pos)

        log.info("Translating %d chars → %s (read: %s)", len(text), target_lang, result.method)

        self._pending_result = result

        translator = self._translator
        self._executor.submit(self._run_translation, text, target_lang, translator, result)

    def _run_translation(
        self,
        text: str,
        target_lang: str,
        translator,
        original: TextResult,
    ) -> None:
        try:
            translated = translator.translate(text, target_lang)
            self._root.after(0, lambda: self._on_translation_done(translated, original))
        except TranslationError as exc:
            self._root.after(0, lambda: self._on_translation_error(str(exc), original))
        except Exception as exc:
            self._root.after(0, lambda: self._on_translation_error(f"Unexpected error: {exc}", original))

    def _on_translation_done(self, translated: str, original: TextResult) -> None:
        ok = self._text_handler.set_text(translated, original)
        if ok:
            self._floating.show_success(translated)
        else:
            self._floating.show_error("Could not write text back to the control.")

    def _on_translation_error(self, error: str, _original: TextResult) -> None:
        log.error("Translation error: %s", error)
        self._floating.show_error(error)

    # ------------------------------------------------------------------
    # Tray
    # ------------------------------------------------------------------

    def _load_tray_image(self, path: Path) -> Image.Image:
        if path.exists():
            return Image.open(path)
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((8, 8, 56, 56), fill=(121, 169, 42, 255))
        return img

    def _build_tray(self) -> None:
        icon_path = _ASSETS / "icon.ico"
        icon_gray_path = _ASSETS / "icon-gray.ico"
        self._icon_enabled = self._load_tray_image(icon_path)
        self._icon_disabled = (
            self._load_tray_image(icon_gray_path) if icon_gray_path.exists() else self._icon_enabled
        )
        self._update_tray_menu()
        self._tray_icon = pystray.Icon(
            "LinguaType",
            self._icon_enabled if self._enabled else self._icon_disabled,
            "LinguaType",
            menu=self._tray_menu,
        )
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _post(self, fn) -> None:
        self._root.after(0, fn)

    def _update_tray_menu(self) -> None:
        items: list[pystray.MenuItem] = []

        toggle_text = "Disable" if self._enabled else "Enable"
        items.append(pystray.MenuItem(
            toggle_text, lambda _i, _it: self._post(self._toggle_enabled),
        ))

        items.append(pystray.Menu.SEPARATOR)

        if self._cfg.hotkeys:
            def _mk_translate_action(lang_code: str):
                def _action(_icon, _item) -> None:
                    self._post(lambda: self._on_hotkey(lang_code))
                return _action

            lang_items = [
                pystray.MenuItem(
                    f"{entry.label}  ({entry.shortcut})",
                    _mk_translate_action(entry.lang),
                )
                for entry in self._cfg.hotkeys
            ]
            items.append(pystray.MenuItem("Translate to…", pystray.Menu(*lang_items)))
            items.append(pystray.Menu.SEPARATOR)

        items.append(pystray.MenuItem(
            "Settings…",
            lambda _i, _it: self._post(self._open_settings),
            default=True,
        ))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Quit", lambda _i, _it: self._post(self._quit)))

        self._tray_menu = pystray.Menu(*items)
        if self._tray_icon is not None:
            self._tray_icon.menu = self._tray_menu
            self._tray_icon.icon = self._icon_enabled if self._enabled else self._icon_disabled
            tooltip = "LinguaType" if self._enabled else "LinguaType (disabled)"
            self._tray_icon.title = tooltip

    def _toggle_enabled(self) -> None:
        self._enabled = not self._enabled
        self._hotkey_mgr.set_enabled(self._enabled)
        self._update_tray_menu()
        log.info("Translation hotkeys %s", "enabled" if self._enabled else "disabled")

    def _quit(self) -> None:
        self._hotkey_mgr.stop()
        self._executor.shutdown(wait=False)
        if self._tray_icon is not None:
            self._tray_icon.stop()
        self._root.quit()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        self._hotkey_mgr.set_enabled(False)
        if self._settings_win is not None and self._settings_win.is_visible():
            self._settings_win.update_config(self._cfg)
            self._settings_win.show()
            return
        self._settings_win = SettingsWindow(self._root, self._cfg, self._on_settings_saved, on_close=lambda: self._hotkey_mgr.set_enabled(True))
        self._settings_win.show()

    def _on_settings_saved(self, cfg: Config) -> None:
        self._cfg = cfg
        self._apply_config()
        log.info("Settings saved.")

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _cursor_pos(self) -> tuple[int, int]:
        import ctypes
        import ctypes.wintypes
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return (pt.x + 16, pt.y + 16)
