"""Text acquisition and replacement via clipboard simulation only.

Strategy
--------
1. Release any still-held hotkey modifiers (Ctrl/Shift/Alt) so the simulated
   Ctrl+C / Ctrl+V are not corrupted into Ctrl+Shift+C etc. This is critical
   for Electron apps (Obsidian, VS Code, Slack) where Ctrl+Shift+C is a
   different command.
2. Simulate ``Ctrl+C`` and wait for the clipboard *sequence number* to change
   (robust against slow Electron clipboard writes) instead of a fixed sleep.
3. If nothing is copied, simulate ``Ctrl+A`` then retry ``Ctrl+C``.
4. Simulate ``Ctrl+V`` to write translated text back.
5. Back up and restore the user's original clipboard *synchronously* around
   each operation, avoiding the race conditions of background restore threads.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger(__name__)

# Tunables (seconds)
_COPY_TIMEOUT = 0.6          # max wait for clipboard to change after Ctrl+C
_PASTE_SETTLE = 0.18         # wait for target app to consume the paste
_MODIFIER_WAIT = 0.5         # max wait for the user to release modifiers
_POLL_INTERVAL = 0.015

_MODIFIER_KEYS = ("ctrl", "shift", "alt")


@dataclass
class TextResult:
    text: str
    method: str = "clipboard"  # clipboard-only pipeline
    has_selection: bool = True
    via_select_all: bool = False


@dataclass
class ClipboardSnapshot:
    """Best-effort snapshot of clipboard formats/data."""

    entries: list[tuple[int, Any]]


# ---------------------------------------------------------------------------
# Keyboard helpers
# ---------------------------------------------------------------------------

def _send_keys(keys: str) -> None:
    """Send a key combination via the keyboard library."""
    try:
        import keyboard  # type: ignore[import]

        keyboard.send(keys)
    except Exception:
        pass


def _wait_modifiers_released(timeout: float = _MODIFIER_WAIT) -> bool:
    """Block until the user releases Ctrl/Shift/Alt, or *timeout* elapses.

    Returns True if all modifiers are released, False on timeout.
    """
    try:
        import keyboard  # type: ignore[import]
    except Exception:
        return True

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if not any(keyboard.is_pressed(k) for k in _MODIFIER_KEYS):
                return True
        except Exception:
            return True
        time.sleep(_POLL_INTERVAL)
    return False


def _release_modifiers() -> None:
    """Ensure no modifier key is held before we simulate Ctrl+C / Ctrl+V.

    First waits briefly for the user to physically release the hotkey
    (the common case). If still held, injects key-up events as a fallback so
    the subsequent Ctrl+C is not turned into Ctrl+Shift+C.
    """
    if _wait_modifiers_released():
        return

    try:
        import keyboard  # type: ignore[import]

        for key in ("ctrl", "shift", "alt", "left windows", "right windows"):
            try:
                keyboard.release(key)
            except Exception:
                continue
        time.sleep(0.03)
    except Exception:
        pass


def _select_all() -> None:
    """Select all text in the focused control."""
    _release_modifiers()
    _send_keys("ctrl+a")
    time.sleep(0.08)


# ---------------------------------------------------------------------------
# Clipboard sequence number (detects real clipboard changes)
# ---------------------------------------------------------------------------

_GetClipboardSequenceNumber = ctypes.windll.user32.GetClipboardSequenceNumber
_GetClipboardSequenceNumber.restype = ctypes.c_uint


def _clipboard_seq() -> int:
    try:
        return int(_GetClipboardSequenceNumber())
    except Exception:
        return 0


def _wait_clipboard_change(before: int, timeout: float) -> bool:
    """Wait until the clipboard sequence number differs from *before*."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _clipboard_seq() != before:
            return True
        time.sleep(_POLL_INTERVAL)
    return False


# ---------------------------------------------------------------------------
# Clipboard data helpers
# ---------------------------------------------------------------------------

