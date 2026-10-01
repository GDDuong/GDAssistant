"""Voice input and output interface for GD Assistant with dynamic noise calibration, Edge-TTS, and system logging."""

from __future__ import annotations

import asyncio
import ctypes
import os
import re
import tempfile
import threading
import numpy as np
import pyttsx3
import sounddevice as sd
import edge_tts

SAMPLE_RATE = 16000
SILENCE_DURATION_SEC = 0.8
MAX_RECORDING_SEC = 12
DEFAULT_VOICE = "en-US-AvaNeural"
DEFAULT_STT_MODEL = "base.en"
TTS_TIMEOUT_SEC = 20

_voice_model_lock = threading.Lock()
_shared_voice_assistant: "VoiceAssistant | None" = None
_voice_input_device: int | str | None = None


def play_mp3_native(file_path: str) -> None:
    """Play an MP3 file natively on Windows using the Win32 MCI API."""
    mci = ctypes.windll.winmm.mciSendStringW
    mci("close tts_audio", None, 0, 0)
    mci(f'open "{file_path}" type mpegvideo alias tts_audio', None, 0, 0)
    mci("play tts_audio wait", None, 0, 0)
    mci("close tts_audio", None, 0, 0)


def get_input_devices() -> list[tuple[int, str]]:
    """Return WASAPI microphone input devices as (index, name)."""
    devices = []
    try:
        # Windows exposes every mic once per host API (MME, DirectSound,
        # WASAPI, WDM-KS); listing only WASAPI shows each physical mic once.
        wasapi_index = None
        for api_idx, api in enumerate(sd.query_hostapis()):
            if "WASAPI" in str(api.get("name", "")):
                wasapi_index = api_idx
                break

        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0 and (
                wasapi_index is None or dev.get("hostapi") == wasapi_index
            ):
                devices.append((idx, dev.get("name", f"Device {idx}")))
    except Exception:
        pass
    return devices


class VoiceAssistant:
    def __init__(self, model_size: str = DEFAULT_STT_MODEL, device: int | str | None = None, debug: bool = False) -> None:
        self.debug = debug
        self.device = device
        # Deferred import: keeps pure-TTS warm-up from paying the heavy
        # Faster-Whisper import cost at module load.
        from faster_whisper import WhisperModel

        self.log(f"[STT] Initializing Faster-Whisper model ({model_size})...")
        self.stt_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.log("[STT] Faster-Whisper model ready.")

    def log(self, message: str) -> None:
        """Write system log messages when console debug mode is active."""
        if self.debug:
            print(message, flush=True)

    def speak(self, text: str) -> None:
        """Convert response text to natural speech using Edge-TTS (with SAPI5 fallback)."""
        if not text:
            return
        clean_text = re.sub(r"[\*`#_~]", "", text)
        temp_path: str | None = None

        try:
            self.log(f"[TTS] Synthesizing speech audio ({len(clean_text)} chars) with Edge-TTS [{DEFAULT_VOICE}]...")
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_path = temp_file.name
            temp_file.close()

            async def _generate():
                communicate = edge_tts.Communicate(clean_text, DEFAULT_VOICE)
                # Without this timeout a stalled Edge endpoint wedged the UI
                # in the "Speaking..." state forever.
                await asyncio.wait_for(communicate.save(temp_path), timeout=TTS_TIMEOUT_SEC)

            asyncio.run(_generate())

            if os.path.getsize(temp_path) == 0:
                raise RuntimeError("Edge-TTS produced an empty audio file")

            self.log("[TTS] Playing speech via Win32 MCI player...")
            play_mp3_native(temp_path)
            self.log("[TTS] Audio playback completed.")

        except Exception as error:
            self.log(f"[TTS WARNING] Edge-TTS failed ({error}), falling back to SAPI5...")
            try:
                engine = pyttsx3.init("sapi5")
                engine.setProperty("rate", 170)
                engine.say(clean_text)
                engine.runAndWait()
                engine.stop()
                self.log("[TTS] SAPI5 fallback playback completed.")
            except Exception as fallback_error:
                self.log(f"[TTS ERROR] SAPI5 failed: {fallback_error}")
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def listen_dynamic(self) -> str:
        """Record audio with automated noise floor calibration and silence detection."""
        self.log("[AUDIO] Opening microphone input stream...")
        chunk_duration = 0.1
        chunk_samples = int(SAMPLE_RATE * chunk_duration)

        recording: list[np.ndarray] = []
        has_spoken = False
        silence_samples = 0
        total_samples = 0
        max_samples = int(MAX_RECORDING_SEC * SAMPLE_RATE)

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=self.device) as stream:
            # Calibrate room noise level during first 0.3 seconds
            calibration_chunks = []
            for _ in range(3):
                data, _ = stream.read(chunk_samples)
                calibration_chunks.append(np.max(np.abs(data)))

            ambient_noise = max(calibration_chunks)
            silence_threshold = max(ambient_noise * 1.5, 0.015)
            self.log(f"[AUDIO] Calibrated ambient noise: {ambient_noise:.4f} | Silence threshold set: {silence_threshold:.4f}")

            self.log("[AUDIO] Listening for speech input...")
            while total_samples < max_samples:
                data, _ = stream.read(chunk_samples)
                audio_chunk = data.squeeze()
                volume = float(np.max(np.abs(audio_chunk)))

                recording.append(audio_chunk)
                total_samples += len(audio_chunk)

                if volume > silence_threshold:
                    if not has_spoken:
                        self.log("[AUDIO] Speech activity detected.")
                    has_spoken = True
                    silence_samples = 0
                elif has_spoken:
                    silence_samples += len(audio_chunk)
                    if silence_samples >= int(SILENCE_DURATION_SEC * SAMPLE_RATE):
                        self.log(f"[AUDIO] Continuous silence limit met ({SILENCE_DURATION_SEC}s). Stopping recording.")
                        break

        if not recording or not has_spoken:
            self.log("[AUDIO] No speech detected during recording window.")
            return ""

        audio_flat = np.concatenate(recording)
        max_val = np.max(np.abs(audio_flat))
        if max_val > 0:
            audio_flat = audio_flat / max_val

        self.log("[STT] Transcribing audio with Faster-Whisper...")
        segments, _ = self.stt_model.transcribe(
            audio_flat,
            beam_size=5,
            vad_filter=True,
            initial_prompt="User speaking to GD Assistant.",
        )

        transcription = " ".join([seg.text for seg in segments]).strip()
        self.log(f"[STT] Transcription complete ({len(transcription.split())} words transcribed).")
        return transcription

    def run_voice_loop(self, session) -> None:
        """Run the hands-free terminal voice loop."""
        self.log("[VOICE LOOP] Starting interactive voice session.")
        self.speak("GD Assistant voice mode ready. How can I help you?")

        while True:
            try:
                input("\nPress Enter to start listening...")
                user_text = self.listen_dynamic()

                if not user_text:
                    print("GD: I didn't hear anything.")
                    self.speak("I didn't hear anything.")
                    continue

                print(f"You (Voice): '{user_text}'")

                if user_text.lower() in {"exit", "quit", "stop", "goodbye"}:
                    self.speak("Goodbye!")
                    break

                reply = session.ask(user_text)
                print(f"GD: {reply}")
                self.speak(reply)

            except KeyboardInterrupt:
                self.log("[VOICE LOOP] Session interrupted by user.")
                self.speak("Goodbye!")
                break


