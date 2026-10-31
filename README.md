# Audio Transcriber

An Ubuntu desktop app that writes a live transcript of whatever is playing on
the computer: videos, calls, podcasts. It records the system output, not a
microphone, and everything runs locally with
[faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## Running it

Use the Audio Transcriber icon, or:

```bash
uv sync
uv run python -m audio_transcriber
```

Press **Start**, play something, and each phrase appears with a timestamp when
the speaker pauses. **Stop** also transcribes the words that were still in
progress. **Save**, **Copy** and **Clear** act on the whole transcript, and
quitting with unsaved text asks first.

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

## Testing

`tests/e2e_gui.py` drives the real window offscreen with real capture and
Whisper. It plays a speech file into a private silent sink:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/e2e_gui.py speech.wav
```
