#!/usr/bin/env bash
# Installs Audio Transcriber for the current user: a Python venv in
# ~/.local/share/audio-transcriber, and the desktop entry.
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
OLD_ICON="$DATA/icons/hicolor/128x128/apps/$APP_ID.png"

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -rf "$ROOT"
  rm -f "$DESKTOP" "$OLD_ICON"
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
  # Release files come through GitHub's API (its plain download links time out at busy times).
  read -r wheel_api wheel_name sha < <("$VENV/bin/python" - "$REPO" <<'EOF'
import json, sys, urllib.request
repo = sys.argv[1]
def get(url, accept):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "audio-transcriber-installer"})
    return urllib.request.urlopen(req, timeout=60).read()
rel = json.loads(get(f"https://api.github.com/repos/{repo}/releases/latest", "application/vnd.github+json"))
assets = {a["name"]: a["url"] for a in rel["assets"]}
info = json.loads(get(assets["audio-transcriber.json"], "application/octet-stream"))
print(assets[info["wheel"]], info["wheel"], info["sha256"])
EOF
)
  echo "Downloading $wheel_name"
  curl -fsSL -H "Accept: application/octet-stream" -o "$tmp/$wheel_name" "$wheel_api"
  echo "$sha  $tmp/$wheel_name" | sha256sum -c --quiet
  "$VENV/bin/pip" install -q "$tmp/$wheel_name"
fi

mkdir -p "$(dirname "$DESKTOP")"
rm -f "$OLD_ICON"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Version=1.1
Type=Application
Name=Audio Transcriber
Comment=Live transcript of any audio playing on this computer
Exec=$VENV/bin/python -m audio_transcriber
Icon=/usr/share/icons/Adwaita/scalable/devices/microphone.svg
Terminal=false
Categories=Audio;Utility;
EOF
update-desktop-database -q "$DATA/applications" 2>/dev/null || true
echo "Installed. Open Audio Transcriber from the app menu."
