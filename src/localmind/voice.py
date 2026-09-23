"""Speech in and speech out, for talking to LocalMind.

Listening uses faster-whisper: the same model that transcribes audio documents, so voice mode
costs no extra VRAM beyond what audio ingestion already uses. Speaking uses Kokoro-82M through
onnxruntime on the CPU. On this PC it speaks about ten times faster than real time there, and
keeping it off the GPU leaves every byte of VRAM for the chat model's context window.
"""
from __future__ import annotations

import io
import logging
import re
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from localmind.config import VoiceConfig

logger = logging.getLogger(__name__)

MAX_SPOKEN_CHARS = 1200  # one request; the page sends a sentence or two at a time

_CODE_BLOCK = re.compile(r"```.*?(```|$)", re.S)
_LINK = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
_URL = re.compile(r"https?://\S+|www\.\S+")
_EMOJI = re.compile(
    "\\s*[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]+"
)
_MARKUP = re.compile(r"(^|\s)#{1,6}\s+|[*_`~|>]+|^\s*[-+•]\s+|^\s*\d+\.\s+(?=\S)", re.M)


def speakable(text: str) -> str:
    """Turn an answer into something that sounds right read aloud.

    The page already sends rendered text, but a reply can still carry markdown (half-rendered
    while streaming), code, links and emoji, none of which should be pronounced.
    """
    text = _CODE_BLOCK.sub(" ", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("a link", text)
    text = _EMOJI.sub("", text)
    text = _MARKUP.sub(lambda m: m.group(1) or " ", text)
    # Line breaks end headings and list items, which carry no full stop but need the pause.
    lines = [line.strip(" .") for line in text.splitlines()]
    text = " ".join(line if line[-1] in "!?:;," else line + "." for line in lines if line)
    return re.sub(r"\s{2,}", " ", text)[:MAX_SPOKEN_CHARS].strip()


def wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm.tobytes())
    return buffer.getvalue()


@dataclass
class Transcript:
    text: str
    language: str
    audio_seconds: float
    elapsed: float


class VoiceUnavailable(RuntimeError):
    pass


class VoiceEngine:
    """Loads lazily and is shared by every browser tab, so each model is loaded once."""

    def __init__(self, config: VoiceConfig, model_manager, on_gpu_change: Callable[[], None] | None = None):
        self.config = config
        self.models = model_manager
        self.on_gpu_change = on_gpu_change
        self._tts = None
        self._voice: np.ndarray | None = None
        self._listen_lock = threading.Lock()
        self._speak_lock = threading.Lock()
        self._warming: threading.Thread | None = None

    # ------------------------------------------------------------------ status
    @staticmethod
    def tts_installed() -> bool:
        try:
            import kokoro_onnx  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def ready(self) -> bool:
        return self._tts is not None and "whisper" in getattr(self.models, "_loaded", {})

    def warm(self) -> None:
        """Load both models in the background, so the first thing you say isn't slow to answer."""
        if self.ready or (self._warming and self._warming.is_alive()):
            return

        def load():
            try:
                self._whisper()
                self._kokoro()
            except Exception:  # noqa: BLE001 - reported again, to the user, on first use
                logger.exception("Voice models failed to load")

        self._warming = threading.Thread(target=load, name="voice-warm", daemon=True)
        self._warming.start()

    # ------------------------------------------------------------------ listening
    def _whisper(self):
        loaded = "whisper" in self.models._loaded
        model = self.models.get_whisper()
        if not loaded and self.on_gpu_change:
            # Whisper's VRAM isn't torch's, so context windows estimated before it loaded are
            # now too generous. Make the next turn re-measure.
            self.on_gpu_change()
        return model

    def transcribe(self, audio: bytes) -> Transcript:
        if not audio:
            return Transcript("", "", 0.0, 0.0)
        started = time.monotonic()
        model = self._whisper()
        with self._listen_lock:
            segments, info = model.transcribe(
                io.BytesIO(audio),
                language=self.config.language or None,
                beam_size=5,
                # Silence and room noise otherwise come back as "Thank you." and the like.
                vad_filter=True,
                condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
        return Transcript(text, info.language, float(info.duration), time.monotonic() - started)

    # ------------------------------------------------------------------ speaking
    def _kokoro(self):
        if self._tts is not None:
            return self._tts
        if not self.tts_installed():
            raise VoiceUnavailable("Speech output needs the kokoro-onnx package:  pip install kokoro-onnx")
        from huggingface_hub import hf_hub_download
        from kokoro_onnx import Kokoro

        repo = self.config.tts_model
        logger.info("Loading Kokoro TTS (%s, voice %s)", repo, self.config.tts_voice)
        model_path = hf_hub_download(repo, self.config.tts_file)
        voice_path = hf_hub_download(repo, f"voices/{self.config.tts_voice}.bin")
        voice = np.fromfile(voice_path, dtype=np.float32).reshape(-1, 1, 256)
        # kokoro-onnx wants a voices archive on disk; ours holds just the chosen voice.
        archive = Path(voice_path).with_suffix(".npz")
        if not archive.exists():
            np.savez(archive, **{self.config.tts_voice: voice})
        self._voice = voice
        self._tts = Kokoro(model_path, str(archive))
        return self._tts

    @property
    def _lang(self) -> str:
        # Kokoro voices are named by accent: a = American, b = British English.
        return "en-gb" if self.config.tts_voice.startswith("b") else "en-us"

    def speak(self, text: str) -> bytes | None:
        """WAV audio for `text`, or None when there's nothing worth saying."""
        text = speakable(text)
        if not re.search(r"\w", text):
            return None
        tts = self._kokoro()
        with self._speak_lock:  # espeak's phonemiser isn't thread-safe
            audio, sample_rate = tts.create(text, voice=self._voice, speed=self.config.tts_speed, lang=self._lang)
        return wav_bytes(audio, sample_rate)
