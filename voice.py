"""Voice input and output interface for GD Assistant with dynamic noise calibration, Edge-TTS, and system logging."""

from __future__ import annotations

import asyncio
import ctypes
import os
import re
import tempfile
import numpy as np
import pyttsx3
import sounddevice as sd
from faster_whisper import WhisperModel
import edge_tts

SAMPLE_RATE = 16000
SILENCE_DURATION_SEC = 1.2
MAX_RECORDING_SEC = 12
DEFAULT_VOICE = "en-US-AvaNeural"


def play_mp3_native(file_path: str) -> None:
    """Play an MP3 file natively on Windows using the Win32 MCI API."""
    mci = ctypes.windll.winmm.mciSendStringW
    mci("close tts_audio", None, 0, 0)
    mci(f'open "{file_path}" type mpegvideo alias tts_audio', None, 0, 0)
    mci("play tts_audio wait", None, 0, 0)
    mci("close tts_audio", None, 0, 0)


def get_input_devices() -> list[tuple[int, str]]:
    """Return a list of available microphone input devices as (index, name)."""
    devices = []
    try:
        device_list = sd.query_devices()
        for idx, dev in enumerate(device_list):
            if dev.get("max_input_channels", 0) > 0:
                devices.append((idx, dev.get("name", f"Device {idx}")))
    except Exception:
        pass
    return devices


class VoiceAssistant:
    def __init__(self, model_size: str = "small.en", device: int | str | None = None, debug: bool = False) -> None:
        self.debug = debug
        self.device = device
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

        try:
            self.log(f"[TTS] Synthesizing speech audio ({len(clean_text)} chars) with Edge-TTS [{DEFAULT_VOICE}]...")
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_path = temp_file.name
            temp_file.close()

            async def _generate():
                communicate = edge_tts.Communicate(clean_text, DEFAULT_VOICE)
                await communicate.save(temp_path)

            asyncio.run(_generate())
            self.log(f"[TTS] Generated audio temp file: {temp_path}")

            self.log("[TTS] Playing speech via Win32 MCI player...")
            play_mp3_native(temp_path)
            self.log("[TTS] Audio playback completed.")

            if os.path.exists(temp_path):
                os.remove(temp_path)

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
                        self.log("[AUDIO] Continuous silence limit met (1.2s). Stopping recording.")
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