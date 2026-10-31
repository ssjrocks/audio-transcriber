#!/usr/bin/env bash
# Installs Audio Transcriber for the current user: a Python venv in
# ~/.local/share/audio-transcriber, the desktop entry and the icon.
#
#   From a checkout:  scripts/install.sh            installs that checkout
#   Anywhere:         curl -fsSL https://raw.githubusercontent.com/ssjrocks/audio-transcriber/master/scripts/install.sh | bash
#   Remove:           scripts/install.sh --uninstall
set -euo pipefail

APP_ID=io.github.ssjrocks.AudioTranscriber
REPO=ssjrocks/audio-transcriber
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
ROOT="$DATA/audio-transcriber"
VENV="$ROOT/venv"
DESKTOP="$DATA/applications/$APP_ID.desktop"
ICON="$DATA/icons/hicolor/128x128/apps/$APP_ID.png"

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -rf "$ROOT"
  rm -f "$DESKTOP" "$ICON"
  update-desktop-database -q "$DATA/applications" 2>/dev/null || true
  echo "Audio Transcriber removed."
  exit 0
fi

command -v pw-record >/dev/null || { echo "pw-record not found: sudo apt install pipewire-bin" >&2; exit 1; }
command -v uv >/dev/null || { echo "uv not found: see https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }

# Install from this checkout when run from one, otherwise from the latest release.
src=""
if [[ -f "${BASH_SOURCE[0]:-}" ]]; then
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  [[ -f "$here/../pyproject.toml" ]] && src="$(cd "$here/.." && pwd)"
fi

uv venv -q --clear --seed --python 3.12 "$VENV"
touch "$VENV/audio-transcriber-venv"   # tells the in-app updater it may update this venv

if [[ -n "$src" ]]; then
  echo "Installing from $src"
  "$VENV/bin/pip" install -q "$src"
else
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  read -r wheel_url sha < <("$VENV/bin/python" - "$REPO" <<'EOF'
import json, sys, urllib.request
repo = sys.argv[1]
rel = json.load(urllib.request.urlopen(f"https://api.github.com/repos/{repo}/releases/latest"))
assets = {a["name"]: a["browser_download_url"] for a in rel["assets"]}
info = json.load(urllib.request.urlopen(assets["audio-transcriber.json"]))
print(assets[info["wheel"]], info["sha256"])
EOF
)
  echo "Downloading $wheel_url"
  curl -fsSL -o "$tmp/$(basename "$wheel_url")" "$wheel_url"
  echo "$sha  $tmp/$(basename "$wheel_url")" | sha256sum -c --quiet
  "$VENV/bin/pip" install -q "$tmp/$(basename "$wheel_url")"
fi

mkdir -p "$(dirname "$DESKTOP")" "$(dirname "$ICON")"
"$VENV/bin/python" -c 'import audio_transcriber, pathlib, shutil, sys; shutil.copy(pathlib.Path(audio_transcriber.__file__).with_name("icon.png"), sys.argv[1])' "$ICON"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Version=1.1
Type=Application
Name=Audio Transcriber
Comment=Live transcript of any audio playing on this computer
Exec=$VENV/bin/python -m audio_transcriber
Icon=$APP_ID
Terminal=false
Categories=Audio;Utility;
EOF
update-desktop-database -q "$DATA/applications" 2>/dev/null || true
echo "Installed. Open Audio Transcriber from the app menu."
