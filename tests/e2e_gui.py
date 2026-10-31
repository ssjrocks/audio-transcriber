"""End-to-end test: real GUI, real pw-record, real Whisper, private null sink.

Creates a silent PipeWire sink, plays a speech file into it, drives the
Start/Stop buttons offscreen, and prints what the app transcribed. Nothing is
audible and the system's default output isn't touched.

    QT_QPA_PLATFORM=offscreen .venv/bin/python tests/e2e_gui.py speech.wav [model]
"""

import faulthandler
import subprocess
import sys
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from audio_transcriber.gui import TranscriberApp

SINK = "audio_transcriber_test_sink"

faulthandler.dump_traceback_later(180, exit=True)
wav = sys.argv[1]
model = sys.argv[2] if len(sys.argv) > 2 else "small.en"

sink = subprocess.Popen([
    "pw-cli", "-m", "create-node", "adapter",
    "factory.name=support.null-audio-sink",
    f"node.name={SINK}", "media.class=Audio/Sink",
    "object.linger=false", "audio.position=[FL FR]",
], stdout=subprocess.DEVNULL)
time.sleep(1)

app = QApplication(sys.argv)
window = TranscriberApp()
window.model_combo.setCurrentText(model)
window._worker.capture_target = SINK
statuses = []
window._worker.status_changed.connect(statuses.append)
window._worker.draft_ready.connect(
    lambda text: print(f"draft {time.time() - started:5.1f}s: {text}", flush=True)
)
window._worker.transcript_ready.connect(
    lambda text: print(f"final {time.time() - started:5.1f}s: {text}", flush=True)
)
player = None
started = time.time()


def poll():
    global player
    status = window.status_label.text()
    if player is None and status == "Listening...":
        player = subprocess.Popen(["pw-play", "--target", SINK, wav])
    elif player is not None and player.poll() is not None:
        timer.stop()
        print(f"playback done after {time.time() - started:.1f}s", flush=True)
        QTimer.singleShot(1500, press_stop)


def press_stop():
    window.stop_btn.click()


def finished():
    print("statuses:", list(dict.fromkeys(statuses)))
    print("final status:", window.status_label.text())
    print("start enabled:", window.start_btn.isEnabled())
    print("transcript:\n" + window.transcript.toPlainText())
    window._unsaved = False
    app.quit()


window._worker.finished.connect(finished)
timer = QTimer(interval=100, timeout=poll)
timer.start()
window.start_btn.click()
app.exec()
sink.terminate()
