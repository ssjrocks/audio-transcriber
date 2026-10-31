"""Regenerate the README screenshots from a real run of the app.

Plays a speech file twice into a private silent PipeWire sink and captures the
window, so nothing is audible. Problem reports stay off (main() isn't used).

    .venv/bin/python scripts/screenshots.py speech.wav
"""

import faulthandler
import subprocess
import sys
import time
import traceback
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from audio_transcriber.gui import TranscriberApp

SINK = "audio_transcriber_shots_sink"
OUT = Path(__file__).parent.parent / "docs/screenshots"
PLAYS = 2
PAUSE = 2.0

faulthandler.dump_traceback_later(120, exit=True)
sys.excepthook = traceback.print_exception
wav = sys.argv[1]
OUT.mkdir(parents=True, exist_ok=True)

sink = subprocess.Popen([
    "pw-cli", "-m", "create-node", "adapter",
    "factory.name=support.null-audio-sink",
    f"node.name={SINK}", "media.class=Audio/Sink",
    "object.linger=false", "audio.position=[FL FR]",
], stdout=subprocess.DEVNULL)
time.sleep(1)

app = QApplication(sys.argv)
app.setStyle("Fusion")
window = TranscriberApp()
window.resize(800, 420)
window._worker.capture_target = SINK
window.show()
player = None
next_play = None
plays = 0
finals = 0
live_done = False


def on_final(_text):
    global finals
    finals += 1


def on_draft(text):
    """Capture once a finished line sits above a draft of several words."""
    global live_done
    if not live_done and finals >= 2 and len(text.split()) >= 6:
        live_done = True
        # Queued after the window's own slot, so the draft is already drawn.
        QTimer.singleShot(50, lambda: window.grab().save(str(OUT / "live.png")))


def poll():
    global player, plays, next_play
    if window.status_label.text() != "Listening...":
        return
    if player is None or player.poll() is not None:
        if plays == PLAYS:
            timer.stop()
            QTimer.singleShot(1500, window.stop_btn.click)
        elif next_play is None:
            next_play = time.time() + PAUSE
        elif time.time() >= next_play:
            next_play = None
            plays += 1
            player = subprocess.Popen(["pw-play", "--target", SINK, wav])


def finished():
    QTimer.singleShot(100, save_final)


def save_final():
    window.grab().save(str(OUT / "transcript.png"))
    print("live captured:", live_done)
    print(window.transcript.toPlainText())
    window._unsaved = False
    app.quit()


window._worker.transcript_ready.connect(on_final)
window._worker.draft_ready.connect(on_draft)
window._worker.finished.connect(finished)
timer = QTimer(interval=100, timeout=poll)
timer.start()
window.start_btn.click()
app.exec()
sink.terminate()
