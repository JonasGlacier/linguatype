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

from PySide6.QtCore import (
    Qt,
    QTimer,
    QPoint,
    QPropertyAnimation,
    QEasingCurve,
    QRect,
    QSize,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QPainter,
    QPainterPath,
    QPen,
    QFont,
    QFontMetrics,
    QScreen,
    QGuiApplication,
)
from PySide6.QtWidgets import QWidget, QApplication


class State(Enum):
    TRANSLATING = auto()
    SUCCESS = auto()
    ERROR = auto()


_COLORS = {
    "bg":           QColor(30, 30, 34, 235),
    "border":       QColor(70, 70, 80, 200),
    "text":         QColor(235, 235, 235),
    "success":      QColor(80, 200, 120),
    "error":        QColor(240, 80, 80),
    "spinner":      QColor(100, 160, 255),
    "subtle":       QColor(160, 160, 170),
}

_PADDING_H = 14
_PADDING_V = 9
_CORNER_R  = 10
_MIN_W     = 160
_MAX_W     = 340


class FloatingWindow(QWidget):
    """Borderless tooltip-style widget with translation status."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        flags = (
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        self._state = State.TRANSLATING
        self._message = "Translating…"
        self._dot_count = 0

        # Spinner animation timer
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(400)
        self._spin_timer.timeout.connect(self._tick_spinner)

        # Auto-hide timer
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_animated)

        # Mouse-movement hide (poll every 500 ms after SUCCESS/ERROR)
        self._mouse_timer = QTimer(self)
        self._mouse_timer.setInterval(500)
        self._mouse_timer.timeout.connect(self._check_mouse)
        self._last_mouse_pos: QPoint | None = None

        self._font = QFont("Segoe UI", 10)
        self._font_bold = QFont("Segoe UI", 10, QFont.Weight.Medium)

        self._opacity = 1.0
        self._anim: QPropertyAnimation | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_translating(self, pos: tuple[int, int]) -> None:
        """Show the 'Translating…' spinner at the given screen position."""
        self._state = State.TRANSLATING
        self._message = "Translating"
        self._dot_count = 0
        self._hide_timer.stop()
        self._mouse_timer.stop()
        self._spin_timer.start()
        self._move_to(pos)
        self._update_size()
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()

    def show_success(self, preview: str) -> None:
        """Switch to SUCCESS state with a translated text preview."""
        self._spin_timer.stop()
        self._state = State.SUCCESS
        short = preview[:60] + ("…" if len(preview) > 60 else "")
        self._message = short
        self._update_size()
        self.update()
        self._start_auto_hide(3500)

    def show_error(self, error: str) -> None:
        """Switch to ERROR state."""
        self._spin_timer.stop()
        self._state = State.ERROR
        self._message = error[:80]
        self._update_size()
        self.update()
        self._start_auto_hide(5000)

    def hide_animated(self) -> None:
        """Fade out and hide."""
        self._spin_timer.stop()
        self._hide_timer.stop()
        self._mouse_timer.stop()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(200)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(self.hide)
        anim.finished.connect(lambda: self.setWindowOpacity(1.0))
        anim.start()
        self._anim = anim

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _start_auto_hide(self, ms: int) -> None:
        self._hide_timer.start(ms)
        # also start mouse polling
        self._last_mouse_pos = QCursor.pos()
        self._mouse_timer.start()

    def _check_mouse(self) -> None:
        current = QCursor.pos()
        if self._last_mouse_pos is None:
            self._last_mouse_pos = current
            return
        delta = (current - self._last_mouse_pos)
        if abs(delta.x()) + abs(delta.y()) > 30:
            self.hide_animated()

    def _tick_spinner(self) -> None:
        self._dot_count = (self._dot_count + 1) % 4
        self.update()

    def _update_size(self) -> None:
        fm = QFontMetrics(self._font_bold)
        label = self._state_label()
        w = max(_MIN_W, min(_MAX_W,
                            fm.horizontalAdvance(label + "  " + self._message)
                            + _PADDING_H * 2 + 28))
        h = fm.height() + _PADDING_V * 2
        self.setFixedSize(w, h)

    def _state_label(self) -> str:
        if self._state == State.TRANSLATING:
            return "Translating" + "." * self._dot_count + " " * (3 - self._dot_count)
        if self._state == State.SUCCESS:
            return "✓ "
        return "✕ "

    def _move_to(self, pos: tuple[int, int]) -> None:
        x, y = pos
        screen = QGuiApplication.screenAt(QPoint(x, y))
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen:
            rect = screen.availableGeometry()
            x = min(x, rect.right() - self.width() - 8)
            y = min(y, rect.bottom() - self.height() - 8)
            x = max(x, rect.left() + 4)
            y = max(y, rect.top() + 4)
        self.move(x, y)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        # Background rounded rect
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, w - 1, h - 1, _CORNER_R, _CORNER_R)
        painter.fillPath(path, _COLORS["bg"])
        painter.setPen(QPen(_COLORS["border"], 1))
        painter.drawPath(path)

        painter.setFont(self._font_bold)
        y_baseline = h // 2 + QFontMetrics(self._font_bold).ascent() // 2 - 1

        x = _PADDING_H

        if self._state == State.TRANSLATING:
            painter.setPen(_COLORS["spinner"])
            dots = "." * self._dot_count + " " * (3 - self._dot_count)
            label = f"Translating{dots}"
            painter.drawText(x, y_baseline, label)

        elif self._state == State.SUCCESS:
            painter.setPen(_COLORS["success"])
            painter.drawText(x, y_baseline, "✓")
            x += QFontMetrics(self._font_bold).horizontalAdvance("✓") + 6
            painter.setPen(_COLORS["text"])
            painter.setFont(self._font)
            painter.drawText(x, y_baseline, self._message)

        else:  # ERROR
            painter.setPen(_COLORS["error"])
            painter.drawText(x, y_baseline, "✕")
            x += QFontMetrics(self._font_bold).horizontalAdvance("✕") + 6
            painter.setPen(_COLORS["text"])
            painter.setFont(self._font)
            painter.drawText(x, y_baseline, self._message)

        painter.end()