def _clipboard_backup() -> Optional[ClipboardSnapshot]:
    """Best-effort backup of clipboard formats readable via pywin32."""
    try:
        import win32clipboard  # type: ignore[import]

        win32clipboard.OpenClipboard()
        try:
            entries: list[tuple[int, Any]] = []
            fmt = 0
            while True:
                fmt = win32clipboard.EnumClipboardFormats(fmt)
                if fmt == 0:
                    break
                try:
                    entries.append((fmt, win32clipboard.GetClipboardData(fmt)))
                except Exception:
                    # Some formats are not marshallable by pywin32.
                    continue
            return ClipboardSnapshot(entries=entries)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return None


def _clipboard_restore(snapshot: Optional[ClipboardSnapshot]) -> bool:
    """Restore clipboard from snapshot (synchronous)."""
    if snapshot is None:
        return False
    try:
        import win32clipboard  # type: ignore[import]

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            for fmt, data in snapshot.entries:
                try:
                    win32clipboard.SetClipboardData(fmt, data)
                except Exception:
                    continue
            return True
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return False


def _clipboard_read_text() -> Optional[str]:
    """Read Unicode text from clipboard without modifying clipboard state."""
    try:
        import win32clipboard  # type: ignore[import]

        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        pass
    return None


def _clipboard_set_text_data(text: str) -> bool:
    """Set clipboard text data."""
    try:
        import win32clipboard  # type: ignore[import]

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
            return True
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class TextHandler:
    """Facade that orchestrates text read/write via clipboard simulation."""

    def get_text(self) -> Optional[TextResult]:
        """Read text by simulating Ctrl+C; retry with Ctrl+A when empty."""
        result = self._clipboard_get_text()
        if result and result.text.strip():
            self._log_read_result(result)
            return result

        log.info("No text without selection, trying select-all (ctrl+a)")
        _select_all()

        result = self._clipboard_get_text()
        if result and result.text.strip():
            result.via_select_all = True
            result.has_selection = True
            self._log_read_result(result, via_select_all=True)
            return result

        log.warning("Text read failed — no text obtained from focused control")
        return None

    @staticmethod
    def _log_read_result(result: TextResult, via_select_all: bool = False) -> None:
        prefix = "select-all → " if via_select_all else ""
        log.info(
            "%sText read via clipboard:ctrl+c (has_selection=%s, len=%d)",
            prefix,
            result.has_selection,
            len(result.text),
        )

    def _clipboard_get_text(self) -> Optional[TextResult]:
        snapshot = _clipboard_backup()
        if snapshot is not None:
            log.info("Clipboard backup captured (%d formats)", len(snapshot.entries))

        # Critical: drop stuck hotkey modifiers so Ctrl+C is not Ctrl+Shift+C.
        _release_modifiers()

        before = _clipboard_seq()
        _send_keys("ctrl+c")
        changed = _wait_clipboard_change(before, _COPY_TIMEOUT)

        text = _clipboard_read_text() if changed else None
        if not changed:
            log.info("Ctrl+C produced no clipboard change (nothing selected?)")

        # Restore the user's clipboard synchronously now that we've read.
        _clipboard_restore(snapshot)

        if text and text.strip():
            return TextResult(text=text, has_selection=True)
        return None

    def set_text(self, new_text: str, original_result: TextResult) -> bool:
        """Write translated text back by clipboard paste only."""
        if self._clipboard_set_text(new_text):
            log.info("Text write-back via clipboard:ctrl+v")
            return True
        log.warning("Text write-back failed — clipboard path failed")
        return False

    def _clipboard_set_text(self, text: str) -> bool:
        snapshot = _clipboard_backup()
        if snapshot is not None:
            log.info("Clipboard backup captured (%d formats)", len(snapshot.entries))

        # Drop stuck modifiers before pasting (same reason as copy).
        _release_modifiers()

        if not _clipboard_set_text_data(text):
            return False

        time.sleep(0.05)
        _send_keys("ctrl+v")
        time.sleep(_PASTE_SETTLE)  # let the target app consume the paste

        # Restore the original clipboard synchronously — no racing threads.
        _clipboard_restore(snapshot)
        return True

    def get_caret_screen_pos(self, result: TextResult) -> tuple[int, int]:
        """Return fallback position near the current mouse cursor."""
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return (pt.x + 16, pt.y + 16)
