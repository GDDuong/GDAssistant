"""OrbService: run the Qt voice orb beside the Tk application.

Tk owns the main thread, so the orb gets its own daemon thread with a
QApplication and event loop. Commands (show_state/set_level/hide) are safe
to call from ANY thread (Tk mainloop, voice worker, wake listener): they
travel over queued Qt signals and are applied on the Qt thread only.

The service is created lazily on the first voice turn and only when the
`voice_orb_enabled` setting is on, so text-only sessions never pay for a
second UI toolkit (migration-safe: the legacy Tk app is untouched).
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from ui_qt.overlay import VoiceBubble

# How long the answer pill stays up after a turn finishes speaking.
RESULT_VISIBLE_MS = 6000


class _Bridge(QObject):
    """Queued-signal relay: emit from any thread, slots run on the Qt thread."""

    stateRequested = Signal(str, str)
    levelRequested = Signal(float)
    hideRequested = Signal()
    hideDelayedRequested = Signal()


class OrbService:
    def __init__(self, reduced_motion: bool = False) -> None:
        self._ready = threading.Event()
        self._bubble = None
        self._reduced_motion = reduced_motion
        # The bridge must have QT-thread affinity or its queued slots would
        # wait on an event loop that never runs (it was made in the Tk thread).
        self._bridge = None
        self._thread = threading.Thread(target=self._run, name="gd-orb-service", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def _run(self) -> None:
        app = QApplication.instance() or QApplication([])
        bridge = _Bridge()
        bridge.stateRequested.connect(self._apply_state)
        bridge.levelRequested.connect(self._apply_level)
        bridge.hideRequested.connect(self._apply_hide)
        bridge.hideDelayedRequested.connect(self._schedule_hide)
        self._bridge = bridge
        bubble = VoiceBubble(reduced_motion=self._reduced_motion)
        bubble.set_state("hidden")
        screen = app.primaryScreen().availableGeometry()
        bubble.move(screen.center().x() - bubble.width() // 2, screen.top() + 24)
        self._bubble = bubble
        self._ready.set()
        app.exec()

    # -- slots (Qt thread) --------------------------------------------------

    def _apply_state(self, state: str, text: str) -> None:
        if self._bubble is not None:
            self._bubble.set_state(state, text)

    def _apply_level(self, level: float) -> None:
        if self._bubble is not None:
            self._bubble.set_level(level)

    def _apply_hide(self) -> None:
        if self._bubble is not None:
            self._bubble.set_state("hidden")

    def _schedule_hide(self) -> None:
        # Runs on the Qt thread, where a singleShot timer has an event loop.
        QTimer.singleShot(RESULT_VISIBLE_MS, self._apply_hide)

    # -- thread-safe API -----------------------------------------------------

    def show_state(self, state: str, text: str = "") -> None:
        if self._bridge is not None:
            self._bridge.stateRequested.emit(state, text)

    def set_level(self, level: float) -> None:
        if self._bridge is not None:
            self._bridge.levelRequested.emit(level)

    def hide(self) -> None:
        if self._bridge is not None:
            self._bridge.hideRequested.emit()

    def hide_after_turn(self) -> None:
        # Let the answer pill linger through TTS, then fade out.
        if self._bridge is not None:
            self._bridge.hideDelayedRequested.emit()

    def on_expand(self, callback) -> None:
        if self._bubble is not None:
            self._bubble.expandRequested.connect(callback)
