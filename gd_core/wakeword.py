"""Always-listening wake word detector for GD Assistant.

Runs the shared Faster-Whisper speech model against short speech clips
gated by an energy VAD, so continuous listening stays cheap on CPU.
"""

from __future__ import annotations

import difflib
import re
import threading
import time
import unicodedata

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
CHUNK_SEC = 0.1
CALIBRATION_CHUNKS = 3
SILENCE_SEC = 0.5
MIN_SPEECH_SEC = 0.4
MAX_CLIP_SEC = 6.0
SPEECH_FACTOR = 1.3
MIN_THRESHOLD = 0.008
COOLDOWN_SEC = 2.5


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(text.split())


def phrase_in_transcript(transcript: str, phrase: str, min_ratio: float = 0.75) -> bool:
    """Tolerant match that survives STT mishearings like 'Pay Assistant' for 'hey assistant'."""
    heard = _normalize(transcript)
    wanted = _normalize(phrase)
    if not heard or not wanted:
        return False
    if wanted in heard:
        return True
    if difflib.SequenceMatcher(None, wanted, heard).ratio() >= min_ratio:
        return True
    wanted_words = wanted.split()
    if len(wanted_words) == 1:
        return False
    heard_words = heard.split()
    hits = sum(1 for word in wanted_words if word in heard_words)
    if hits / len(wanted_words) >= min_ratio:
        return True
    # A short clip where only the keyword survives ("assistance" for "hey
    # assistant") should wake just like the exact keyword does above. A
    # longer sentence that merely mentions the keyword is normal speech.
    if len(heard_words) > 3:
        return False
    keyword = wanted_words[-1]
    return any(
        difflib.SequenceMatcher(None, keyword, word).ratio() >= 0.84
        for word in heard_words
    )


class WakeWordListener:
    """Background thread that watches a microphone for a summoning sentence.

    The stream keeps running while paused, but audio is discarded so the
    detector never hears the assistant's own replies or competes with a
    normal voice request.
    """

    def __init__(
        self,
        phrase: str,
        device: int | str | None = None,
        on_wake=None,
        debug: bool = False,
    ) -> None:
        self.phrase = phrase
        self.device = device
        self.on_wake = on_wake
        self.debug = debug
        self._model = None
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread = threading.Thread(target=self._run, name="wake-word-listener", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def log(self, message: str) -> None:
        if self.debug:
            print(message, flush=True)

    def _run(self) -> None:
        self.log(f"[WAKE] Listener starting (phrase: '{self.phrase}').")
        try:
            from gd_core.voice import get_voice_assistant

            # Share the main base.en model instead of loading a second one:
            # better accuracy than tiny.en with no extra model resident.
            self._model = get_voice_assistant(debug=self.debug).stt_model
            self.log("[WAKE] Sharing the main speech model (base.en).")
        except Exception as error:
            self.log(f"[WAKE ERROR] Could not load wake model: {error}")
            return

        chunk_samples = int(SAMPLE_RATE * CHUNK_SEC)
        while not self._stop.is_set():
            try:
                with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=self.device) as stream:
                    self._listen(stream, chunk_samples)
            except Exception as error:
                if self._stop.is_set():
                    break
                self.log(f"[WAKE WARNING] Mic stream error ({error}); retrying in 5 s.")
                if self._stop.wait(5.0):
                    break

    def _listen(self, stream: sd.InputStream, chunk_samples: int) -> None:
        calibration: list[float] = []
        noise_floor = MIN_THRESHOLD
        speaking = False
        buffer: list[np.ndarray] = []
        buffered_samples = 0
        silence_samples = 0
        last_wake = 0.0
        max_clip_samples = int(MAX_CLIP_SEC * SAMPLE_RATE)

        while not self._stop.is_set():
            data, _ = stream.read(chunk_samples)
            if self._paused.is_set():
                calibration = []
                speaking = False
                buffer.clear()
                buffered_samples = 0
                silence_samples = 0
                continue

            level = float(np.max(np.abs(data.squeeze())))

            if len(calibration) < CALIBRATION_CHUNKS:
                calibration.append(level)
                if len(calibration) == CALIBRATION_CHUNKS:
                    noise_floor = max(max(calibration), MIN_THRESHOLD)
                    self.log(f"[WAKE] Calibrated ambient noise: {noise_floor:.4f}")
                continue

            threshold = max(noise_floor * SPEECH_FACTOR, MIN_THRESHOLD)

            if level > threshold:
                speaking = True
                silence_samples = 0
            elif speaking:
                silence_samples += chunk_samples

            if speaking:
                buffer.append(data.squeeze())
                buffered_samples += chunk_samples
                if buffered_samples > max_clip_samples:
                    dropped = 0
                    while buffer and dropped < buffered_samples - max_clip_samples:
                        dropped += len(buffer.pop(0))
                    buffered_samples -= dropped

                if silence_samples >= int(SILENCE_SEC * SAMPLE_RATE):
                    speaking = False
                    silence_samples = 0
                    clip = np.concatenate(buffer) if buffer else np.empty(0)
                    buffer.clear()
                    buffered_samples = 0

                    if len(clip) < int(MIN_SPEECH_SEC * SAMPLE_RATE):
                        continue
                    peak = float(np.max(np.abs(clip)))
                    if peak > 0:
                        clip = clip / peak
                    if time.monotonic() - last_wake < COOLDOWN_SEC:
                        continue

                    try:
                        transcript = self._transcribe(clip)
                    except Exception as error:
                        self.log(f"[WAKE WARNING] Transcription failed: {error}")
                        continue

                    if phrase_in_transcript(transcript, self.phrase):
                        last_wake = time.monotonic()
                        self.log("[WAKE] Summoning phrase detected!")
                        if self.on_wake is not None:
                            try:
                                self.on_wake()
                            except Exception as error:
                                self.log(f"[WAKE ERROR] Wake callback failed: {error}")

    def _transcribe(self, clip: np.ndarray) -> str:
        # Priming the decoder with the phrase biases the model toward hearing it correctly.
        segments, _ = self._model.transcribe(clip, beam_size=1, initial_prompt=self.phrase)
        return " ".join(seg.text for seg in segments).strip()
