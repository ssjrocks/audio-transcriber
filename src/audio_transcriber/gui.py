"""GUI module — PyQt6-based interface for the audio transcriber.

Falls back to tkinter if PyQt6 is unavailable.
"""

import sys
import threading
import time


def _run_qt_gui():
    """Launch the PyQt6 GUI application."""
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

    # ------------------------------------------------------------------
    # Fake transcription worker
    # ------------------------------------------------------------------
    class _FakeWorker(QThread):
        """Emits a fake transcript line every 2 seconds."""

        text_updated = pyqtSignal(str)

        def __init__(self):
            super().__init__()
            self._running = False

        def run(self):
            while self._running:
                self.msleep(2000)  # 2 s
                self.text_updated.emit("Hello world (test)")

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
            self._worker = _FakeWorker()
            self._worker.text_updated.connect(self._on_text_update)
            self._running = False

        # ---- public API ------------------------------------------------

        def start_capture(self):
            """Start the capture / transcription loop."""
            self._running = True
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.status_label.setText("Listening...")
            self._worker.start()

        def stop_capture(self):
            """Stop the capture / transcription loop."""
            self._running = False
            self._worker.wait(timeout=3)
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.status_label.setText("Stopped")

        # ---- internal slots --------------------------------------------

        def _on_text_update(self, text: str):
            """Append received text and auto-scroll."""
            self.transcript.append(text)
            self.status_label.setText("Transcribing...")

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = TranscriberApp()
    window.show()
    sys.exit(app.exec())


def _run_tkinter_gui():
    """Fallback tkinter GUI when PyQt6 is not available."""
    import tkinter as tk
    from tkinter import font as tkfont

    class TranscriberApp(tk.Frame):
        def __init__(self, root):
            super().__init__(root)
            self.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            self._running = False
            self._worker_thread = None

            monospaced = tkfont.Font(family="Monospace", size=12)
            label_font = tkfont.Font(family="Monospace", size=10)

            # Status
            self.status_label = tk.Label(self, text="Stopped", font=label_font)
            self.status_label.pack(fill=tk.X)

            # Transcript
            self.transcript = tk.Text(self, font=monospaced, state=tk.DISABLED)
            self.transcript.pack(fill=tk.BOTH, expand=True)
            self.transcript.configure(state=tk.DISABLED)

            # Toolbar
            toolbar = tk.Frame(self)
            toolbar.pack(fill=tk.X, pady=(10, 0))

            tk.Label(toolbar, text="Model:", font=label_font).pack(side=tk.LEFT)
            self.model_var = tk.StringVar(value="base")
            model_combo = tk.OptionMenu(toolbar, self.model_var, "tiny", "base", "small")
            model_combo.config(font=label_font)
            model_combo.pack(side=tk.LEFT, padx=(5, 5))

            tk.Label(toolbar).pack(side=tk.LEFT, expand=True)

            start_btn = tk.Button(
                toolbar, text="Start", width=10,
                bg="#2ecc71", fg="white", font=label_font,
                command=self.start_capture,
            )
            start_btn.pack(side=tk.LEFT, padx=5)

            stop_btn = tk.Button(
                toolbar, text="Stop", width=10,
                bg="#e74c3c", fg="white", font=label_font,
                command=self.stop_capture, state=tk.DISABLED,
            )
            stop_btn.pack(side=tk.LEFT, padx=5)
            self._stop_btn_ref = stop_btn

        def start_capture(self):
            self._running = True
            self.status_label.config(text="Listening...")
            self._worker_thread = threading.Thread(
                target=self._fake_loop, daemon=True
            )
            self._worker_thread.start()

        def stop_capture(self):
            self._running = False
            self.status_label.config(text="Stopped")

        def _fake_loop(self):
            while self._running:
                time.sleep(2)
                if not self._running:
                    break
                self.transcript.configure(state=tk.NORMAL)
                self.transcript.insert(tk.END, "Hello world (test)\n")
                self.transcript.configure(state=tk.DISABLED)
                # auto-scroll
                self.transcript.see(tk.END)
                self.status_label.config(text="Transcribing...")

    root = tk.Tk()
    root.title("Audio Transcriber")
    root.geometry("800x600")
    TranscriberApp(root)
    root.mainloop()


# ----------------------------------------------------------------------
# Dispatcher — try PyQt6 first, fall back to tkinter
# ----------------------------------------------------------------------
def run_gui():
    """Launch the GUI (PyQt6 preferred, tkinter fallback)."""
    try:
        _run_qt_gui()
    except (ImportError, ModuleNotFoundError):
        _run_tkinter_gui()


if __name__ == "__main__":
    run_gui()
