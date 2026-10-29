"""Audio Transcriber -- real-time system audio transcription."""

import shutil
import sys

from audio_transcriber.gui import run_gui


def _check_requirements() -> list[str]:
    """Verify all runtime requirements are available.

    Returns a list of error messages; empty list means everything is OK.
    """
    errors: list[str] = []

    # 1. Check audio backend
    has_pw_cat = shutil.which("pw-cat") is not None
    has_pacat = shutil.which("pacat") is not None
    has_pactl = shutil.which("pactl") is not None

    if not has_pw_cat and not has_pacat:
        errors.append(
            "No audio capture tool found.\n\n"
            "Install one of:\n"
            "  * PipeWire:  sudo apt install pipewire-utils\n"
            "  * PulseAudio: sudo apt install pulseaudio-utils"
        )

    # 2. Check faster-whisper import
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        errors.append(
            "faster-whisper is not installed.\n\n"
            "Install it:\n"
            "  uv pip install faster-whisper\n"
            "or\n"
            "  uv pip install faster-whisper[cpu]"
        )

    # 3. Check PyQt6 import
    try:
        import PyQt6  # noqa: F401
    except ImportError:
        errors.append(
            "PyQt6 is not installed.\n\n"
            "Install it:\n"
            "  uv pip install pyqt6"
        )

    return errors


def main():
    """Entry point: check requirements then launch the GUI."""
    errors = _check_requirements()

    if errors:
        print("\n" + "=" * 50, file=sys.stderr)
        print("Audio Transcriber -- missing requirements", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        for i, err in enumerate(errors, 1):
            print(f"\n{i}. {err}", file=sys.stderr)
        print("\n" + "=" * 50, file=sys.stderr)
        sys.exit(1)

    run_gui()


if __name__ == "__main__":
    main()
