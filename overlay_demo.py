"""overlay_demo.py: drive the Qt voice bubble with real microphone audio.

Ctrl+Alt+Space starts a turn (or --wake to also summon with the wake word).
The bubble shows the live mic level while you speak, then the transcript.
No Gemini here: this proves the core->UI event path (audio thread -> bubble).

Usage:
    python overlay_demo.py            hotkey only
    python overlay_demo.py --wake     hotkey + "hey assistant"
"""

from __future__ import annotations

import sys
import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

WAKE_PHRASE = "hey assistant"
RESULT_VISIBLE_MS = 4000


class Bridge(QObject):
    """Thread-safe relay: audio/wake threads emit, the bubble receives."""

    state = Signal(str, str)
    level = Signal(float)


def main() -> None:
    use_wake = "--wake" in sys.argv[1:]
    app = QApplication(sys.argv)

    from ui_qt.overlay import VoiceBubble

    bubble = VoiceBubble()
    screen = app.primaryScreen().availableGeometry()
    bubble.move(screen.center().x() - bubble.width() // 2, screen.top() + 40)

    bridge = Bridge()

    def apply_state(state: str, text: str = "") -> None:
        bubble.set_state(state, text)
        if state == "result":
            QTimer.singleShot(RESULT_VISIBLE_MS, lambda: bubble.set_state("hidden"))

    bridge.state.connect(apply_state)
    bridge.level.connect(bubble.set_level)

    busy = threading.Event()
    listener = None

    from gd_core.voice import preload_voice_assistant

    threading.Thread(target=preload_voice_assistant, daemon=True).start()

    def start_turn() -> None:
        if busy.is_set():
            return
        busy.set()

        def run() -> None:
            from gd_core.voice import get_voice_assistant

            if listener is not None:
                listener.pause()
            assistant = get_voice_assistant()
            bridge.state.emit("listening", "")
            text = assistant.listen_dynamic(on_level=bridge.level.emit)
            bridge.state.emit("result", text or "(nothing heard)")
            if listener is not None:
                listener.resume()
            busy.clear()

        threading.Thread(target=run, daemon=True).start()

    if use_wake:
        from gd_core.wakeword import WakeWordListener

        listener = WakeWordListener(WAKE_PHRASE, on_wake=start_turn)
        listener.start()
        print(f"[DEMO] Wake word '{WAKE_PHRASE}' armed. Say it or press Ctrl+Alt+Space.")
    else:
        print("[DEMO] Press Ctrl+Alt+Space to start a voice turn.")

    try:
        import keyboard

        keyboard.add_hotkey("ctrl+alt+space", start_turn)
    except Exception as error:
        print(f"[DEMO WARNING] Global hotkey unavailable ({error}); use --wake instead.")

    bubble.set_state("hidden")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
