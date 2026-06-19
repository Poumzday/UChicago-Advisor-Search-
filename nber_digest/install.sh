#!/usr/bin/env bash
# Set up the NBER digest + weather menu-bar apps and the weekly scrape.
#
# macOS blocks background (launchd) apps from reading ~/Documents, so the runtime
# is deployed to ~/Library/Application Support/NBERDigest (not protected) while the
# git repo stays in Documents as the source. Re-run this after editing source files
# (e.g. profile.md) to redeploy. Re-runnable.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RT="$HOME/Library/Application Support/NBERDigest"
LA="$HOME/Library/LaunchAgents"
PYTHON="${PYTHON:-python3}"
PY="$RT/.venv/bin/python"
GUI="gui/$(id -u)"

echo "==> Deploying runtime to: $RT"
mkdir -p "$RT/pages" "$LA"
cp "$SRC"/menubar_app.py "$SRC"/weather_app.py \
   "$SRC"/nber_digest.py "$SRC"/profile.md "$SRC"/requirements.txt "$RT"/
# Seed the digest only if the runtime doesn't have one yet (preserve read state).
[ -f "$RT/digest.json" ] || { [ -f "$SRC/digest.json" ] && cp "$SRC/digest.json" "$RT"/ || true; }

echo "==> Building virtualenv + dependencies"
"$PYTHON" -m venv "$RT/.venv"
"$RT/.venv/bin/pip" install --quiet --upgrade pip
"$RT/.venv/bin/pip" install --quiet -r "$RT/requirements.txt"

# --- API key -> gitignored .env in the runtime -----------------------------
if [ ! -f "$RT/.env" ]; then
  printf "Enter your Anthropic API key (input hidden): "
  read -rs API_KEY; echo
  echo "ANTHROPIC_API_KEY=$API_KEY" > "$RT/.env"; chmod 600 "$RT/.env"
  echo "==> Saved key to $RT/.env"
fi

agent_plist () {  # $1=label $2=script ; reads $3.. as extra <dict> entries
  local label="$1" script="$2"; shift 2
  cat > "$LA/$label.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$RT/$script</string>
  </array>
$*
  <key>StandardOutPath</key><string>$RT/$label.log</string>
  <key>StandardErrorPath</key><string>$RT/$label.log</string>
</dict>
</plist>
EOF
}

KEEPALIVE='  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>'
WEEKLY='  <key>StartCalendarInterval</key>
  <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>'

agent_plist com.poum.nberdigest.menubar menubar_app.py "$KEEPALIVE"
agent_plist com.poum.nberdigest.weather  weather_app.py "$KEEPALIVE"
agent_plist com.poum.nberdigest          nber_digest.py "$WEEKLY"

for L in com.poum.nberdigest.menubar com.poum.nberdigest.weather com.poum.nberdigest; do
  launchctl bootout "$GUI/$L" 2>/dev/null || true
  launchctl bootstrap "$GUI" "$LA/$L.plist"
done

echo "==> Done."
echo "    Menu bar: NBER digest (red + hazard when unread) and a weather tab."
echo "    Weekly NBER scrape runs Mondays 08:00."
echo "    Force a scrape now:  $PY $RT/nber_digest.py"
