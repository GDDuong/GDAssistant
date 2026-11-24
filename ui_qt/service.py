"""Qt UI service: run the Qt layer (voice orb, chat window, menu popups,
settings window) beside the Tk application.

Tk owns the main thread, so Qt gets its own daemon thread with a
QApplication and event loop. Qt allows a single QApplication per process, so
every Qt window — the orb, the chat window, the File/Mode popup menus, the
settings window — lives in this one thread. Commands (show_state/set_level/
show_menu/open_settings/open_chat_window/chat_op/hide) are safe to call from
ANY thread (Tk mainloop, voice worker, wake listener): they travel over
queued Qt signals and are applied on the Qt thread only.

The service is created lazily on first use, so text-only sessions never pay
for a second UI toolkit (migration-safe: the legacy Tk app is untouched and
keeps working if Qt is unavailable).

Callbacks registered via on_expand/on_menu_trigger/on_settings_saved run on
the Qt thread; the Tk side must hop back with root.after before touching Tk
widgets (see _orb_raise_main_window in main.py).
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from ui_qt.chat_window import ChatWindow
from ui_qt.menu import PopupMenu
from ui_qt.motion import tick_interval_ms
from ui_qt.overlay import VoiceBubble
from ui_qt.settings_window import SettingsWindow
from ui_qt.wizard import WizardDialog

# How long the answer pill stays up after a turn finishes speaking.
RESULT_VISIBLE_MS = 6000


class _Bridge(QObject):
    """Queued-signal relay: emit from any thread, slots run on the Qt thread."""

    stateRequested = Signal(str, str)
    levelRequested = Signal(float)
    hideRequested = Signal()
    hideDelayedRequested = Signal()
    menuRequested = Signal(list, dict)
    settingsRequested = Signal(dict, dict, str)
    chatRequested = Signal(str, object)
    noticeRequested = Signal(str, str, str)
    chatRaiseRequested = Signal()
    wizardRequested = Signal(dict, object)


class QtUiService:
    def __init__(self, reduced_motion: bool = False) -> None:
        self._ready = threading.Event()
        self._bubble = None
        self._reduced_motion = reduced_motion
        # Resolved on the Qt thread (QScreen needs the QApplication); read by
        # the Tk side for the --debug line after _ready.wait().
        self.motion_tick_ms = 0
        # The bridge must have QT-thread affinity or its queued slots would
        # wait on an event loop that never runs (it was made in the Tk thread).
        self._bridge = None
        self._menu = None  # keeps the posted PopupMenu alive until it hides
        self._settings_window = None
        self._chat_window = None
        self._menu_trigger_cb = None
        self._menu_closed_cb = None
        self._settings_saved_cb = None
        self._chat_event_cb = None
        self._thread = threading.Thread(target=self._run, name="gd-qt-service", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def _run(self) -> None:
        app = QApplication.instance() or QApplication([])
        # The Tk app owns the process lifetime: closing the settings window
        # (or any other Qt window — the orb is a Qt.Tool and never counts)
        # must not end this event loop, or every later menu/settings call
        # silently lands in a queue nobody drains (the "after closing
        # Settings the File/Mode tabs do nothing" bug).
        app.setQuitOnLastWindowClosed(False)
        self.motion_tick_ms = tick_interval_ms()
        bridge = _Bridge()
        bridge.stateRequested.connect(self._apply_state)
        bridge.levelRequested.connect(self._apply_level)
        bridge.hideRequested.connect(self._apply_hide)
        bridge.hideDelayedRequested.connect(self._schedule_hide)
        bridge.menuRequested.connect(self._apply_menu)
        bridge.settingsRequested.connect(self._apply_settings)
        bridge.chatRequested.connect(self._apply_chat)
        bridge.noticeRequested.connect(self._apply_notice)
        bridge.chatRaiseRequested.connect(self._apply_chat_raise)
        bridge.wizardRequested.connect(self._apply_wizard)
        self._bridge = bridge
        bubble = VoiceBubble(reduced_motion=self._reduced_motion)
        bubble.set_state("hidden")
        screen = app.primaryScreen().availableGeometry()
        bubble.move(screen.center().x() - bubble.width() // 2, screen.top() + 24)
        self._bubble = bubble
        self._ready.set()
        app.exec()

    # -- orb slots (Qt thread) ----------------------------------------------

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

    # -- menu + settings slots (Qt thread) ------------------------------------

    def _apply_menu(self, items: list, palette: dict) -> None:
        # Close-then-open, and clear self._menu first: the superseded menu's
        # aboutToHide then sees itself as stale (no closed-callback, no
        # touching the new menu). The old handler read self._menu inside
        # aboutToHide, so a fast File->Mode reopen deleted the NEW menu —
        # the "sometimes the File/Mode tab does nothing" bug.
        previous = self._menu
        self._menu = None
        if previous is not None:
            previous.close()
            previous.deleteLater()
        menu = PopupMenu(palette, animate=not self._reduced_motion)
        for index, item in enumerate(items):
            if item.get("separator"):
                menu.addSeparator()
                continue
            action = menu.addAction(str(item.get("label", "")))
            action.setEnabled(bool(item.get("enabled", True)))
            action.triggered.connect(lambda _checked=False, i=index: self._menu_chosen(i))
        self._menu = menu
        menu.aboutToHide.connect(lambda m=menu: self._menu_hidden(m))
        menu.popup_at_cursor()

    def _menu_chosen(self, index: int) -> None:
        if self._menu_trigger_cb is not None:
            self._menu_trigger_cb(index)

    def _menu_hidden(self, menu) -> None:
        if self._menu is not menu:
            menu.deleteLater()
            return
        self._menu = None
        point = menu.dismiss_click_pos()
        menu.deleteLater()
        if self._menu_closed_cb is not None:
            self._menu_closed_cb(None if point is None else (point.x(), point.y()))

    def _apply_settings(self, values: dict, palette: dict, lang: str) -> None:
        if self._settings_window is not None:
            self._settings_window.close()
            self._settings_window.deleteLater()
        window = SettingsWindow(values, palette, lang)
        window.setAttribute(Qt.WA_DeleteOnClose)
        window.saved.connect(self._settings_saved)
        window.destroyed.connect(lambda: self._forget_settings_window(window))
        self._settings_window = window
        window.show()
        window.raise_()
        window.activateWindow()

    def _apply_wizard(self, payload: dict, completion: dict) -> None:
        # Runs on the Qt thread; the Tk side blocks on completion["event"].
        try:
            dialog = WizardDialog(payload)
            dialog.exec()
            completion["value"] = dialog.wizard_result()
        except Exception as error:
            print(f"[QT] wizard failed: {error}", flush=True)
            completion["value"] = None
        finally:
            completion["event"].set()

    def _settings_saved(self, values: dict) -> None:
        if self._settings_saved_cb is not None:
            self._settings_saved_cb(values)

    def _forget_settings_window(self, window) -> None:
        if self._settings_window is window:
            self._settings_window = None

    # -- chat window slots (Qt thread) ---------------------------------------

    def _apply_chat(self, op: str, payload) -> None:
        if self._chat_window is None:
            # Only "open" may create the window: every later op is a gesture
            # from the Tk logic, which can only exist after the window did.
            if op != "open":
                return
            data = payload if isinstance(payload, dict) else {}
            window = ChatWindow(
                data.get("palette") or {},
                str(data.get("lang") or "en"),
                opacity=float(data.get("opacity") or 0.93),
                maximize_opaque=bool(data.get("maximize_opaque", True)),
                reduced_motion=self._reduced_motion,
            )
            window.event.connect(self._chat_forward)
            self._chat_window = window
        self._chat_window.apply_op(op, payload)

    def _chat_forward(self, op: str, payload) -> None:
        if self._chat_event_cb is not None:
            self._chat_event_cb(op, payload)

    def _apply_chat_raise(self) -> None:
        window = self._chat_window
        if window is None:
            return
        if window.isMinimized():
            window.showNormal()
        window.raise_()
        window.activateWindow()

    def _apply_notice(self, title: str, text: str, level: str) -> None:
        parent = (
            self._chat_window
            if self._chat_window is not None and self._chat_window.isVisible()
            else None
        )
        box = QMessageBox(parent)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(
            {"error": QMessageBox.Critical, "warning": QMessageBox.Warning}.get(
                level, QMessageBox.Information
            )
        )
        box.setStandardButtons(QMessageBox.Ok)
        box.exec()

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

    def show_menu(self, items: list, palette: dict) -> None:
        self._ensure_running()
        if self._bridge is not None:
            self._bridge.menuRequested.emit(items, palette)

    def open_settings(self, values: dict, palette: dict, lang: str = "en") -> None:
        self._ensure_running()
        if self._bridge is not None:
            self._bridge.settingsRequested.emit(values, palette, lang)

    def run_wizard(self, payload: dict) -> dict | None:
        """First-boot wizard, modal on the Qt thread; blocks the caller until
        it closes. Returns the config dict, or None when cancelled/unavailable."""
        self._ensure_running()
        if self._bridge is None:
            return None
        completion: dict = {"event": threading.Event(), "value": None}
        self._bridge.wizardRequested.emit(payload, completion)
        completion["event"].wait()
        return completion.get("value")

    def open_chat_window(self, payload: dict) -> None:
        self._ensure_running()
        if self._bridge is not None:
            self._bridge.chatRequested.emit("open", payload)

    def chat_op(self, op: str, payload=None) -> None:
        if self._bridge is not None:
            self._bridge.chatRequested.emit(op, payload)

    def chat_raise(self) -> bool:
        """Raise the chat window if it is up; False lets the caller fall back."""
        window = self._chat_window
        if window is None or not window.isVisible():
            return False
        if self._bridge is not None:
            self._bridge.chatRaiseRequested.emit()
        return True

    def on_chat_event(self, callback) -> None:
        """Called (Qt thread) with every chat-window gesture: send/stop/mic/
        attach_files/menu/close/sidebar_* — the Tk side hops with root.after."""
        self._chat_event_cb = callback

    def notice(self, title: str, text: str, level: str = "info") -> None:
        if self._bridge is not None:
            self._bridge.noticeRequested.emit(title, text, level)

    def _ensure_running(self) -> None:
        # A dead loop would swallow the queued signal silently; raising here
        # makes the Tk side fall back to its own menus/dialog instead.
        if not self._thread.is_alive():
            raise RuntimeError("Qt UI thread is not running")

    def on_menu_trigger(self, callback) -> None:
        # Replacing (not appending) means the last-shown menu owns dispatch.
        self._menu_trigger_cb = callback

    def on_menu_closed(self, callback) -> None:
        """Called (Qt thread) when the posted menu hides on its own, with the
        dismissed click point or None for Esc / item selections."""
        self._menu_closed_cb = callback

    def on_settings_saved(self, callback) -> None:
        self._settings_saved_cb = callback
