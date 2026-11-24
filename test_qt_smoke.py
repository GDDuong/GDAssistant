"""Smoke test for the Qt menu + settings + chat window migration (qt branch).

Renders the Qt settings window, the popup menus, and the glass chat window
for both palettes to PNG (visual check) and asserts the save payload,
validation, menu-descriptor, and chat op/event contracts. Widgets use
WA_DontShowOnScreen, so they lay out with real Windows fonts but never pop
over the desktop.
"""
import os
import sys
import tempfile
from pathlib import Path

# Sandbox before importing main: CONFIG_PATH/API_CONFIG_PATH resolve %APPDATA%.
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="gd_qt_")
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import main
from gd_core.translations import get_text
from ui_tk.themes import get_theme
from ui_qt.settings_window import CATEGORIES, SettingsWindow

VALUES = {
    "api_key": "test-key-123",
    "models": ["gemini-3.5-flash-lite", "gemini-3.5-pro"],
    "model": "gemini-3.5-flash-lite",
    "code_model": "gemini-3.5-pro",
    "share_chat_code_model": False,
    "hotkey": "ctrl+alt+g",
    "hotkey_voice": "ctrl+alt+v",
    "hotkey_code": "ctrl+alt+c",
    "mic_devices": [(3, "Headset Mic"), (7, "USB Mic")],
    "mic_position": 2,
    "wake_word_enabled": True,
    "wake_phrase": "hey assistant",
    "voice_orb_enabled": True,
    "theme": "dark",
    "language": "en",
    "window_opacity": 0.8,
    "maximize_opaque": False,
    "personality": "Be concise.",
}


def test_settings_render():
    app = QApplication.instance()
    for theme_name in ("dark", "light"):
        window = SettingsWindow(dict(VALUES, theme=theme_name), get_theme(theme_name), "en")
        assert window._rail.count() == len(CATEGORIES)
        window._share_check.setChecked(True)
        assert not window._code_combo.isEnabled(), "shared models must lock the code combobox"
        window._share_check.setChecked(False)
        assert window._code_combo.isEnabled()
        window._wake_check.setChecked(False)
        assert not window._wake_edit.isEnabled(), "wake phrase must lock when the listener is off"
        window._wake_check.setChecked(True)
        window.setAttribute(Qt.WA_DontShowOnScreen)
        window.show()
        for row in range(len(CATEGORIES)):
            window._rail.setCurrentRow(row)
            app.processEvents()
            path = Path(tempfile.gettempdir()) / f"gd_qt_settings_{theme_name}_{row}.png"
            assert window.grab().save(str(path))
        window.close()
        print(f"OK  settings render {theme_name} (5 pages)")


def test_menu_render():
    import time

    from PySide6.QtCore import QPoint

    from ui_qt.menu import PopupMenu

    app = QApplication.instance()
    for theme_name in ("dark", "light"):
        menu = PopupMenu(get_theme(theme_name), animate=False)
        settings = menu.addAction("Settings")
        menu.addSeparator()
        exit_action = menu.addAction("Exit")
        exit_action.setEnabled(False)
        menu.setAttribute(Qt.WA_DontShowOnScreen)
        menu.show()
        menu.setActiveAction(settings)
        app.processEvents()
        assert menu.width() > 80 and menu.height() > 80, (menu.width(), menu.height())
        path = Path(tempfile.gettempdir()) / f"gd_qt_menu_{theme_name}.png"
        assert menu.grab().save(str(path))
        menu.close()
        print(f"OK  menu render {theme_name} ({path})")

    animated = PopupMenu(get_theme("dark"), animate=True)
    animated.addAction("Settings")
    animated.setAttribute(Qt.WA_DontShowOnScreen)
    animated.show()
    animated.move(100, 100)
    animated._play_entrance()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and animated.windowOpacity() < 0.99:
        app.processEvents()
        time.sleep(0.01)
    assert animated.windowOpacity() > 0.98, animated.windowOpacity()
    assert animated.pos() == QPoint(100, 100), animated.pos()
    animated.close()
    print("OK  menu entrance animation settles at full opacity + final pos")


