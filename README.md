# Audio Transcriber

An Ubuntu desktop app that writes a live transcript of whatever is playing on
the computer: videos, calls, podcasts. It records the system output, not a
microphone, and everything runs locally with
[faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## Install

Needs Ubuntu with PipeWire and [uv](https://docs.astral.sh/uv/).

```bash
curl -fsSL https://raw.githubusercontent.com/ssjrocks/audio-transcriber/master/scripts/install.sh | bash
```

Remove it again with `scripts/install.sh --uninstall`.

## Using it

Press **Start** and play something. With **Live** ticked, words appear in grey
while they are spoken and are replaced by the final text, with a timestamp,
when the speaker pauses. Untick it to see only the final text. **Stop** also
transcribes the words that were still in progress. **Save**, **Copy** and
**Clear** act on the whole transcript, and quitting with unsaved text asks first.

## Models

| Model | Notes |
|---|---|
| `base` | Fastest, least accurate |
| `small.en` | Default |
| `medium.en` | Most accurate, slowest |

The model is English only for now and runs on the CPU, so the GPU stays free for
the desktop and Ollama. A model that isn't in the Hugging Face cache downloads
the first time it's used.

## How it works

1. `audio_capture.py` runs `pw-record` with `stream.capture.sink=true`, which
   records the default output as 16 kHz mono. PipeWire is required.
2. `SpeechSegmenter` in `transcriber.py` uses Silero VAD to cut the stream at
   pauses, and drops music and silence.
3. `Transcriber` sends each phrase to Whisper from a worker thread (`gui.py`).

## Updates and problem reports

- **Updates**: the app checks this repository's latest release at most every 12
  hours and shows an update button. The download must come from github.com and
  match the SHA-256 published with the release.
- **Problem reports**: crashes, unexpected errors and **Help > Report a problem**
  send a report to the developer's server (`ssjrocks.com`). A report contains
  the app version, the error and its stack trace, the app's log file (start,
  stop, model choice and errors), the PC's manufacturer and model name, the
  OS/kernel/Python versions, a random install ID, and for "Report a problem" your
  note plus the selected model and whether Live was on. It never contains the
  transcript or any audio.

## Testing

`tests/e2e_gui.py` drives the real window offscreen with real capture and
Whisper, playing a speech file into a private silent sink.
`tests/e2e_lifecycle.py` covers Start, Stop, restart and failures:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/e2e_gui.py speech.wav
```

## Development

```bash
uv sync
uv run python -m audio_transcriber
```

Bump `version` in `pyproject.toml`, commit, then publish with
`scripts/release.sh NOTES.md`.
