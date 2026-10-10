#!/bin/zsh
set -e

APP_PATH="/Applications/JARVIS Desktop Pet.app"
AGENT_DIR="$HOME/Library/LaunchAgents"
AGENT_PATH="$AGENT_DIR/com.jarvis.desktop-pet.plist"
DOMAIN="gui/$(id -u)"

if [[ ! -d "$APP_PATH" ]]; then
  print "找不到应用：$APP_PATH"
  exit 1
fi

/bin/mkdir -p "$AGENT_DIR"
/bin/chmod 700 "$AGENT_DIR"
/bin/launchctl bootout "$DOMAIN" "$AGENT_PATH" 2>/dev/null || true
/bin/cat > "$AGENT_PATH" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.jarvis.desktop-pet</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>-a</string>
    <string>/Applications/JARVIS Desktop Pet.app</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
PLIST
/bin/chmod 600 "$AGENT_PATH"
/usr/bin/plutil -lint "$AGENT_PATH"
/bin/launchctl bootstrap "$DOMAIN" "$AGENT_PATH"
/bin/launchctl kickstart -k "$DOMAIN/com.jarvis.desktop-pet"
print "JARVIS 已设为登录后自动启动，并已启动当前应用。"