def test_menu_dismiss_click():
    from PySide6.QtCore import QEvent, QPoint, QPointF
    from PySide6.QtGui import QMouseEvent

    from ui_qt.menu import PopupMenu

    menu = PopupMenu(get_theme("dark"), animate=False)
    menu.addAction("Settings")
    menu.resize(160, 100)

    assert menu.dismiss_click_pos() is None
    outside = QMouseEvent(
        QEvent.MouseButtonPress, QPointF(-5, -5), QPointF(500, 500),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    menu._note_outside_click(outside)
    assert menu.dismiss_click_pos() == QPoint(500, 500), menu.dismiss_click_pos()

    inside_menu = PopupMenu(get_theme("dark"), animate=False)
    inside_menu.addAction("Settings")
    inside_menu.resize(160, 100)
    inside = QMouseEvent(
        QEvent.MouseButtonPress, QPointF(20, 20), QPointF(620, 620),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    inside_menu._note_outside_click(inside)
    assert inside_menu.dismiss_click_pos() is None, "item clicks must not be replayed"
    print("OK  dismiss-click recording (outside recorded, inside ignored)")


def test_save_payload():
    window = SettingsWindow(VALUES, get_theme("dark"), "en")
    captured: list[dict] = []
    window.saved.connect(captured.append)

    window._key_edit.setText("   ")
    window._save()
    assert captured == [], "empty API key must not emit a save"
    assert not window._key_error.isHidden(), "empty API key must show the inline error"

    window._key_edit.setText(" new-key ")
    window._model_combo.setCurrentText("gemini-3.5-pro")
    window._save()
    assert len(captured) == 1
    payload = captured[0]
    assert payload["api_key"] == "new-key"
    assert payload["model"] == "gemini-3.5-pro"
    assert payload["code_model"] == "gemini-3.5-pro"
    assert payload["voice_device"] == 7, "mic position 2 must map to device index 7"
    assert payload["theme"] == "dark"
    assert payload["language"] == "en"
    assert payload["personality"] == "Be concise."
    assert payload["wake_word_enabled"] is True
    assert payload["window_opacity"] == 0.8, "the opacity slider must round-trip"
    assert window._opacity_slider.value() == 80
    assert payload["maximize_opaque"] is False, "the maximize-opaque toggle must round-trip"
    print("OK  save payload round-trip")


def test_chat_window_render():
    from ui_qt.chat_window import ChatWindow

    app = QApplication.instance()
    for theme_name in ("dark", "light"):
        window = ChatWindow(get_theme(theme_name), "en")
        events: list[tuple[str, object]] = []
        window.event.connect(lambda op, payload: events.append((op, payload)))

        window.apply_op("title", {"title": "GD Assistant", "header": "Chat Mode"})
        window.apply_op("append", {"speaker": "You", "text": "plain question", "markdown": False})
        window.apply_op("append", {
            "speaker": "GD",
            "text": "# Heading\n\nwith `code` and [link](https://example.com)\n\n```py\nprint('x')\n```",
            "markdown": True,
        })
        window.apply_op("stream_begin")
        window.apply_op("stream_replace", {"text": "working on it..."})
        window.apply_op("stream_finish", {"text": "streamed piece done", "markdown": True})
        window.apply_op("rows", {
            "rows": [
                {"id": "c1", "label": "First chat", "title": "First chat"},
                {"id": "c2", "label": "Second chat", "title": "Second chat"},
            ],
            "current": "c1",
        })
        window.apply_op("attachments", {"paths": ["C:/tmp/shot.png", "C:/tmp/notes.txt"]})
        window.apply_op("status", {"text": "Thinking..."})
        window.setAttribute(Qt.WA_DontShowOnScreen)
        window.show()
        app.processEvents()

        text = window.transcript.toPlainText()
        assert "plain question" in text, text
        assert "streamed piece done" in text, text
        assert "Heading" in text and "print('x')" in text, text

        # A fenced block used to leak its background into the paragraph
        # separator and tint the next message (see _reset_tail_formats).
        document = window.transcript.document()
        streamed_block = document.find("streamed piece done").block()
        assert streamed_block.blockFormat().background().style() == Qt.NoBrush, (
            "streamed reply must not inherit the code block background"
        )
        assert document.lastBlock().blockFormat().background().style() == Qt.NoBrush, (
            "the separator gap must not inherit the code block background"
        )

        window.input_box.setText("hello")
        window._handle_send()
        assert events[-1] == ("send", "hello"), events[-1]

        window._header.file_button.click()
        assert events[-1][0] == "menu" and events[-1][1]["kind"] == "file", events[-1]
        assert len(events[-1][1]["rects"]["file"]) == 4, events[-1]

        path = Path(tempfile.gettempdir()) / f"gd_qt_chat_{theme_name}.png"
        assert window.grab().save(str(path))
        window.close()
        print(f"OK  chat window render {theme_name} ({path})")


def test_chat_rail_and_scroll():
    from ui_qt.chat_window import ChatWindow

    app = QApplication.instance()
    window = ChatWindow(get_theme("dark"), "en", reduced_motion=True)
    window.setAttribute(Qt.WA_DontShowOnScreen)
    window.show()
    app.processEvents()

    # Taskbar click-to-minimize needs WS_MINIMIZEBOX on the frameless window.
    assert window.windowFlags() & Qt.WindowMinimizeButtonHint, (
        "the chat window must keep WindowMinimizeButtonHint for taskbar minimize"
    )

    # The rail handle used to float to the vertical middle when the sidebar
    # collapsed (lone layout item absorbing free space).
    handle = window.sidebar._toggle_button
    expanded_geom = handle.geometry()
    window.sidebar.toggle()
    app.processEvents()
    assert handle.geometry() == expanded_geom, (
        "the rail handle must stay anchored when collapsing", handle.geometry(), expanded_geom
    )
    assert handle.height() > 200, "the rail handle should span the sidebar height"
    path = Path(tempfile.gettempdir()) / "gd_qt_chat_rail_closed.png"
    assert window.grab().save(str(path))
    window.sidebar.toggle()
    app.processEvents()

    assert window.sidebar.list.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert window.sidebar.list.textElideMode() == Qt.ElideRight

    # Re-wraps used to drag the transcript view away from the bottom.
    for index in range(60):
        window.apply_op(
            "append", {"speaker": "GD", "text": f"line {index} " + "word " * 20, "markdown": False}
        )
    app.processEvents()
    bar = window.transcript.verticalScrollBar()
    assert bar.value() == bar.maximum(), (bar.value(), bar.maximum())

    window.resize(window.width() - 120, window.height() - 60)
    app.processEvents()
    assert bar.value() == bar.maximum(), "resize must keep the view at the bottom"
    window.resize(window.width() + 200, window.height() + 80)
    app.processEvents()
    assert bar.value() == bar.maximum(), "resize must keep the view at the bottom"

    bar.setValue(200)
    app.processEvents()
    window.resize(window.width() - 200, window.height())
    app.processEvents()
    assert bar.value() == 200, "a scrolled-up view must not be yanked down"
    window.close()
    print(f"OK  rail handle anchored + transcript pinned to bottom ({path})")


def test_chat_motion_tracking():
    import time

    from ui_qt.chat_window import ChatWindow
    from ui_qt.motion import tick_interval_ms

    app = QApplication.instance()
    window = ChatWindow(get_theme("dark"), "en")
    window.setAttribute(Qt.WA_DontShowOnScreen)
    window.show()
    app.processEvents()

    sidebar = window.sidebar
    handle = sidebar._toggle_button

    # Timelines must be paced at one tick per monitor refresh, not Qt's 16ms.
    assert sidebar._collapse.updateInterval() == tick_interval_ms(), (
        "the collapse timeline must use the refresh-matched interval"
    )
    screen = app.primaryScreen()
    hz = float(screen.refreshRate()) if screen else 0.0
    expected = max(4, min(16, int(1000.0 / hz))) if hz > 0 else 16
    assert tick_interval_ms() == expected, (tick_interval_ms(), expected, hz)

    # Deterministic replay of the drift: with the content hidden, shrinking
    # the sidebar used to centre the lone handle (it slid from x=4 toward the
    # bar's middle). Every sampled width must keep it at the left edge.
    sidebar._content.setVisible(False)
    for width in range(216, 23, -12):
        sidebar.setFixedWidth(width)
        app.processEvents()
        assert handle.x() == 4, ("handle drifted mid-collapse", width, handle.x())
    sidebar.setFixedWidth(216)
    sidebar._content.setVisible(True)
    app.processEvents()

    # Live animated collapse: sample the real timeline; the handle must stay
    # pinned the whole run, and ticks must keep up with the monitor.
    sidebar.toggle()
    changes: list[float] = []
    last_width = None
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and sidebar.width() != 24:
        app.processEvents()
        assert handle.x() == 4, ("handle drifted during live collapse", handle.x())
        if sidebar.width() != last_width:
            changes.append(time.monotonic())
            last_width = sidebar.width()
        time.sleep(0.002)
    assert sidebar.width() == 24, sidebar.width()
    assert len(changes) >= 5, ("collapse should be sampled mid-flight", len(changes))
    deltas = [b - a for a, b in zip(changes, changes[1:])]
    mean_delta = sum(deltas) / len(deltas)
    print(f"OK  collapse ticks: {len(changes)} frames, mean {mean_delta * 1000:.1f} ms")
    assert mean_delta < 0.030, ("animation stutters beyond 30ms/frame", mean_delta)
    sidebar.toggle()
    app.processEvents()

    # Entrance slide must settle exactly at the recorded target position.
    target = window.pos()
    window.play_entrance()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and window.windowOpacity() < 0.99:
        app.processEvents()
        time.sleep(0.01)
    assert window.windowOpacity() > 0.98, window.windowOpacity()
    assert window.pos() == target, (window.pos(), target)
    window.close()
    print("OK  entrance slide settles at target pos + full opacity")


def test_orb_motion():
    from ui_qt.overlay import VoiceBubble

    app = QApplication.instance()
    orb = VoiceBubble(reduced_motion=False)
    orb.setAttribute(Qt.WA_DontShowOnScreen)
    orb.set_state("listening")
    app.processEvents()

    import time

    # The braid phase loop must keep advancing on the refresh-matched ticks.
    phase = orb._phase
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and orb._phase <= phase:
        app.processEvents()
        time.sleep(0.01)
    assert orb._phase > phase, "the phase loop must keep running"

    # State change eases to a settled pop/morph (OutBack overshoots, ends 1.0).
    orb.set_state("result", "hello there")
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and (orb._pop < 0.999 or orb._morph < 0.999):
        app.processEvents()
        time.sleep(0.01)
    assert orb._pop >= 0.999 and orb._morph >= 0.999, (orb._pop, orb._morph)

    # Fade-out finishes by hiding; a stopped fade must not hide mid-run.
    orb.set_state("hidden")
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and orb.isVisible():
        app.processEvents()
        time.sleep(0.01)
    assert not orb.isVisible(), "fade-out must hide the orb"
    orb.close()

    # Reduced motion: state changes land instantly (no pop/morph animation)
    # and the decorative phase loop never starts.
    still = VoiceBubble(reduced_motion=True)
    still.setAttribute(Qt.WA_DontShowOnScreen)
    still.set_state("listening")
    app.processEvents()
    assert still._pop == 1.0 and still._morph == 1.0, (still._pop, still._morph)
    assert still._phase == 0.0, "the braid loop must not run under reduced motion"
    still.close()
    print("OK  orb phase loop + state easing + fade-out hide + reduced motion")


def test_menu_descriptors():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="Settings", command=lambda: None)
    menu.add_separator()
    menu.add_command(label="Exit", command=lambda: None, state="disabled")
    items = main.menu_descriptors(menu)
    assert items == [
        {"label": "Settings", "enabled": True},
        {"separator": True},
        {"label": "Exit", "enabled": False},
    ], items

    assert main.menu_descriptors(tk.Menu(root, tearoff=0)) == []

    fired: list[bool] = []
    menu.entryconfigure(0, command=lambda: fired.append(True))
    main.invoke_menu_item(menu, 0)
    assert fired == [True], "invoke_menu_item must run the Tk command"
    root.destroy()
    print("OK  menu descriptors + invoke")


def test_opacity_and_maximize():
    from ui_qt.chat_window import ChatWindow

    def center_alpha(target) -> int:
        image = target._glass_pixmap().toImage()
        return image.pixelColor(image.width() // 2, image.height() // 2).alpha()

    app = QApplication.instance()
    window = ChatWindow(get_theme("dark"), "en", opacity=1.0, reduced_motion=True)
    window.setAttribute(Qt.WA_DontShowOnScreen)
    window.show()
    app.processEvents()
    assert center_alpha(window) == 255, "100% opacity must be fully opaque"

    key_before = window._glass_key
    window.apply_op("opacity", {"value": 0.5})
    app.processEvents()
    assert window._opacity == 0.5, window._opacity
    window._glass_pixmap()
    assert window._glass_key != key_before, "opacity change must invalidate the glass cache"
    half = center_alpha(window)
    assert half < 255, "opacity below 100% must stay translucent"
    window.apply_op("opacity", {"value": 0.93})
    assert center_alpha(window) > half, "a higher opacity must be more opaque"

    window.apply_op("opacity", {"value": 0.1})
    assert window._opacity == 0.4, "opacity must clamp to the slider floor"
    window.apply_op("opacity", {"value": "junk"})
    assert window._opacity == 0.4, "non-numeric opacity must be ignored"

    window.toggle_maximize()
    app.processEvents()
    assert window.isMaximized()
    assert window._maximized, "changeEvent must track the maximized state"
    assert window._header.maximize_button.text() == "\u2750"
    glass = window._glass_pixmap()
    assert glass.width() == window.width(), "maximized glass must fill the window (no shadow margin)"
    assert center_alpha(window) == 255, "maximized is fully opaque by default"

    window.apply_op("opacity", {"value": 0.5, "maximize_opaque": False})
    app.processEvents()
    assert not window._maximize_opaque, "the setting must turn off via the opacity op"
    assert center_alpha(window) < 255, "with the setting off, maximized follows the slider"

    window.toggle_maximize()
    app.processEvents()
    assert not window.isMaximized() and not window._maximized
    assert window._header.maximize_button.text() == "\u25A1"
    assert center_alpha(window) < 255, "restoring keeps the slider opacity"
    window.close()
    print("OK  opacity op + clamp + maximize square-glass round-trip")


def test_toggle_switch():
    from ui_qt.settings_window import ToggleSwitch

    app = QApplication.instance()
    for theme_name in ("dark", "light"):
        toggle = ToggleSwitch(get_text("share_models_label", "en"), get_theme(theme_name))
        toggle.setAttribute(Qt.WA_DontShowOnScreen)
        toggle.show()
        app.processEvents()
        toggle.resize(toggle.sizeHint())
        for state in (False, True):
            toggle.setChecked(state)
            app.processEvents()
            path = Path(tempfile.gettempdir()) / f"gd_qt_toggle_{theme_name}_{int(state)}.png"
            assert toggle.grab().save(str(path)), path
        assert toggle.isChecked() is True
        toggle.click()
        assert toggle.isChecked() is False, "clicking must flip the toggle"
        toggle.close()
    print("OK  toggle switch paints off/on for both palettes")


def test_wizard():
    from PySide6.QtWidgets import QPushButton

    from ui_qt.wizard import WizardDialog

    app = QApplication.instance()
    payload = {
        "language": "en",
        "theme": "light",
        "model": "gemini-3.5-flash-lite",
        "code_model": "gemini-3.5-pro",
        "share_chat_code_model": False,
        "hotkey": "ctrl+alt+g",
        "models": ["gemini-3.5-flash-lite", "gemini-3.5-pro"],
        "mic_devices": [(3, "Headset Mic"), (7, "USB Mic")],
        "voice_device": 7,
        "personality": "",
        "window_opacity": 1.0,
    }
    dialog = WizardDialog(payload)
    dialog.setAttribute(Qt.WA_DontShowOnScreen)
    dialog.show()
    app.processEvents()

    buttons = {b.text(): b for b in dialog.findChildren(QPushButton)}
    buttons["English"].click()
    app.processEvents()
    assert dialog._step == 1, "picking a language must advance to the theme step"
    assert dialog.windowTitle().startswith("GD Assistant")

    dialog._theme_dark.setChecked(True)
    dialog._apply_theme("dark")
    dialog._opacity_slider.setValue(60)
    dialog._next()
    assert dialog._step == 2
    dialog._next()  # empty API key must not advance
    assert dialog._step == 2, "empty API key must stay on the step"
    assert not dialog._key_error.isHidden()
    dialog._key_edit.setText("  wizard-key  ")
    dialog._next()
    assert dialog._step == 3
    dialog._mic_combo.setCurrentIndex(2)
    dialog._hotkey_edit.setText("ctrl+alt+x")
    dialog._next()
    assert dialog._step == 4
    dialog._pers_edit.setPlainText("Be witty.")
    dialog._next()
    app.processEvents()
    result = dialog.wizard_result()
    assert result is not None and dialog.isVisible() is False
    assert result["api_key"] == "wizard-key"
    assert result["language"] == "en"
    assert result["theme"] == "dark"
    assert result["window_opacity"] == 0.6
    assert result["model"] == "gemini-3.5-flash-lite"
    assert result["share_chat_code_model"] is False
    assert result["hotkey"] == "ctrl+alt+x"
    assert result["voice_device"] == 7, "mic position 2 must map to device index 7"
    assert result["personality"] == "Be witty."

    cancelled = WizardDialog(payload)
    cancelled.reject()
    assert cancelled.wizard_result() is None, "cancel must yield no result"
    print("OK  wizard full walk (lang -> theme+opacity -> api -> mic -> persona) + cancel")


def test_service_module():
    import inspect

    from ui_qt.service import QtUiService

    for method in (
        "show_menu", "open_settings", "on_menu_trigger", "on_menu_closed", "on_settings_saved",
        "open_chat_window", "chat_op", "chat_raise", "on_chat_event", "notice",
    ):
        assert callable(getattr(QtUiService, method)), method
    # Closing the settings window used to quit the Qt loop (QApplication's
    # quit-on-last-window-closed default; the orb is a Qt.Tool), which made
    # every later menu click do nothing. Guard the one-line fix.
    assert "setQuitOnLastWindowClosed(False)" in inspect.getsource(QtUiService._run), (
        "the Qt service loop must survive all Qt windows closing"
    )
    print("OK  service module exposes the menu + settings API")


def run() -> None:
    app = QApplication.instance() or QApplication([])
    test_settings_render()
    test_menu_render()
    test_menu_dismiss_click()
    test_save_payload()
    test_chat_window_render()
    test_chat_rail_and_scroll()
    test_chat_motion_tracking()
    test_opacity_and_maximize()
    test_toggle_switch()
    test_wizard()
    test_orb_motion()
    test_menu_descriptors()
    test_service_module()
    print("Qt smoke checks passed")


if __name__ == "__main__":
    run()
