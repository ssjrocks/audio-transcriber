"""GUI module — PyQt6-based interface for the audio transcriber.

Uses real AudioCapture and Transcriber classes.  Transcription runs in a
worker QThread so the GUI never freezes; results are posted back via Qt
signals (queued by default across threads).
"""

import sys
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QPushButton,
    QLabel,
    QComboBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from audio_transcriber.audio_capture import AudioCapture
from audio_transcriber.transcriber import Transcriber


# ------------------------------------------------------------------
# Worker thread — runs capture / transcription loop off the GUI thread
# ------------------------------------------------------------------
class TranscriptionWorker(QThread):
    """Runs the audio-capture loop in a background thread."""

    # Emitted when a new transcript chunk is ready
    transcript_ready = pyqtSignal(str)
    # Emitted to update the status label
    status_changed = pyqtSignal(str)
    # Emitted on error (e.g. no backend)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._capture: AudioCapture | None = None
        self._transcriber: Transcriber | None = None
        self._running = False

    # ------------------------------------------------------------------
    def setup(self) -> None:
        """Create AudioCapture and Transcriber, start capture."""
        try:
            self._capture = AudioCapture()
            self._transcriber = Transcriber()
            self._capture.start()
        except RuntimeError as exc:
            self._capture = None
            self._transcriber = None
            self.error_occurred.emit(str(exc))

    # ------------------------------------------------------------------
    def run(self):
        """Main loop: read chunks, detect speech, transcribe, emit results."""
        self._running = True

        if self._capture is None or self._transcriber is None:
            return  # setup already reported an error

        # Lazy model load — show status while it happens
        self.status_changed.emit("Loading model...")

        # Force a model load by probing is_speech (triggers lazy init)
        # We use a tiny silence chunk so it doesn't waste time transcribing
        self._transcriber.is_speech(self._transcriber.transcribe(
            self._capture.read_chunk(0.05)
        ))  # noqa: B023 — intentional side-effect call

        self.status_changed.emit("Listening...")

        while self._running:
            chunk = self._capture.read_chunk(3.0)

            if len(chunk) == 0:
                self._running = False
                self.status_changed.emit("Stopped")
                break

            if self._transcriber.is_speech(chunk):
                text = self._transcriber.transcribe(chunk)
                if text:
                    self.transcript_ready.emit(text)

            self.status_changed.emit("Listening...")

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Stop the loop and clean up capture resources."""
        self._running = False
        if self._capture:
            self._capture.stop()
            self._capture = None
        if self._transcriber:
            self._transcriber = None
        self.wait(timeout=5)


# ------------------------------------------------------------------
# Main window
# ------------------------------------------------------------------
class TranscriberApp(QMainWindow):
    """Desktop GUI for the audio transcriber."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Transcriber")
        self.resize(800, 600)

        # -- Status label -------------------------------------------
        self.status_label = QLabel("Stopped")
        self.status_label.setFont(QFont("Monospace", 10))

        # -- Transcript text area -----------------------------------
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setFont(QFont("Monospace", 12))
        self.transcript.setPlaceholderText(
            "Transcribed text will appear here..."
        )

        # -- Model-size combo box -----------------------------------
        self.model_combo = QComboBox()
        self.model_combo.addItems(["tiny", "base", "small"])
        self.model_combo.setFont(QFont("Monospace", 10))

        # -- Start / Stop buttons -----------------------------------
        self.start_btn = QPushButton("Start")
        self.start_btn.setFont(QFont("Monospace", 12))
        self.start_btn.setStyleSheet(
            "QPushButton { background-color: #2ecc71; border: none; "
            "padding: 8px 24px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #27ae60; }"
            "QPushButton:disabled { background-color: #95a5a6; }"
        )
        self.start_btn.clicked.connect(self.start_capture)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFont(QFont("Monospace", 12))
        self.stop_btn.setStyleSheet(
            "QPushButton { background-color: #e74c3c; border: none; "
            "padding: 8px 24px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #c0392b; }"
            "QPushButton:disabled { background-color: #95a5a6; }"
        )
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_capture)

        # -- Toolbar row --------------------------------------------
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Model:"))
        toolbar.addWidget(self.model_combo)
        toolbar.addStretch()
        toolbar.addWidget(self.start_btn)
        toolbar.addWidget(self.stop_btn)

        # -- Main layout --------------------------------------------
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.addWidget(self.status_label)
        layout.addWidget(self.transcript)
        layout.addLayout(toolbar)

        # -- Worker & wiring ----------------------------------------
        self._worker = TranscriptionWorker()
        self._worker.transcript_ready.connect(self._on_transcript_update)
        self._worker.status_changed.connect(self.status_label.setText)
        self._worker.error_occurred.connect(self._on_error)
        self._worker_started = False

    # ---- public API ------------------------------------------------

    def start_capture(self):
        """Start the capture / transcription loop."""
        self._worker_started = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("Starting...")
        self._worker.start()

    def stop_capture(self):
        """Stop the capture / transcription loop."""
        self._worker.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Stopped")

    # ---- internal slots --------------------------------------------

    def _on_transcript_update(self, text: str):
        """Append received text and auto-scroll."""
        self.transcript.append(text)
        self.transcript.see(self.transcript.document().blockCount())

    def _on_error(self, msg: str):
        """Handle error from the worker thread."""
        self.status_label.setText(f"Error: {msg}")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    # ---- model selection -------------------------------------------

    def _on_model_changed(self):
        """Reset loaded model when the user picks a different size."""
        size = self.model_combo.currentText()
        if self._worker._transcriber is not None:
            self._worker._transcriber.set_model_size(size)
            self._worker._transcriber._model = None  # force reload next time


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
def run_gui():
    """Launch the PyQt6 GUI application."""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = TranscriberApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_gui()
