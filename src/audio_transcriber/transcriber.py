"""Transcription module — uses faster-whisper for speech-to-text."""

from __future__ import annotations

from typing import Optional

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.vad import VadOptions, get_speech_timestamps

SAMPLE_RATE = 16000


class SpeechSegmenter:
    """Cut a live audio stream into utterances at pauses in the speech.

    Whisper needs whole phrases: fixed-length chunks split words in half.
    Audio is buffered and checked with Silero VAD, and an utterance is released
    once it is followed by a pause, or when ``max_seconds`` is reached without
    one. Music and other non-speech audio is dropped.
    """

    def __init__(self, max_seconds: float = 15.0, check_seconds: float = 0.5):
        self._max_samples = int(max_seconds * SAMPLE_RATE)
        self._check_samples = int(check_seconds * SAMPLE_RATE)
        self._pause_samples = int(0.5 * SAMPLE_RATE)
        self._keep_samples = int(0.5 * SAMPLE_RATE)
        self._vad = VadOptions(min_silence_duration_ms=300, speech_pad_ms=200)
        self._buffer = np.zeros(0, dtype=np.float32)
        self._unchecked = 0
        self._speech_start: Optional[int] = None
        self._undrafted = 0

    def feed(self, audio: np.ndarray) -> list[np.ndarray]:
        """Add captured audio; return any utterances that are now complete."""
        self._buffer = np.concatenate((self._buffer, audio))
        self._unchecked += len(audio)
        self._undrafted += len(audio)
        if self._unchecked < self._check_samples:
            return []
        self._unchecked = 0

        speech = get_speech_timestamps(self._buffer, self._vad)
        self._speech_start = None
        if not speech:
            self._buffer = self._buffer[-self._keep_samples:]
            return []

        size = len(self._buffer)
        utterances = []
        if speech[-1]["end"] <= size - self._pause_samples:
            cut = speech[-1]["end"]
        elif size >= self._max_samples:
            # No pause yet: cut at the last gap between phrases, if any.
            cut = speech[-2]["end"] if len(speech) > 1 else size
        else:
            self._speech_start = speech[0]["start"]
            return []

        utterances.append(self._buffer[speech[0]["start"]:cut])
        self._buffer = self._buffer[cut:]
        return utterances

    def draft(self, min_new_seconds: float = 1.0) -> Optional[np.ndarray]:
        """Return the utterance in progress, if it has grown enough to redo."""
        if self._speech_start is None:
            return None
        if self._undrafted < min_new_seconds * SAMPLE_RATE:
            return None
        self._undrafted = 0
        return self._buffer[self._speech_start:]

    def flush(self) -> list[np.ndarray]:
        """Return whatever speech is still buffered (used when stopping)."""
        speech = get_speech_timestamps(self._buffer, self._vad)
        buffered = self._buffer
        self._buffer = np.zeros(0, dtype=np.float32)
        if not speech:
            return []
        return [buffered[speech[0]["start"]:speech[-1]["end"]]]


class Transcriber:
    """Wrap faster-whisper for transcribing utterances to text.

    Runs on the CPU: the GPU is shared with the desktop and Ollama, and
    ``small.en`` keeps up with live audio without it.
    """

    def __init__(self, model_size: str = "small.en") -> None:
        self._model: Optional[WhisperModel] = None
        self._model_size = model_size

    # ------------------------------------------------------------------
    def load(self) -> None:
        """Load the model (downloading it first if it isn't cached)."""
        if self._model is None:
            self._model = WhisperModel(
                self._model_size,
                device="cpu",
                compute_type="int8",
                cpu_threads=8,
            )

    # ------------------------------------------------------------------
    def transcribe(self, audio: np.ndarray, draft: bool = False) -> str:
        """Transcribe a mono float32 numpy array (16 kHz) to text.

        ``draft`` trades accuracy for speed, for text that will be replaced.
        """
        self.load()
        segments, _info = self._model.transcribe(
            audio,
            language="en",
            beam_size=1 if draft else 5,
            without_timestamps=draft,
            condition_on_previous_text=False,
        )
        text = "".join(seg.text for seg in segments if seg.no_speech_prob < 0.8)
        return text.strip()

    # ------------------------------------------------------------------
    def set_model_size(self, size: str) -> None:
        """Switch model; the new one loads on the next ``load()``."""
        if size != self._model_size:
            self._model_size = size
            self._model = None

    @property
    def model_size(self) -> str:
        """Current model size setting."""
        return self._model_size
