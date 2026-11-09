"""Updater safety checks: only this repository's addresses, the checksum, the download fallback.

    python3 -m pytest tests/test_updater.py      (with audio-transcriber installed)
"""

import pytest

from audio_transcriber import updater


def test_trusts_only_this_repository():
    assert updater._trusted("https://api.github.com/repos/ssjrocks/audio-transcriber/releases/assets/1")
    assert updater._trusted("https://github.com/ssjrocks/audio-transcriber/releases/download/v1/x.whl")
    assert not updater._trusted("https://github.com/someone/audio-transcriber/releases/download/v1/x.whl")
    assert not updater._trusted("https://example.com/ssjrocks/audio-transcriber/x.whl")
    assert updater.parse_version("v0.10.1") > updater.parse_version("0.9.9")


def test_refuses_a_wheel_with_the_wrong_checksum(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "installed_in_venv", lambda: True)
    monkeypatch.setattr(updater, "_download", lambda *a: b"not the real wheel")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    ran = []
    monkeypatch.setattr(updater.subprocess, "run", lambda *a, **k: ran.append(a))
    u = updater.Update("9.9.9", "https://api.github.com/repos/ssjrocks/audio-transcriber/releases/assets/1",
                       "audio_transcriber-9.9.9-py3-none-any.whl", "0" * 64)
    with pytest.raises(RuntimeError, match="checksum"):
        updater.install(u)
    assert not ran                                   # pip never ran


def test_falls_back_to_the_plain_link(monkeypatch):
    tried = []

    def get(url, accept=None, timeout=20):
        tried.append(url)
        if "api.github.com" in url:
            raise OSError("HTTP Error 504: Gateway Time-out")
        return b"data"

    monkeypatch.setattr(updater, "_get", get)
    data = updater._download("https://api.github.com/repos/ssjrocks/audio-transcriber/releases/assets/1",
                             "https://github.com/ssjrocks/audio-transcriber/releases/download/v1/x.json")
    assert data == b"data" and len(tried) == 2
