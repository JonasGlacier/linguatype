"""Main application: orchestrates all components.

Responsibilities
----------------
- Own the QSystemTrayIcon and its context menu
- Listen for hotkey signals and run the translation pipeline
- Manage the floating window lifecycle
- Provide the confirmation dialog for long texts
- Wire config reloads after settings are saved
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal, Slot, Qt
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from linguatype.config import Config, load_config, save_config, add_history
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


# ---------------------------------------------------------------------------
# Translation worker (runs in a thread-pool thread)
# ---------------------------------------------------------------------------

class _TranslationSignals(QObject):
    finished  = Signal(str, object)   # translated_text, TextResult
    error     = Signal(str, object)   # error_message, TextResult


class _TranslationWorker(QRunnable):
    def __init__(
        self,
        text: str,
        target_lang: str,
        translator,
        original_result: TextResult,
    ) -> None:
        super().__init__()
        self.signals = _TranslationSignals()
        self._text = text
        self._lang = target_lang
        self._translator = translator
        self._original = original_result

    def run(self) -> None:
        try:
            result = self._translator.translate(self._text, self._lang)
            self.signals.finished.emit(result, self._original)
        except TranslationError as exc:
            self.signals.error.emit(str(exc), self._original)
        except Exception as exc:
            self.signals.error.emit(f"Unexpected error: {exc}", self._original)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class App(QObject):
    """Top-level application object.  Owns the tray icon and orchestrates all
    sub-components.  Must be created after a QApplication exists.
    """

    def __init__(self) -> None:
        super().__init__()
        self._cfg = load_config()
        self._enabled = True

        self._text_handler = TextHandler()
        self._hotkey_mgr   = HotkeyManager()
        self._floating     = FloatingWindow()
        self._settings_win: Optional[SettingsWindow] = None

        self._thread_pool = QThreadPool.globalInstance()
        self._pending_result: Optional[TextResult] = None  # result waiting for write-back
        self._pending_lang: str = "en"

        self._build_tray()
        self._apply_config()

        # Connect hotkey signal → pipeline entry point
        self._hotkey_mgr.bridge.hotkey_triggered.connect(self._on_hotkey)

    # ------------------------------------------------------------------
    # Config application
    # ------------------------------------------------------------------

    def _apply_config(self) -> None:
        self._translator = self._build_translator()
        self._hotkey_mgr.update(self._cfg.hotkeys)
        self._refresh_tray_menu()

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

    @Slot(str)
    def _on_hotkey(self, target_lang: str) -> None:
        if not self._enabled:
            return

        # 1. Get text from focused control
        result = self._text_handler.get_text()
        if result is None or not result.text.strip():
            pos = self._cursor_pos()
            self._floating.show_translating(pos)
            self._floating.show_error("No text found in the focused control.")
            return

        # 2. Long-text confirmation
        text = result.text.strip()
        if len(text) > self._cfg.max_chars_confirm:
            answer = QMessageBox.question(
                None,
                "LinguaType — Long Text",
                f"The selected text is {len(text)} characters long.\n"
                "Translating long texts may take a moment and use more API quota.\n\n"
                "Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        # 3. Show floating "Translating…"
        pos = self._text_handler.get_caret_screen_pos(result)
        self._floating.show_translating(pos)

        log.info(
            "Translating %d chars → %s (read: %s)",
            len(text),
            target_lang,
            result.method,
        )

        # 4. Dispatch to thread pool
        self._pending_result = result
        self._pending_lang   = target_lang

        worker = _TranslationWorker(text, target_lang, self._translator, result)
        worker.signals.finished.connect(self._on_translation_done)
        worker.signals.error.connect(self._on_translation_error)
        self._thread_pool.start(worker)

    @Slot(str, object)
    def _on_translation_done(self, translated: str, original: TextResult) -> None:
        # Write translated text back
        ok = self._text_handler.set_text(translated, original)
        if ok:
            self._floating.show_success(translated)
            add_history(self._cfg, original.text, translated, self._pending_lang)
            save_config(self._cfg)
            self._refresh_tray_menu()
            if self._settings_win is not None and self._settings_win.isVisible():
                self._settings_win.refresh_history()
        else:
            self._floating.show_error("Could not write text back to the control.")

    @Slot(str, object)
    def _on_translation_error(self, error: str, _original: TextResult) -> None:
        log.error("Translation error: %s", error)
        self._floating.show_error(error)

    # ------------------------------------------------------------------
    # Tray
    # ------------------------------------------------------------------

    def _build_tray(self) -> None:
        icon_path = _ASSETS / "icon.ico"
        icon_gray_path = _ASSETS / "icon-gray.ico"

        self._icon_enabled = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
        self._icon_disabled = (
            QIcon(str(icon_gray_path)) if icon_gray_path.exists() else self._icon_enabled
        )

        self._tray = QSystemTrayIcon(self._icon_enabled)
        self._tray.setToolTip("LinguaType")
        self._tray.activated.connect(self._on_tray_activated)

        self._tray_menu = QMenu()
        self._tray.setContextMenu(self._tray_menu)
        self._refresh_tray_menu()
        self._update_tray_icon()
        self._tray.show()

    def _update_tray_icon(self) -> None:
        self._tray.setIcon(self._icon_enabled if self._enabled else self._icon_disabled)
        self._tray.setToolTip("LinguaType" if self._enabled else "LinguaType (disabled)")

    def _refresh_tray_menu(self) -> None:
        menu = self._tray_menu
        menu.clear()

        # Enable / disable toggle
        toggle_text = "Disable" if self._enabled else "Enable"
        toggle_action = QAction(toggle_text, self)
        toggle_action.triggered.connect(self._toggle_enabled)
        menu.addAction(toggle_action)

        menu.addSeparator()

        # Quick translate sub-menu per configured language
        if self._cfg.hotkeys:
            lang_menu = menu.addMenu("Translate to…")
            for entry in self._cfg.hotkeys:
                a = QAction(f"{entry.label}  ({entry.shortcut})", self)
                lang_code = entry.lang
                a.triggered.connect(lambda checked=False, lc=lang_code: self._on_hotkey(lc))
                lang_menu.addAction(a)
            menu.addSeparator()

        # History
        history_action = QAction("History…", self)
        history_action.triggered.connect(self._show_history)
        menu.addAction(history_action)

        menu.addSeparator()

        settings_action = QAction("Settings…", self)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._open_settings()

    def _toggle_enabled(self) -> None:
        self._enabled = not self._enabled
        self._hotkey_mgr.set_enabled(self._enabled)
        self._update_tray_icon()
        status = "enabled" if self._enabled else "disabled"
        self._tray.showMessage("LinguaType", f"Translation hotkeys {status}.",
                               QSystemTrayIcon.MessageIcon.Information, 2000)
        self._refresh_tray_menu()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _open_settings(self, history_tab: bool = False) -> None:
        if self._settings_win is not None and self._settings_win.isVisible():
            self._settings_win.update_config(self._cfg)
            if history_tab:
                self._settings_win.show_history_tab()
            else:
                self._settings_win.refresh_history()
            self._settings_win.raise_()
            self._settings_win.activateWindow()
            return
        self._settings_win = SettingsWindow(self._cfg)
        self._settings_win.settings_saved.connect(self._on_settings_saved)
        if history_tab:
            self._settings_win.show_history_tab()
        self._settings_win.show()

    @Slot(object)
    def _on_settings_saved(self, cfg: Config) -> None:
        self._cfg = cfg
        self._apply_config()
        self._tray.showMessage(
            "LinguaType", "Settings saved.", QSystemTrayIcon.MessageIcon.Information, 2000
        )

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def _show_history(self) -> None:
        self._open_settings(history_tab=True)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _cursor_pos(self) -> tuple[int, int]:
        import ctypes, ctypes.wintypes
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return (pt.x + 16, pt.y + 16)
