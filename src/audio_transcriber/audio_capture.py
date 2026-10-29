"""Audio capture module — records system audio output via PipeWire/PulseAudio.

Captures the *monitor* of the active system audio sink (i.e. what is being
played out of the speakers/headphones), NOT a microphone input.
"""

import os
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Optional

import numpy as np


def _get_default_sink() -> Optional[str]:
    """Return the name of the active default audio sink.

    Tries several methods in order of preference:
    1. ``pactl get-default-sink``  (PulseAudio compatibility layer)
    2. ``pactl info``  → ``Active Sink`` line
    3. ``pw-cli list-objects Node``  → first real Audio/Sink node
    4. ``pw-metadata -n settings 0 default.audio.sink``

    Returns the sink node name (e.g. ``alsa_output.pci-0000_02_00.1.hdmi-stereo``)
    or ``None`` if nothing is found.
    """
    # --- 1. pactl get-default-sink ---
    try:
        result = subprocess.run(
            ["pactl", "get-default-sink"],
            capture_output=True, text=True, timeout=5,
        )
        sink = result.stdout.strip()
        if sink:
            return sink
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # --- 2. pactl info → Active Sink ---
    try:
        result = subprocess.run(
            ["pactl", "info"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if "Active Sink" in line:
                sink = line.split(":", 1)[1].strip()
                if sink:
                    return sink
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # --- 3. pw-cli: find a real Audio/Sink node ---
    if shutil.which("pw-cli"):
        try:
            result = subprocess.run(
                ["pw-cli", "list-objects", "Node"],
                capture_output=True, text=True, timeout=5,
            )
            lines = result.stdout.splitlines()
            current_name = None
            current_class = None
            for line in lines:
                if "node.name" in line:
                    current_name = line.split("=")[1].strip().strip('"')
                if "media.class" in line:
                    current_class = line.split("=")[1].strip().strip('"')
                    if current_class == "Audio/Sink" and current_name:
                        # Prefer real (non-virtual) sinks
                        if "Dummy" in current_name or "Freewheel" in current_name:
                            continue
                        return current_name
        except (subprocess.TimeoutExpired, IndexError):
            pass

    # --- 4. pw-metadata default.audio.sink ---
    if shutil.which("pw-metadata"):
        try:
            result = subprocess.run(
                ["pw-metadata", "-n", "settings", "0", "default.audio.sink"],
                capture_output=True, text=True, timeout=5,
            )
            sink = result.stdout.strip()
            if sink:
                return sink
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return None


class AudioCapture:
    """Capture system audio output using PipeWire's pw-cat or PulseAudio's pacat."""

    def __init__(self, sink_name: Optional[str] = None):
        self._backend = self._detect_backend()
        self._sink_name = sink_name or _get_default_sink()
        self._process: Optional[subprocess.Popen] = None
        self._tmp_file: Optional[str] = None
        self._tmp_fd: Optional[int] = None
        self._file_pos = 0          # byte offset of last read in tmp file
        self._file_lock = threading.Lock()
        self._running = False
        self._stderr_output: str = ""

    # ------------------------------------------------------------------
    @staticmethod
    def _detect_backend() -> str:
        """Detect which audio backend is available."""
        if shutil.which("pw-cat") and shutil.which("pw-cli"):
            return "pipewire"
        if shutil.which("pacat") and shutil.which("pactl"):
            return "pulseaudio"
        return "none"

    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start capturing audio from the system output monitor.

        Spawns *pw-cat* (PipeWire) or *pacat* (PulseAudio) as a subprocess
        that writes raw 16-bit PCM (16 kHz, mono) to a temporary file.
        A background thread monitors the subprocess for death.

        Raises
        ------
        RuntimeError
            If no audio backend is found or the default sink cannot be
            determined.
        """
        if self._backend == "none":
            raise RuntimeError(
                "No audio backend found. Install pipewire (pw-cat) or "
                "pulseaudio-utils (pacat/pactl)."
            )
        if not self._sink_name:
            raise RuntimeError(
                "No default sink found. Cannot capture system audio."
            )

        self._running = True
        self._file_pos = 0
        self._stderr_output = ""

        monitor = f"{self._sink_name}.monitor"

        # Create a temp file for the subprocess to write into.
        # pw-cat does not write to subprocess.PIPE reliably (buffering issue),
        # so we use a real file on disk.
        self._tmp_file = tempfile.mktemp(suffix=".raw", dir="/tmp")
        self._tmp_fd = os.open(
            self._tmp_file,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o644,
        )

        if self._backend == "pipewire":
            cmd = [
                "pw-cat",
                "-r",                          # record mode
                "--target", monitor,           # sink.monitor
                "--format", "s16",             # 16-bit signed PCM
                "--rate", "16000",
                "--channels", "1",
                "-",                           # write to stdout (fd passed below)
            ]
        else:
            cmd = [
                "pacat",
                "-r",
                "--raw",
                "--process-time=1000",
                "--format=s16",
                "--rate=16000",
                "--channels=1",
                monitor,
            ]

        # Pass the temp file fd as stdout so pw-cat writes directly there
        self._process = subprocess.Popen(
            cmd,
            stdout=self._tmp_fd,
            stderr=subprocess.PIPE,
        )

        # Start background watcher
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()

        # Give the subprocess a moment to open the monitor and start writing.
        # pw-cat needs a brief warm-up before data appears in the temp file.
        time.sleep(0.5)

    def _watch_loop(self) -> None:
        """Monitor the subprocess and capture stderr on death."""
        try:
            self._process.wait()
        except Exception:
            pass
        finally:
            if self._process and self._process.stderr:
                self._stderr_output = self._process.stderr.read().decode(
                    errors="replace"
                )

    def read_chunk(self, duration_sec: float) -> np.ndarray:
        """Read *duration_sec* seconds of audio as a float32 numpy array.

        Parameters
        ----------
        duration_sec : float
            Desired duration in seconds. The actual amount returned depends
            on what the subprocess has produced so far.

        Returns
        -------
        np.ndarray
            1-D array of dtype ``float32`` with values in the range
            ``[-1.0, 1.0]`` (mono, 16 kHz).

        Raises
        ------
        RuntimeError
            If the capture subprocess has died.
        """
        if self._process and self._process.poll() is not None:
            stderr = self._stderr_output or "(no stderr captured)"
            raise RuntimeError(
                f"Audio capture subprocess died (exit code "
                f"{self._process.returncode}). stderr: {stderr}"
            )

        if not self._tmp_file or not os.path.exists(self._tmp_file):
            return np.zeros(0, dtype=np.float32)

        # How many bytes we need for the requested duration
        needed = int(duration_sec * 16000 * 2)  # 16 kHz × 2 bytes/sample

        with self._file_lock:
            with open(self._tmp_file, "rb") as f:
                f.seek(self._file_pos)
                available = f.read(needed)
                self._file_pos = f.tell()

        if not available:
            return np.zeros(0, dtype=np.float32)

        # Convert raw int16 bytes to float32 in [-1, 1]
        raw = np.frombuffer(available, dtype=np.int16).astype(np.float32)
        audio = raw / 32768.0
        return audio

    def stop(self) -> None:
        """Stop the capture process and clean up resources."""
        self._running = False
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            self._process = None
        if self._tmp_file and os.path.exists(self._tmp_file):
            try:
                os.unlink(self._tmp_file)
            except OSError:
                pass
            self._tmp_file = None
            self._tmp_fd = None

    @property
    def backend(self) -> str:
        """The detected backend: ``'pipewire'``, ``'pulseaudio'``, or ``'none'``."""
        return self._backend

    @property
    def sink_name(self) -> Optional[str]:
        """The sink node name being monitored, or ``None``."""
        return self._sink_name


# ----------------------------------------------------------------------
# __main__ test block
# ----------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Audio backend: {AudioCapture()._detect_backend()}")

    capture = AudioCapture()
    print(f"Sink: {capture.sink_name}")
    print("Starting capture…")
    capture.start()

    try:
        duration = 2.0
        print(f"Reading {duration} seconds of audio…")
        audio = capture.read_chunk(duration)
        if len(audio) > 0:
            rms = float(np.sqrt(np.mean(audio ** 2)))
            print(f"RMS level: {rms:.6f}")
        else:
            print("RMS level: 0.0 (no audio data available)")
    except RuntimeError as exc:
        print(f"Error during capture: {exc}")
    finally:
        print("Stopping capture…")
        capture.stop()
    print("Done.")