def get_voice_assistant(debug: bool = False, device: int | str | None = None) -> VoiceAssistant:
    """Return the one shared, locally cached speech-to-text model instance."""
    global _shared_voice_assistant, _voice_input_device
    if device is not None:
        _voice_input_device = device

    # Keep initialization out of the GUI thread. If a microphone request arrives
    # while preloading is still in progress, its worker waits here without
    # creating or downloading a second Whisper model.
    with _voice_model_lock:
        if _shared_voice_assistant is None:
            _shared_voice_assistant = VoiceAssistant(debug=debug, device=_voice_input_device)
        elif debug:
            _shared_voice_assistant.debug = True
        return _shared_voice_assistant


def set_voice_input_device(device: int | str | None) -> None:
    """Point the shared assistant at a new microphone without reloading models."""
    global _voice_input_device
    _voice_input_device = device
    with _voice_model_lock:
        if _shared_voice_assistant is not None:
            _shared_voice_assistant.device = device


def preload_tts_voice(debug: bool = False) -> None:
    """Warm the Edge-TTS network path so the first spoken reply starts faster."""
    temp_path = ""
    try:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_path = temp_file.name
        temp_file.close()

        async def _warm():
            communicate = edge_tts.Communicate("Voice ready.", DEFAULT_VOICE)
            await asyncio.wait_for(communicate.save(temp_path), timeout=TTS_TIMEOUT_SEC)

        asyncio.run(_warm())
        if debug:
            print("[TTS] Edge-TTS warm-up completed.", flush=True)
    except Exception as error:
        if debug:
            print(f"[TTS WARNING] Edge-TTS warm-up skipped: {error}", flush=True)
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def preload_voice_assistant(debug: bool = False) -> None:
    """Warm the shared Faster-Whisper model from a caller-owned background thread."""
    try:
        get_voice_assistant(debug=debug)
    except Exception as error:
        # Voice remains optional: a later microphone request can retry loading,
        # and text chat / Code Mode stay available even if warm-up fails.
        if debug:
            print(f"[STT WARNING] Background voice preload failed: {error}", flush=True)
