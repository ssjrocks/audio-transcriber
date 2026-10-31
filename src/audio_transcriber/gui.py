"""GUI module — PyQt6-based interface for the audio transcriber.

Uses real AudioCapture and Transcriber classes.  Transcription runs in a
worker QThread so the GUI never freezes; results are posted back via Qt
signals (queued by default across threads).
"""

import sys
import threading
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QPushButton,
    QLabel,
    QComboBox,
    QMessageBox,
)
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QTextOption

from audio_transcriber.audio_capture import AudioCapture
from audio_transcriber.transcriber import SpeechSegmenter, Transcriber

MODELS = ["base", "small.en", "medium.en"]
DEFAULT_MODEL = "small.en"
ICON = Path(__file__).with_name("icon.png")


# ------------------------------------------------------------------
# Worker thread — runs capture / transcription loop off the GUI thread
# ------------------------------------------------------------------
class TranscriptionWorker(QThread):
    """Runs the audio-capture loop in a background thread."""

    # Emitted when a new transcript chunk is ready
    transcript_ready = pyqtSignal(str)
    # Emitted to update the status label
    status_changed = pyqtSignal(str)
    # Emitted on error (e.g. pw-record missing)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.transcriber = Transcriber(DEFAULT_MODEL)
        self.capture_target: str | None = None
        self._stop_requested = threading.Event()

    # ------------------------------------------------------------------
    def run(self):
        """Main loop: read audio, split it into utterances, emit their text."""
        capture = AudioCapture(self.capture_target)
        try:
            self.status_changed.emit(
                f"Loading model {self.transcriber.model_size}..."
            )
            self.transcriber.load()
            if self._stop_requested.is_set():
                return

            capture.start()
            segmenter = SpeechSegmenter()
            self.status_changed.emit("Listening...")

            while not self._stop_requested.is_set():
                for utterance in segmenter.feed(capture.read()):
                    self._transcribe(utterance)

            # Don't lose the words that were playing when Stop was pressed.
            capture.stop()
            for utterance in segmenter.flush():
                self._transcribe(utterance)
        except Exception as exc:
            self.error_occurred.emit(str(exc))
        finally:
            capture.stop()

    def _transcribe(self, utterance) -> None:
        self.status_changed.emit("Transcribing...")
        text = self.transcriber.transcribe(utterance)
        if text:
            self.transcript_ready.emit(text)
        self.status_changed.emit("Listening...")

    # ------------------------------------------------------------------
    def begin(self) -> None:
        """Start the thread; clearing here keeps a quick Stop from being lost."""
        self._stop_requested.clear()
        self.start()

    def request_stop(self) -> None:
        """Ask the loop to finish; ``finished`` is emitted when it has."""
        self._stop_requested.set()


# ------------------------------------------------------------------
# Main window
# ------------------------------------------------------------------
class TranscriberApp(QMainWindow):
    """Desktop GUI for the audio transcriber."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Transcriber")
        self.setWindowIcon(QIcon(str(ICON)))
        self.resize(800, 600)

        # -- Status label -------------------------------------------
        self.status_label = QLabel("Stopped")
        self.status_label.setFont(QFont("Monospace", 10))

        # -- Transcript text area -----------------------------------
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setFont(QFont("Monospace", 12))
        self.transcript.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        self.transcript.setPlaceholderText(
            "Transcribed text will appear here..."
        )

        # -- Model-size combo box -----------------------------------
        self.model_combo = QComboBox()
        self.model_combo.addItems(MODELS)
        self.model_combo.setCurrentText(DEFAULT_MODEL)
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

        # -- Transcript actions -------------------------------------
        self.save_btn = QPushButton("Save...")
        self.save_btn.clicked.connect(self.save_transcript)
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.clicked.connect(self.copy_transcript)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_transcript)

        # -- Toolbar row --------------------------------------------
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Model:"))
        toolbar.addWidget(self.model_combo)
        toolbar.addWidget(self.save_btn)
        toolbar.addWidget(self.copy_btn)
        toolbar.addWidget(self.clear_btn)
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
        self._worker.finished.connect(self._on_worker_finished)
        self._error_shown = False
        self._unsaved = False
        self._close_when_finished = False

    # ---- public API ------------------------------------------------

    def start_capture(self):
        """Start the capture / transcription loop."""
        self._error_shown = False
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.model_combo.setEnabled(False)
        self.status_label.setText("Starting...")
        self._worker.transcriber.set_model_size(self.model_combo.currentText())
        self._worker.begin()

    def stop_capture(self):
        """Stop the capture / transcription loop."""
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Stopping...")
        self._worker.request_stop()

    def save_transcript(self):
        """Write the transcript to a text file the user picks."""
        default = Path.home() / time.strftime("transcript-%Y-%m-%d-%H%M.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save transcript", str(default), "Text files (*.txt)"
        )
        if path:
            self._write_transcript(path)

    def _write_transcript(self, path: str):
        try:
            Path(path).write_text(
                self.transcript.toPlainText() + "\n", encoding="utf-8"
            )
        except OSError as exc:
            QMessageBox.critical(self, "Save Error", f"Could not save:\n\n{exc}")
            return
        self._unsaved = False

    def copy_transcript(self):
        """Copy the whole transcript to the clipboard."""
        QApplication.clipboard().setText(self.transcript.toPlainText())

    def clear_transcript(self):
        """Empty the transcript area."""
        self.transcript.clear()
        self._unsaved = False

    # ---- internal slots --------------------------------------------

    def _on_transcript_update(self, text: str):
        """Append received text; QTextEdit keeps following the end."""
        self.transcript.append(f"[{time.strftime('%H:%M:%S')}] {text}")
        self._unsaved = True

    def _on_error(self, msg: str):
        """Handle error from the worker thread."""
        self._error_shown = True
        self.status_label.setText(f"Error: {msg}")
        QMessageBox.critical(
            self,
            "Capture Error",
            f"Audio capture failed:\n\n{msg}",
        )

    def _on_worker_finished(self):
        """Reset the controls once the worker has really stopped."""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.model_combo.setEnabled(True)
        if not self._error_shown:
            self.status_label.setText("Stopped")
        if self._close_when_finished:
            self.close()

    def closeEvent(self, event):
        """Ask about unsaved text, and let the worker stop before closing."""
        if self._unsaved and not self._close_when_finished:
            answer = QMessageBox.question(
                self,
                "Unsaved transcript",
                "Quit without saving the transcript?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        if self._worker.isRunning():
            # Destroying a running QThread aborts the process.
            self._close_when_finished = True
            self.hide()
            self._worker.request_stop()
            event.ignore()
            return
        event.accept()


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
def run_gui():
    """Launch the PyQt6 GUI application."""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setDesktopFileName("audio-transcriber")
    window = TranscriberApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_gui()
