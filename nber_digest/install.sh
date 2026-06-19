#!/usr/bin/env bash
# Set up the NBER digest: virtualenv, dependencies, API key, and a weekly
# launchd job. Re-runnable. macOS only (uses launchd + osascript).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
LABEL="com.poum.nberdigest"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
VENV="$HERE/.venv"

echo "==> Creating virtualenv at $VENV"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$HERE/requirements.txt"

# --- API key -> gitignored .env -------------------------------------------
if [ ! -f "$HERE/.env" ]; then
  printf "Enter your Anthropic API key (input hidden): "
  read -rs API_KEY
  echo
  echo "ANTHROPIC_API_KEY=$API_KEY" > "$HERE/.env"
  chmod 600 "$HERE/.env"
  echo "==> Saved key to $HERE/.env (gitignored)"
else
  echo "==> $HERE/.env already exists; leaving it untouched"
fi

# --- launchd plist: every Monday 08:00 ------------------------------------
echo "==> Writing launchd job to $PLIST (Mondays 08:00)"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV/bin/python</string>
    <string>$HERE/nber_digest.py</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key><integer>1</integer>
    <key>Hour</key><integer>8</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>$HERE/last_run.log</string>
  <key>StandardErrorPath</key><string>$HERE/last_run.log</string>
</dict>
</plist>
PLIST_EOF

# Reload the job
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "==> Done. The digest runs Mondays at 08:00."
echo "    Test it now with:  $VENV/bin/python $HERE/nber_digest.py"
