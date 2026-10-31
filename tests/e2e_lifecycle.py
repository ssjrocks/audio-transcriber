"""Lifecycle checks with the real window, offscreen: no audio is played.

    QT_QPA_PLATFORM=offscreen .venv/bin/python tests/e2e_lifecycle.py [listen_seconds]

listen_seconds > 0 also listens to the real default output for that long and
prints whatever was playing.
"""

import faulthandler
import os
import subprocess
import sys
import tempfile
import time
import traceback

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from audio_transcriber.gui import TranscriberApp

faulthandler.dump_traceback_later(240, exit=True)
sys.excepthook = lambda *exc: (traceback.print_exception(*exc), os._exit(1))
listen = float(sys.argv[1]) if len(sys.argv) > 1 else 0

app = QApplication(sys.argv)
errors = []
QMessageBox.critical = lambda parent, title, text: errors.append(text)
window = TranscriberApp()


def spin(ms):
    loop = QEventLoop()
    QTimer.singleShot(int(ms), loop.quit)
    loop.exec()


def wait_until(condition, seconds=60):
    end = time.time() + seconds
    while not condition() and time.time() < end:
        spin(50)
    assert condition(), "timed out"


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name, flush=True)
    if not ok:
        os._exit(1)


# Stop pressed while the model is still loading
window.start_btn.click()
window.stop_btn.click()
wait_until(window._worker.isFinished)
spin(100)
check("stop during load ends cleanly", window.status_label.text() == "Stopped")
check("start re-enabled", window.start_btn.isEnabled())

# Start again, reach Listening, repeat twice
for i in range(2):
    window.start_btn.click()
    wait_until(lambda: window.status_label.text() == "Listening...")
    spin(1000)
    if i == 0 and listen:
        print(f"listening to the real output for {listen:.0f}s", flush=True)
        spin(listen * 1000)
    window.stop_btn.click()
    wait_until(lambda: window._worker.isFinished() and window.start_btn.isEnabled())
    check(f"start/stop round {i + 1}", window.status_label.text() == "Stopped")
if listen:
    print("heard:\n" + (window.transcript.toPlainText() or "(nothing)"), flush=True)

# Model choice is honoured
window.model_combo.setCurrentText("base")
window.start_btn.click()
wait_until(lambda: window.status_label.text() == "Listening...")
check("model switched", window._worker.transcriber.model_size == "base")
check("model locked while running", not window.model_combo.isEnabled())
window.stop_btn.click()
wait_until(lambda: window.start_btn.isEnabled())

# Save writes the transcript
window.transcript.setPlainText("[12:00:00] hello")
window._unsaved = True
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "t.txt")
    window._write_transcript(path)
    check("save", open(path).read() == "[12:00:00] hello\n")
check("save clears unsaved flag", not window._unsaved)

# Drafts are shown but never saved, and final text replaces them
window._show_draft("draft words")
check("draft shown", window.transcript.toPlainText().endswith("draft words"))
check("draft not in saved text", window._final_text() == "[12:00:00] hello")
window._show_draft("longer draft words")
window._on_transcript_update("final words")
lines = window.transcript.toPlainText().splitlines()
check("final replaces draft", len(lines) == 2 and lines[1].endswith("] final words"))
window.clear_transcript()
window._show_draft("draft on empty")
window._show_draft("")
check("draft removed", window.transcript.toPlainText() == "")
window._unsaved = False

# A dead pw-record is reported instead of hanging
window.start_btn.click()
wait_until(lambda: window.status_label.text() == "Listening...")
subprocess.run(["pkill", "-x", "pw-record"])
wait_until(lambda: errors, 15)
wait_until(lambda: window.start_btn.isEnabled(), 15)
check("capture failure shown", "pw-record exited" in errors[0])
check("error stays in status", window.status_label.text().startswith("Error"))

# Closing while running must not destroy a live QThread
window.show()
window.start_btn.click()
wait_until(lambda: window.status_label.text() == "Listening...")
window.close()
wait_until(window._worker.isFinished)
spin(200)
check("close while running", not window.isVisible())
print("ALL PASS")
