#!/bin/bash
# Sets up the Strategic Intelligence Digest as a macOS launchd job (7am daily).

set -e
cd "$(dirname "$0")"
APP_DIR="$(pwd)"
LABEL="com.strategicdigest.app"
AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST="$AGENTS_DIR/$LABEL.plist"

# Create venv if needed
if [ ! -f "$APP_DIR/.venv/bin/python" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$APP_DIR/.venv"
    "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
    echo "✓  Dependencies installed"
fi

VENV_PYTHON="$APP_DIR/.venv/bin/python"

# Check .env exists
if [ ! -f "$APP_DIR/.env" ]; then
    echo ""
    echo "  ⚠️  No .env file found. Copy .env.example → .env and fill in your keys."
    echo "      Then re-run this script."
    echo ""
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo "  Created .env from template. Edit it now:"
    echo "  open $APP_DIR/.env"
    exit 1
fi

mkdir -p "$AGENTS_DIR"

cat > "$PLIST" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV_PYTHON</string>
        <string>$APP_DIR/main.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$APP_DIR/digest.log</string>
    <key>StandardErrorPath</key>
    <string>$APP_DIR/digest_error.log</string>
    <key>WorkingDirectory</key>
    <string>$APP_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
PLIST_EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo ""
echo "✓  Strategic Digest installed. Runs every day at 7:00 AM."
echo ""
echo "   Test now:   $VENV_PYTHON $APP_DIR/main.py"
echo "   Logs:       $APP_DIR/digest.log / digest_error.log"
echo "   To stop:    launchctl unload $PLIST"
