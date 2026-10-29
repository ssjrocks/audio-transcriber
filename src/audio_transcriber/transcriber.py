"""Transcription module — uses faster-whisper for speech-to-text."""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
from faster_whisper import WhisperModel


class Transcriber:
    """Wrap faster-whisper for transcribing audio chunks to text.

    The WhisperModel is loaded lazily on the first call to ``transcribe()``
    with default settings: ``WhisperModel('base', device='cpu', compute_type='int8')``.
    """

    def __init__(self) -> None:
        self._model: Optional[WhisperModel] = None
        self._model_size: str = "base"
        self._device: str = "cpu"
        self._compute_type: str = "int8"

    # ------------------------------------------------------------------
    def _ensure_model_loaded(self) -> WhisperModel:
        """Load the WhisperModel on first use (lazy init)."""
        if self._model is None:
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
        return self._model

    # ------------------------------------------------------------------
    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a mono float32 numpy array (16 kHz) to text.

        Parameters
        ----------
        audio : np.ndarray
            1-D array of dtype ``float32`` with values in ``[-1.0, 1.0]``.

        Returns
        -------
        str
            The transcribed text with leading/trailing whitespace stripped.
            Returns an empty string if silence is detected (RMS <= 0.005).
        """
        if len(audio) == 0:
            return ""

        # Skip silent chunks to save compute time
        if not self.is_speech(audio):
            return ""

        model = self._ensure_model_loaded()
        segments, info = model.transcribe(audio, language="en")
        text = " ".join(seg.text for seg in segments)
        return text.strip()

    # ------------------------------------------------------------------
    def is_speech(self, audio: np.ndarray) -> bool:
        """Simple RMS-based voice activity detection.

        Returns ``True`` if the RMS level exceeds 0.005, indicating
        non-silent audio, otherwise ``False``.

        Parameters
        ----------
        audio : np.ndarray
            1-D float32 array.

        Returns
        -------
        bool
        """
        if len(audio) == 0:
            return False
        rms = float(np.sqrt(np.mean(audio ** 2)))
        return rms > 0.005

    # ------------------------------------------------------------------
    def set_model_size(self, size: str) -> None:
        """Switch the model size for the next load.

        Parameters
        ----------
        size : str
            One of ``'tiny'``, ``'base'``, ``'small'`` (or other
            faster-whisper model sizes).

        Notes
        -----
        If a model is already loaded, calling this will **not** reload it
        — the model is loaded lazily on the first ``transcribe()`` call
        or when ``_model`` is ``None``. To apply a new size to an
        already-loaded model, set ``self._model = None`` first.
        """
        self._model_size = size

    # ------------------------------------------------------------------
    @property
    def model_size(self) -> str:
        """Current model size setting."""
        return self._model_size

    @property
    def model(self) -> Optional[WhisperModel]:
        """The loaded WhisperModel, or ``None`` if not yet loaded."""
        return self._model


# ----------------------------------------------------------------------
# __main__ test block
# ----------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Transcriber self-test ===")

    # Create a Transcriber instance
    t = Transcriber()
    print(f"Model size: {t.model_size}")
    print(f"Model loaded: {t.model is not None}")

    # Generate a 2-second 440 Hz sine wave at 16 kHz
    sr = 16000
    duration = 2.0
    t_array = np.linspace(0, duration, int(sr * duration), endpoint=False)
    sine_wave = np.sin(2.0 * math.pi * 440.0 * t_array).astype(np.float32)

    # Check RMS before transcription
    rms = float(np.sqrt(np.mean(sine_wave ** 2)))
    print(f"Sine wave RMS: {rms:.6f}")
    print(f"is_speech(sine_wave): {t.is_speech(sine_wave)}")

    # Transcribe (may be empty/garbage for a sine tone — that's expected)
    print(f"Transcribing 2s of 440 Hz sine wave…")
    result = t.transcribe(sine_wave)
    print(f"Result: '{result}'")

    # Test set_model_size
    t.set_model_size("tiny")
    print(f"Model size after set_model_size('tiny'): {t.model_size}")

    # Test with silence (all zeros)
    silence = np.zeros(16000, dtype=np.float32)
    print(f"is_speech(silence): {t.is_speech(silence)}")
    silence_result = t.transcribe(silence)
    print(f"Transcribe silence: '{silence_result}' (should be empty)")

    print("=== Done ===")
