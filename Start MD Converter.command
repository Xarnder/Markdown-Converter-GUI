#!/bin/bash
# Double-click this file in Finder to install dependencies and launch MD Converter.
# Important: double-click in Finder (not inside Cursor/VS Code).

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR" || exit 1

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

PORT=8765
URL="http://127.0.0.1:${PORT}"
LOG_FILE="$APP_DIR/launcher.log"
EXIT_CODE=0

pause_before_close() {
  echo ""
  echo "This window will stay open so you can read any errors."
  read -r -p "Press Enter to close..." _
}

log() {
  echo "$1" | tee -a "$LOG_FILE"
}

cleanup() {
  if [ "$EXIT_CODE" -ne 0 ]; then
    pause_before_close
  fi
}
trap cleanup EXIT

: > "$LOG_FILE"

log "========================================"
log "  MD Converter"
log "========================================"
log ""
log "Started: $(date)"
log "Folder: $APP_DIR"
log ""

if ! command -v python3 >/dev/null 2>&1; then
  log "Error: python3 was not found."
  log "Install Python from https://www.python.org/downloads/"
  EXIT_CODE=1
  exit 1
fi

PYTHON_BIN="$(command -v python3)"
log "Using Python: $PYTHON_BIN"
log ""

log "Installing dependencies..."
if ! "$PYTHON_BIN" -m pip install -r "$APP_DIR/requirements.txt" 2>&1 | tee -a "$LOG_FILE"; then
  log ""
  log "Error: Failed to install dependencies."
  log "Try running this command manually in Terminal:"
  log "  cd \"$APP_DIR\" && python3 -m pip install -r requirements.txt"
  EXIT_CODE=1
  exit 1
fi

if ! command -v pandoc >/dev/null 2>&1; then
  log ""
  log "Tip: For best PDF/DOCX quality and proper table grid lines, install Pandoc:"
  log "  brew install pandoc"
  log "For PDF export, also install one PDF engine:"
  log "  brew install --cask basictex"
  log "  or: brew install wkhtmltopdf"
fi

log ""
log "Starting MD Converter..."

# If the app is already running, just open the browser.
if "$PYTHON_BIN" -c "import urllib.request; urllib.request.urlopen('$URL', timeout=1)" >/dev/null 2>&1; then
  log "MD Converter is already running at $URL"
  open "$URL"
  log "Opened the UI in your browser."
  log "Leave the original Terminal window running, or stop it with Ctrl+C there."
  pause_before_close
  exit 0
fi

log "The UI should open in your browser automatically."
log "If it does not, open: $URL"
log "Keep this Terminal window open while using the app."
log "Press Ctrl+C here to stop the server."
log ""

if ! "$PYTHON_BIN" "$APP_DIR/MD-Converter.py" --port "$PORT" 2>&1 | tee -a "$LOG_FILE"; then
  log ""
  log "Error: MD Converter stopped unexpectedly."
  log "Check launcher.log in this folder for details."
  EXIT_CODE=1
  exit 1
fi
