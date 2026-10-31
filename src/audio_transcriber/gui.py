"""GUI module — PyQt6-based interface for the audio transcriber.

Uses real AudioCapture and Transcriber classes.  Transcription runs in a
worker QThread so the GUI never freezes; results are posted back via Qt
signals (queued by default across threads).
"""

import logging
import sys
import threading
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QInputDialog,
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
from PyQt6.QtGui import (
    QFont,
    QIcon,
    QPalette,
    QTextCharFormat,
    QTextCursor,
    QTextOption,
)

from audio_transcriber import APP_ID, APP_NAME, REPO, __version__, appreports, updater
from audio_transcriber.audio_capture import SAMPLE_RATE, AudioCapture
from audio_transcriber.transcriber import SpeechSegmenter, Transcriber

LOG = logging.getLogger(__name__)

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
    # Emitted with the draft of the phrase still being spoken (live mode)
    draft_ready = pyqtSignal(str)
    # Emitted to update the status label
    status_changed = pyqtSignal(str)
    # Emitted on error (e.g. pw-record missing)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.transcriber = Transcriber(DEFAULT_MODEL)
        self.capture_target: str | None = None
        self.live = True
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
                audio = capture.read()
                for utterance in segmenter.feed(audio):
                    self._transcribe(utterance)

                # A long read means we're behind: skip drafts and catch up.
                if self.live and len(audio) < SAMPLE_RATE:
                    draft = segmenter.draft()
                    if draft is not None:
                        text = self.transcriber.transcribe(draft, draft=True)
                        if text:
                            self.draft_ready.emit(text)

            # Don't lose the words that were playing when Stop was pressed.
            capture.stop()
            for utterance in segmenter.flush():
                self._transcribe(utterance)
        except Exception as exc:
            LOG.exception("capture stopped")
            appreports.report_error(exc, "capturing or transcribing")
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


class BackgroundTask(QThread):
    """Run one blocking call off the GUI thread."""

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, task):
        super().__init__()
        self._task = task

    def run(self):
        try:
            self.succeeded.emit(self._task())
        except Exception as exc:
            LOG.warning("background task failed: %s", exc)
            self.failed.emit(str(exc))


