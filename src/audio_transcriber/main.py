"""Audio Transcriber -- real-time system audio transcription."""

import traceback
import sys

from audio_transcriber.gui import run_gui


def _log_exception(exc_type, exc, tb) -> None:
    # Without a hook, PyQt6 aborts the process on an exception in a slot.
    traceback.print_exception(exc_type, exc, tb)


def main():
    """Entry point: launch the GUI."""
    sys.excepthook = _log_exception
    run_gui()


if __name__ == "__main__":
    main()
