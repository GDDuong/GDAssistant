"""Frameless, transparent, always-on-top voice bubble for GD Assistant (Qt prototype).

The bubble never steals focus: it uses Qt.Tool (no taskbar entry) plus the
WS_EX_NOACTIVATE extended style set after the window is shown.
"""

from __future__ import annotations

import ctypes
import math

from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000

STATE_COLOR = {
    "hidden": QColor("#7aa2f7"),
    "listening": QColor("#9ece6a"),
    "thinking": QColor("#e0af68"),
    "speaking": QColor("#7aa2f7"),
    "result": QColor("#bb9af7"),
}

STATE_TEXT = {
    "hidden": "",
    "listening": "Listening…",
    "thinking": "Thinking…",
    "speaking": "Speaking…",
    "result": "",
}


def _with_alpha(color: QColor, alpha: int) -> QColor:
    return QColor(color.red(), color.green(), color.blue(), max(0, min(255, int(alpha))))


def _apply_no_activate_style(hwnd: int) -> None:
    # OR the bit in: overwriting GWL_EXSTYLE would wipe Qt's layered/composited
    # styles and turn the translucent background solid black.
    try:
        user32 = ctypes.windll.user32
        get_style, set_style = (
            (user32.GetWindowLongPtrW, user32.SetWindowLongPtrW)
            if hasattr(user32, "GetWindowLongPtrW")
            else (user32.GetWindowLongW, user32.SetWindowLongW)
        )
        get_style.restype = ctypes.c_ssize_t
        get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
        set_style.restype = ctypes.c_ssize_t
        set_style.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        set_style(hwnd, GWL_EXSTYLE, get_style(hwnd, GWL_EXSTYLE) | WS_EX_NOACTIVATE)
    except Exception:
        pass


class VoiceBubble(QWidget):
    def __init__(self, width: int = 300, height: int = 78, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(width, height)
        self._state = "hidden"
        self._result_text = ""
        self._phase = 0.0
        self._target_level = 0.0  # live mic level 0.0..1.0, set by the caller
        self._display_level = 0.0  # exponentially smoothed toward the target
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def show(self) -> None:  # noqa: D102
        super().show()
        _apply_no_activate_style(int(self.winId()))

    def set_state(self, state: str, result_text: str = "") -> None:
        if state not in STATE_COLOR:
            raise ValueError(f"unknown bubble state: {state}")
        self._state = state
        if state == "result":
            self._result_text = result_text
        if state == "hidden":
            super().hide()
        elif not self.isVisible():
            # A summoned bubble reveals itself; show() also applies the
            # no-focus-stealing style once the window handle exists.
            self.show()

    def set_level(self, level: float) -> None:
        # Raw target from the mic callback; _tick smooths it into self._display_level.
        self._target_level = max(0.0, min(1.0, level))

    def _tick(self) -> None:
        self._phase += 0.12
        self._display_level += (self._target_level - self._display_level) * 0.35
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = STATE_COLOR[self._state]

        body = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.setPen(QPen(_with_alpha(color, 120), 1.5))
        painter.setBrush(QColor(20, 20, 28, 210))
        painter.drawRoundedRect(body, self.height() / 2, self.height() / 2)

        cx, cy, base_r = 40, self.height() / 2, 12
        if self._state == "listening":
            self._paint_listening(painter, cx, cy, base_r, color)
        elif self._state == "thinking":
            self._paint_thinking(painter, cx, cy, base_r, color)
        elif self._state == "speaking":
            self._paint_speaking(painter, cx, cy, base_r, color)
        else:
            self._paint_dot(painter, cx, cy, base_r, color)

        text = STATE_TEXT[self._state] if self._state != "result" else self._result_text
        if text:
            painter.setPen(QPen(QColor("#c9d1d9")))
            painter.setFont(QFont("Segoe UI", 10))
            area = QRectF(cx + base_r + 18, 10, self.width() - (cx + base_r + 30), self.height() - 20)
            painter.drawText(area, Qt.AlignVCenter | Qt.TextWordWrap, text)

    def _paint_dot(self, painter, cx, cy, r, color):
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))

    def _paint_listening(self, painter, cx, cy, r, color):
        # Outer ring expands with the live mic level (falls back to a gentle pulse).
        amp = self._display_level if self._display_level > 0.01 else (0.3 + 0.2 * math.sin(self._phase * 2))
        ring_r = r + 6 + amp * 12
        painter.setPen(QPen(color, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(cx - ring_r, cy - ring_r, 2 * ring_r, 2 * ring_r))
        self._paint_dot(painter, cx, cy, r, color)

    def _paint_thinking(self, painter, cx, cy, r, color):
        # Three dots on a clockwise circular orbit (screen coords have y pointing down).
        orbit = r + 6
        painter.setPen(Qt.NoPen)
        for i in range(3):
            angle = self._phase + i * (math.tau / 3)
            size = r * 0.68
            painter.setBrush(_with_alpha(color, 140 + 100 * math.sin(self._phase + i)))
            painter.drawEllipse(
                QRectF(cx + orbit * math.cos(angle) - size,
                       cy + orbit * math.sin(angle) - size,
                       2 * size, 2 * size)
            )

    def _paint_speaking(self, painter, cx, cy, r, color):
        pulse = r + 8 + 4 * math.sin(self._phase * 3)
        gradient = QRadialGradient(cx, cy, pulse)
        gradient.setColorAt(0.0, _with_alpha(color, 160))
        gradient.setColorAt(1.0, _with_alpha(color, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(QRectF(cx - pulse, cy - pulse, 2 * pulse, 2 * pulse))
        self._paint_dot(painter, cx, cy, r, color)


def main() -> None:
    import sys

    app = QApplication(sys.argv)
    bubble = VoiceBubble()
    screen = app.primaryScreen().availableGeometry()
    bubble.move(screen.center().x() - bubble.width() // 2, screen.top() + 40)

    script = [
        (0, "listening", ""),
        (3500, "thinking", ""),
        (6000, "result", "Getting your weather now…"),
        (7500, "speaking", ""),
        (10000, "hidden", ""),
    ]
    for delay, state, text in script:
        QTimer.singleShot(delay, lambda s=state, t=text: bubble.set_state(s, t))
    QTimer.singleShot(10500, app.quit)

    bubble.show()
    bubble.set_state("listening")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
