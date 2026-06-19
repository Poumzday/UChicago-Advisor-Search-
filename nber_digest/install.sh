#!/usr/bin/env bash
# Set up the NBER digest: virtualenv, dependencies, API key, and a weekly
# launchd job. Re-runnable. macOS only (uses launchd + osascript).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
SCRAPE_LABEL="com.poum.nberdigest"
MENU_LABEL="com.poum.nberdigest.menubar"
SCRAPE_PLIST="$HOME/Library/LaunchAgents/$SCRAPE_LABEL.plist"
MENU_PLIST="$HOME/Library/LaunchAgents/$MENU_LABEL.plist"
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

mkdir -p "$HOME/Library/LaunchAgents"

# --- launchd job 1: weekly scrape, Mondays 08:00 --------------------------
echo "==> Writing weekly scrape job to $SCRAPE_PLIST (Mondays 08:00)"
cat > "$SCRAPE_PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$SCRAPE_LABEL</string>
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

# --- launchd job 2: always-on menu-bar app --------------------------------
echo "==> Writing menu-bar app job to $MENU_PLIST (runs at login, stays alive)"
cat > "$MENU_PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$MENU_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV/bin/python</string>
    <string>$HERE/menubar_app.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HERE/menubar.log</string>
  <key>StandardErrorPath</key><string>$HERE/menubar.log</string>
</dict>
</plist>
PLIST_EOF

# (Re)load both jobs into the GUI session domain (reliable for menu-bar apps)
GUI="gui/$(id -u)"
launchctl bootout "$GUI/$SCRAPE_LABEL" 2>/dev/null || true
launchctl bootstrap "$GUI" "$SCRAPE_PLIST"
launchctl bootout "$GUI/$MENU_LABEL" 2>/dev/null || true
launchctl bootstrap "$GUI" "$MENU_PLIST"

echo "==> Done. Scrape runs Mondays 08:00; the NBER menu-bar icon is now in your top-right bar."
echo "    Force a scrape now with:  $VENV/bin/python $HERE/nber_digest.py"
