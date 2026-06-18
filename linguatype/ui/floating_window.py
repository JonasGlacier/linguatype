"""Floating status window that appears near the text cursor during translation.

States
------
TRANSLATING  Spinning dots animation + "Translating…"
SUCCESS      Green tick + translated preview (first 60 chars)
ERROR        Red cross + short error description

The window auto-hides after the SUCCESS/ERROR state:
- On mouse movement away from the window, or
- After a hard 4-second timeout.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
from enum import Enum, auto
from typing import TYPE_CHECKING

import customtkinter as ctk
import tkinter as tk
import tkinter.font as tkfont

if TYPE_CHECKING:
    pass


class State(Enum):
    TRANSLATING = auto()
    SUCCESS = auto()
    ERROR = auto()


_COLORS = {
    "bg": "#23252b",
    "border": "#414654",
    "accent": "#5f98ff",
    "title": "#f5f7ff",
    "text": "#d3d9e8",
    "muted": "#9aa2b8",
    "success": "#5dd39e",
    "error": "#ff6b6b",
}

_PADDING_H = 14
_PADDING_V = 10
_ICON_SIZE = 22
_ICON_GAP = 10
_MIN_W = 220
_MAX_W = 380
_MIN_H = 58
_MAX_DETAIL_LINES = 3
_ACCENT_W = 4


class FloatingWindow:
    """Borderless tooltip-style widget with translation status."""

    def __init__(self, root: tk.Tk) -> None:
        self._root = root
        self._state = State.TRANSLATING
        self._message = "Translating…"
        self._dot_count = 0

        self._win: ctk.CTkToplevel | None = None
        self._canvas: tk.Canvas | None = None

        self._spin_after_id: str | None = None
        self._hide_after_id: str | None = None
        self._mouse_after_id: str | None = None
        self._fade_after_id: str | None = None
        self._last_mouse_pos: tuple[int, int] | None = None
        self._size: tuple[int, int] = (_MIN_W, _MIN_H)

        self._font_title = tkfont.Font(family="Segoe UI Semibold", size=10)
        self._font_detail = tkfont.Font(family="Segoe UI", size=9)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_translating(self, pos: tuple[int, int]) -> None:
        """Show the 'Translating…' spinner at the given screen position."""
        self._ensure_window()
        self._state = State.TRANSLATING
        self._message = "Translating"
        self._dot_count = 0
        self._cancel_hide_timers()
        self._start_spinner()
        self._update_size()
        self._move_to(pos)
        assert self._win is not None
        self._win.attributes("-alpha", 1.0)
        self._win.deiconify()
        self._win.lift()
        self._redraw()

    def show_success(self, preview: str) -> None:
        """Switch to SUCCESS state with a translated text preview."""
        self._ensure_window()
        self._stop_spinner()
        self._state = State.SUCCESS
        short = preview.strip()[:88] + ("…" if len(preview.strip()) > 88 else "")
        self._message = short
        self._update_size()
        self._redraw()
        self._start_auto_hide(3500)

    def show_error(self, error: str) -> None:
        """Switch to ERROR state."""
        self._ensure_window()
        self._stop_spinner()
        self._state = State.ERROR
        self._message = error.strip()[:100]
        self._update_size()
        self._redraw()
        self._start_auto_hide(5000)

    def hide_animated(self) -> None:
        """Fade out and hide."""
        self._stop_spinner()
        self._cancel_hide_timers()
        self._fade_out()

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------

    def _ensure_window(self) -> None:
        if self._win is not None:
            return
        self._win = ctk.CTkToplevel(self._root)
        self._win.withdraw()
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-alpha", 1.0)

        self._canvas = tk.Canvas(
            self._win,
            highlightthickness=0,
            bd=0,
            bg=_COLORS["bg"],
        )
        self._canvas.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cancel_after(self, attr: str) -> None:
        after_id = getattr(self, attr)
        if after_id is not None:
            self._root.after_cancel(after_id)
            setattr(self, attr, None)

    def _cancel_hide_timers(self) -> None:
        self._cancel_after("_hide_after_id")
        self._cancel_after("_mouse_after_id")

    def _stop_spinner(self) -> None:
        self._cancel_after("_spin_after_id")

    def _start_spinner(self) -> None:
        self._stop_spinner()
        self._tick_spinner()

    def _tick_spinner(self) -> None:
        self._dot_count = (self._dot_count + 1) % 4
        self._redraw()
        self._spin_after_id = self._root.after(400, self._tick_spinner)

    def _start_auto_hide(self, ms: int) -> None:
        self._cancel_hide_timers()
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        self._last_mouse_pos = (pt.x, pt.y)
        self._hide_after_id = self._root.after(ms, self.hide_animated)
        self._mouse_after_id = self._root.after(500, self._check_mouse)

    def _check_mouse(self) -> None:
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        current = (pt.x, pt.y)
        if self._last_mouse_pos is None:
            self._last_mouse_pos = current
            self._mouse_after_id = self._root.after(500, self._check_mouse)
            return
        delta = abs(current[0] - self._last_mouse_pos[0]) + abs(current[1] - self._last_mouse_pos[1])
        if delta > 30:
            self.hide_animated()
            return
        self._mouse_after_id = self._root.after(500, self._check_mouse)

    def _compose_text(self) -> tuple[str, str]:
        if self._state == State.TRANSLATING:
            dots = "." * self._dot_count + " " * (3 - self._dot_count)
            return f"Translating{dots}", "Please wait while your text is processed"
        if self._state == State.SUCCESS:
            return "Translation complete", self._message or "Done"
        return "Translation failed", self._message or "Unknown error"

    def _content_left(self) -> int:
        return _PADDING_H + _ACCENT_W + 8 + _ICON_SIZE + _ICON_GAP

    def _wrap_text(self, text: str, max_width: int, font: tkfont.Font, max_lines: int = 2) -> list[str]:
        if not text:
            return [""]

        text = text.replace("\r\n", "\n")
        paragraphs = text.split("\n")
        lines: list[str] = []
        was_truncated = False

        for p_index, para in enumerate(paragraphs):
            if len(lines) >= max_lines:
                was_truncated = True
                break

            if para == "":
                lines.append("")
                continue

            current = ""
            i = 0
            while i < len(para):
                ch = para[i]
                candidate = current + ch
                if font.measure(candidate) <= max_width:
                    current = candidate
                    i += 1
                    continue

                if current:
                    lines.append(current.rstrip())
                    current = ""
                    if len(lines) >= max_lines:
                        was_truncated = True
                        break
                    continue

                lines.append(ch)
                i += 1
                if len(lines) >= max_lines:
                    was_truncated = i < len(para) or p_index < len(paragraphs) - 1
                    break

            if len(lines) >= max_lines:
                break

            if current or (para == "" and not lines):
                lines.append(current.rstrip())

        if not lines:
            lines = [""]

        if was_truncated:
            idx = min(max_lines, len(lines)) - 1
            last = lines[idx].rstrip()
            while last and font.measure(f"{last}…") > max_width:
                last = last[:-1]
            lines[idx] = f"{last}…" if last else "…"

        return lines[:max_lines]

    def _measure_text(self) -> tuple[int, int]:
        title, detail = self._compose_text()

        text_max_width = _MAX_W - self._content_left() - _PADDING_H
        detail_lines = self._wrap_text(detail, text_max_width, self._font_detail, max_lines=_MAX_DETAIL_LINES)

        title_w = self._font_title.measure(title)
        detail_w = max((self._font_detail.measure(line) for line in detail_lines), default=0)
        text_w = max(title_w, detail_w)

        title_h = self._font_title.metrics("linespace")
        detail_h = self._font_detail.metrics("linespace") * max(1, len(detail_lines))

        w = self._content_left() + text_w + _PADDING_H
        h = _PADDING_V * 2 + title_h + 4 + detail_h
        w = max(_MIN_W, min(_MAX_W, w))
        h = max(_MIN_H, h)
        return int(w), int(h)

    def _update_size(self) -> None:
        if self._win is None or self._canvas is None:
            return
        w, h = self._measure_text()
        self._size = (w, h)
        self._win.geometry(f"{w}x{h}")
        self._canvas.config(width=w, height=h)
        self._win.update_idletasks()

    def _move_to(self, pos: tuple[int, int]) -> None:
        if self._win is None:
            return
        x, y = pos
        # Clamp to primary monitor work area (best-effort on Windows)
        try:
            user32 = ctypes.windll.user32
            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
            w = self._win.winfo_width() or _MIN_W
            h = self._win.winfo_height() or 40
            x = min(x, sw - w - 8)
            y = min(y, sh - h - 8)
            x = max(x, 4)
            y = max(y, 4)
        except Exception:
            pass
        self._win.geometry(f"+{x}+{y}")

    def _fade_out(self, alpha: float = 1.0) -> None:
        if self._win is None:
            return
        alpha -= 0.1
        if alpha <= 0:
            self._win.withdraw()
            self._win.attributes("-alpha", 1.0)
            self._cancel_after("_fade_after_id")
            return
        self._win.attributes("-alpha", alpha)
        self._fade_after_id = self._root.after(20, lambda: self._fade_out(alpha))

    def _redraw(self) -> None:
        if self._canvas is None:
            return
        c = self._canvas
        c.delete("all")
        w, h = self._size

        c.config(width=w, height=h, bg=_COLORS["bg"])

        # Flat rectangular card to avoid corner seam artifacts.
        c.create_rectangle(0, 0, w - 1, h - 1, fill=_COLORS["bg"], outline=_COLORS["border"], width=1)

        # Accent strip
        accent = _COLORS["accent"]
        if self._state == State.SUCCESS:
            accent = _COLORS["success"]
        elif self._state == State.ERROR:
            accent = _COLORS["error"]
        c.create_rectangle(_PADDING_H, 9, _PADDING_H + _ACCENT_W, h - 10, fill=accent, outline=accent)

        title, detail = self._compose_text()
        text_max_width = w - self._content_left() - _PADDING_H
        detail_lines = self._wrap_text(detail, text_max_width, self._font_detail, max_lines=_MAX_DETAIL_LINES)

        icon_x = _PADDING_H + _ACCENT_W + 8 + (_ICON_SIZE // 2)
        icon_y = h // 2
        badge_fill = "#2c3140"
        badge_outline = "#3d465e"
        if self._state == State.SUCCESS:
            badge_fill = "#1f3a33"
            badge_outline = "#2c5c4f"
        elif self._state == State.ERROR:
            badge_fill = "#3f2628"
            badge_outline = "#6b3a3e"
        c.create_oval(
            icon_x - _ICON_SIZE // 2,
            icon_y - _ICON_SIZE // 2,
            icon_x + _ICON_SIZE // 2,
            icon_y + _ICON_SIZE // 2,
            fill=badge_fill,
            outline=badge_outline,
        )

        if self._state == State.TRANSLATING:
            dot_step = 6
            start = icon_x - dot_step
            for i in range(3):
                is_active = i == self._dot_count % 3
                color = _COLORS["accent"] if is_active else _COLORS["muted"]
                cx = start + i * dot_step
                c.create_oval(cx - 1.8, icon_y - 1.8, cx + 1.8, icon_y + 1.8, fill=color, outline=color)
        elif self._state == State.SUCCESS:
            c.create_text(icon_x, icon_y, text="✓", fill=_COLORS["success"], font=self._font_title)
        else:
            c.create_text(icon_x, icon_y, text="✕", fill=_COLORS["error"], font=self._font_title)

        text_x = self._content_left()
        title_y = _PADDING_V + 3
        c.create_text(text_x, title_y, text=title, anchor="nw", fill=_COLORS["title"], font=self._font_title)

        detail_y = title_y + self._font_title.metrics("linespace") + 3
        detail_text = "\n".join(detail_lines)
        c.create_text(
            text_x,
            detail_y,
            text=detail_text,
            anchor="nw",
            fill=_COLORS["text"],
            font=self._font_detail,
        )
