"""Audio capture module — records system audio output via PipeWire.

Captures what is being played to the speakers/headphones, NOT a microphone.
``pw-record`` with ``stream.capture.sink=true`` records the default output
device and follows it if the default changes.
"""

import queue
import shutil
import subprocess
import threading
from typing import Optional

import numpy as np

SAMPLE_RATE = 16000
_READ_BYTES = 3200  # 0.1 s of s16 mono


class AudioCapture:
    """Stream system audio as 16 kHz mono float32 from a pw-record subprocess."""

    def __init__(self, target: Optional[str] = None):
        # A sink name to record from instead of the default output.
        self._target = target
        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._chunks: queue.Queue[bytes] = queue.Queue()
        self._stopping = False

    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start recording.

        Raises
        ------
        RuntimeError
            If ``pw-record`` is not installed.
        """
        if not shutil.which("pw-record"):
            raise RuntimeError(
                "pw-record not found. Install it with: "
                "sudo apt install pipewire-bin"
            )

        cmd = [
            "pw-record",
            "-P", "stream.capture.sink=true",
            "--format", "s16",
            "--rate", str(SAMPLE_RATE),
            "--channels", "1",
            "--raw",        # without this, a header is written into the stream
        ]
        if self._target:
            cmd += ["--target", self._target]
        cmd.append("-")     # write to stdout

        self._stopping = False
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        """Drain the pipe so pw-record never blocks while we transcribe."""
        while True:
            data = self._process.stdout.read1(_READ_BYTES)
            if not data:
                break
            self._chunks.put(data)

    # ------------------------------------------------------------------
    def read(self, timeout: float = 0.25) -> np.ndarray:
        """Return all audio captured since the last call.

        Waits up to *timeout* seconds for the first data and returns an empty
        array if there is none.

        Returns
        -------
        np.ndarray
            1-D ``float32`` array in ``[-1.0, 1.0]`` (mono, 16 kHz).

        Raises
        ------
        RuntimeError
            If the capture subprocess has died.
        """
        try:
            parts = [self._chunks.get(timeout=timeout)]
        except queue.Empty:
            if self._process.poll() is not None and not self._stopping:
                stderr = self._process.stderr.read().decode(errors="replace")
                raise RuntimeError(
                    f"pw-record exited with code {self._process.returncode}: "
                    f"{stderr.strip() or '(no error output)'}"
                )
            return np.zeros(0, dtype=np.float32)

        while True:
            try:
                parts.append(self._chunks.get_nowait())
            except queue.Empty:
                break

        data = b"".join(parts)
        # An odd byte can only come from a pipe read splitting a sample.
        usable = len(data) // 2 * 2
        if usable != len(data):
            self._chunks.queue.appendleft(data[usable:])
        return np.frombuffer(data[:usable], dtype=np.int16).astype(np.float32) / 32768.0

    def stop(self) -> None:
        """Stop the capture process."""
        self._stopping = True
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            self._thread.join(timeout=2)
            self._process.stdout.close()
            self._process.stderr.close()
            self._process = None
