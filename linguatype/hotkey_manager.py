"""Global hotkey registration and dispatch.

The ``keyboard`` library listens for key events from a background thread.
To keep Tk happy, all callbacks are marshalled back to the Tk main thread
via ``root.after()`` before any UI or application logic runs.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import tkinter as tk

log = logging.getLogger(__name__)


class HotkeyManager:
    """Registers and unregisters global hotkeys.

    Usage::

        manager = HotkeyManager(root, my_callback)
        manager.update([HotkeyEntry("en", "ctrl+shift+1", "→ English")])
    """

    def __init__(
        self,
        root: tk.Tk,
        callback: Callable[[str], None],
    ) -> None:
        self._root = root
        self._callback = callback
        self._registered: dict[str, str] = {}   # shortcut → lang
        self._enabled = True
        self._lock = threading.Lock()
        self._kb_available = self._check_keyboard()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def update(self, hotkeys: list) -> None:
        """Replace all registered hotkeys with the new list.

        *hotkeys* is a list of :class:`~linguatype.config.HotkeyEntry`.
        """
        self._unregister_all()
        if not self._kb_available:
            log.warning("keyboard library unavailable — hotkeys disabled")
            return
        for entry in hotkeys:
            self._register(entry.shortcut, entry.lang)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def stop(self) -> None:
        self._unregister_all()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _check_keyboard() -> bool:
        try:
            import keyboard  # type: ignore[import]   # noqa: F401
            return True
        except Exception as exc:
            log.error("Cannot import keyboard library: %s", exc)
            return False

    def _register(self, shortcut: str, lang: str) -> None:
        try:
            import keyboard  # type: ignore[import]

            def _cb(lang_code: str = lang) -> None:
                if self._enabled:
                    self._root.after(0, lambda lc=lang_code: self._callback(lc))

            with self._lock:
                # Do not suppress key events globally.
                # suppress=True can steal modifier combos (e.g. Ctrl+Wheel in Figma).
                keyboard.add_hotkey(shortcut, _cb, suppress=False)
                self._registered[shortcut] = lang
            log.debug("Registered hotkey %s → %s", shortcut, lang)
        except Exception as exc:
            log.error("Failed to register hotkey %s: %s", shortcut, exc)

    def _unregister_all(self) -> None:
        if not self._kb_available:
            return
        try:
            import keyboard  # type: ignore[import]
            with self._lock:
                for shortcut in list(self._registered):
                    try:
                        keyboard.remove_hotkey(shortcut)
                    except Exception:
                        pass
                self._registered.clear()
        except Exception:
            pass
