"""Refresh-matched motion timing for the Qt surfaces.

Qt's built-in animation timer ticks at a fixed 16 ms regardless of the
monitor, so on 100+ Hz screens animated values land unevenly between
refreshes and motion reads as choppy. QTimeLine is the one Qt animation
class that exposes its tick interval, so animated surfaces drive their
motion through ``smooth_line`` / ``SmoothPropertyLine`` / ``RiseEntrance``
instead of QPropertyAnimation: same durations and easing curves, but one
tick per screen refresh (10 ms on a 100 Hz panel).
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QTimeLine
from PySide6.QtWidgets import QApplication

DEFAULT_TICK_MS = 16


def tick_interval_ms() -> int:
    """One tick per monitor refresh (10 ms at 100 Hz), clamped to 4..16 ms."""
    app = QApplication.instance()
    screen = app.primaryScreen() if app else None
    hz = float(screen.refreshRate()) if screen else 0.0
    interval = int(1000.0 / hz) if hz > 0 else DEFAULT_TICK_MS
    return max(4, min(DEFAULT_TICK_MS, interval))


def smooth_line(duration_ms: int = 0, parent=None) -> QTimeLine:
    line = QTimeLine(duration_ms, parent)
    line.setUpdateInterval(tick_interval_ms())
    return line


class SmoothPropertyLine(QTimeLine):
    """Eased timeline that writes its value into a QObject property.

    Drop-in for a one-shot QPropertyAnimation: ``run`` eases from start to
    end and calls ``setProperty(name, value)`` every tick; ``land`` snaps to
    the end value (reduced motion). Interrupting and re-running is safe —
    each run re-reads its own start value.
    """

    def __init__(self, target, prop_name: str, easing: QEasingCurve, parent=None) -> None:
        super().__init__(0, parent)
        self._target = target
        self.prop_name = prop_name
        self._start = 0.0
        self._span = 1.0
        self.setUpdateInterval(tick_interval_ms())
        self.setEasingCurve(easing)
        self.valueChanged.connect(self._apply)

    def run(self, start: float, end: float, duration: int) -> None:
        self.stop()
        self.setDuration(duration)
        self._start = float(start)
        self._span = float(end) - float(start)
        self.start()

    def land(self, end: float) -> None:
        self.stop()
        self._target.setProperty(self.prop_name, float(end))

    def _apply(self, fraction: float) -> None:
        self._target.setProperty(self.prop_name, self._start + self._span * fraction)


class RiseEntrance:
    """Fade-in + rise-into-place entrance shared by frameless surfaces.

    ``play`` animates from ``rise_px`` below wherever the window currently
    sits (popup()/the WM have already clamped it to the screen, so the
    target is exact) back to that spot, fading 0 -> 1 on the same clock.
    """

    def __init__(self, window, ms: int, rise_px: int) -> None:
        self._window = window
        self._rise = rise_px
        self._to = QPoint()
        self._from = QPoint()
        self._slide = smooth_line(ms, window)
        self._slide.setEasingCurve(QEasingCurve.OutCubic)
        self._slide.valueChanged.connect(self._apply_slide)
        self._fade = smooth_line(ms, window)
        self._fade.valueChanged.connect(window.setWindowOpacity)

    def play(self) -> None:
        self._to = self._window.pos()
        self._from = QPoint(self._to.x(), self._to.y() + self._rise)
        self._slide.start()
        self._fade.start()

    def _apply_slide(self, fraction: float) -> None:
        y = self._from.y() + (self._to.y() - self._from.y()) * fraction
        self._window.move(self._to.x(), int(round(y)))