# ------------------------------------------------------------------
# Main window
# ------------------------------------------------------------------
class TranscriberApp(QMainWindow):
    """Desktop GUI for the audio transcriber."""

    report_finished = pyqtSignal(bool)

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

        # -- Live mode ----------------------------------------------
        self.live_check = QCheckBox("Live")
        self.live_check.setChecked(True)
        self.live_check.setToolTip(
            "Show words while they are spoken. Grey text is a draft that is "
            "corrected when the speaker pauses."
        )
        self.live_check.toggled.connect(self._on_live_toggled)

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

        # -- Update button, shown when a release is available --------
        self.update_btn = QPushButton()
        self.update_btn.setVisible(False)
        self.update_btn.clicked.connect(self.install_update)

        # -- Toolbar row --------------------------------------------
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Model:"))
        toolbar.addWidget(self.model_combo)
        toolbar.addWidget(self.live_check)
        toolbar.addWidget(self.save_btn)
        toolbar.addWidget(self.copy_btn)
        toolbar.addWidget(self.clear_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.update_btn)
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
        self._worker.draft_ready.connect(self._show_draft)
        self._worker.status_changed.connect(self.status_label.setText)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._error_shown = False
        self._unsaved = False
        self._close_when_finished = False
        self._draft_pos: int | None = None
        self._update: updater.Update | None = None
        self._tasks: set[BackgroundTask] = set()
        self._draft_format = QTextCharFormat()
        self._draft_format.setForeground(
            self.palette().color(QPalette.ColorRole.PlaceholderText)
        )

        # -- Menu ---------------------------------------------------
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("Check for updates...", self.check_for_updates)
        help_menu.addAction("Report a problem...", self.report_problem)
        help_menu.addAction("About", self.show_about)
        self.report_finished.connect(self._on_report_finished)

    # ---- public API ------------------------------------------------

    def start_capture(self):
        """Start the capture / transcription loop."""
        self._error_shown = False
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.model_combo.setEnabled(False)
        self.status_label.setText("Starting...")
        LOG.info("start: model %s, live %s",
                 self.model_combo.currentText(), self.live_check.isChecked())
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
            Path(path).write_text(self._final_text() + "\n", encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Save Error", f"Could not save:\n\n{exc}")
            return
        self._unsaved = False

    def copy_transcript(self):
        """Copy the whole transcript to the clipboard."""
        QApplication.clipboard().setText(self._final_text())

    def clear_transcript(self):
        """Empty the transcript area."""
        self.transcript.clear()
        self._draft_pos = None
        self._unsaved = False

    # ---- updates and problem reports -------------------------------

    def _run_task(self, task, on_success, on_failure) -> None:
        worker = BackgroundTask(task)
        worker.succeeded.connect(on_success)
        worker.failed.connect(on_failure)
        worker.finished.connect(lambda: self._tasks.discard(worker))
        self._tasks.add(worker)  # dropping a running QThread aborts the process
        worker.start()

    def start_update_check(self):
        """Quietly look for a new release, at most every 12 hours."""
        if updater.due():
            updater.mark_checked()
            self._run_task(updater.check, self._on_update_checked, lambda _msg: None)

    def check_for_updates(self):
        """Check now and say what was found."""
        def done(update):
            self._on_update_checked(update)
            if update is None:
                QMessageBox.information(
                    self, "Updates", f"{APP_NAME} {__version__} is up to date."
                )

        def failed(msg):
            QMessageBox.warning(self, "Updates", f"Could not check:\n\n{msg}")

        self._run_task(updater.check, done, failed)

    def _on_update_checked(self, update):
        if update is not None:
            self._update = update
            self.update_btn.setText(f"Update to {update.version}")
            self.update_btn.setVisible(True)

    def install_update(self):
        """Install the available update and restart."""
        if self._worker.isRunning():
            QMessageBox.information(self, "Update", "Press Stop first.")
            return
        update = self._update
        self.update_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.status_label.setText(f"Installing {update.version}...")

        def failed(msg):
            self.update_btn.setEnabled(True)
            self.start_btn.setEnabled(True)
            self.status_label.setText("Stopped")
            QMessageBox.warning(self, "Update failed", msg)

        self._run_task(lambda: updater.install(update), self._restart, failed)

    def _restart(self, _result):
        self.status_label.setText("Update installed")
        if self._unsaved and self._confirm_discard():
            self._unsaved = False
        if not self._unsaved:
            updater.restart()

    def report_problem(self):
        """Send a note and the app's log to the developer."""
        note, ok = QInputDialog.getMultiLineText(
            self,
            "Report a problem",
            "What went wrong? This is sent with the app's log, never the "
            "transcript.",
        )
        if ok:
            extra = {
                "model": self.model_combo.currentText(),
                "live": str(self.live_check.isChecked()),
            }
            appreports.send_report(note, extra, on_done=self.report_finished.emit)

    def _on_report_finished(self, sent: bool):
        if sent:
            QMessageBox.information(self, "Report a problem", "Report sent. Thanks.")
        else:
            QMessageBox.warning(self, "Report a problem", "The report could not be sent.")

    def show_about(self):
        QMessageBox.about(
            self,
            APP_NAME,
            f"{APP_NAME} {__version__}\n\nhttps://github.com/{REPO}",
        )

    # ---- internal slots --------------------------------------------

    def _on_live_toggled(self, checked: bool):
        self._worker.live = checked
        if not checked:
            self._show_draft("")

    def _show_draft(self, text: str):
        """Replace the grey draft line at the end ("" removes it)."""
        bar = self.transcript.verticalScrollBar()
        following = bar.value() >= bar.maximum() - 4
        cursor = QTextCursor(self.transcript.document())
        if self._draft_pos is None:
            if not text:
                return
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._draft_pos = cursor.position()
        else:
            cursor.setPosition(self._draft_pos)
            cursor.movePosition(
                QTextCursor.MoveOperation.End,
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.removeSelectedText()

        if text:
            if self._draft_pos > 0:
                cursor.insertBlock()
            cursor.insertText(text, self._draft_format)
        else:
            self._draft_pos = None
        if following:
            bar.setValue(bar.maximum())

    def _final_text(self) -> str:
        """The transcript without the draft line."""
        if self._draft_pos is None:
            return self.transcript.toPlainText()
        cursor = QTextCursor(self.transcript.document())
        cursor.setPosition(self._draft_pos, QTextCursor.MoveMode.KeepAnchor)
        return cursor.selectedText().replace("\u2029", "\n")

    def _on_transcript_update(self, text: str):
        """Swap the draft for the final text; QTextEdit keeps following the end."""
        self._show_draft("")
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
        self._show_draft("")
        if not self._error_shown:
            self.status_label.setText("Stopped")
        if self._close_when_finished:
            self.close()

    def _confirm_discard(self) -> bool:
        answer = QMessageBox.question(
            self,
            "Unsaved transcript",
            "Quit without saving the transcript?",
        )
        return answer == QMessageBox.StandardButton.Yes

    def closeEvent(self, event):
        """Ask about unsaved text, and let the worker stop before closing."""
        if self._unsaved and not self._close_when_finished:
            if not self._confirm_discard():
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
    app.setDesktopFileName(APP_ID)
    window = TranscriberApp()
    window.show()
    window.start_update_check()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_gui()
