#!/bin/zsh
set -e

AGENT_PATH="$HOME/Library/LaunchAgents/com.jarvis.desktop-pet.plist"
DOMAIN="gui/$(id -u)"

/bin/launchctl bootout "$DOMAIN" "$AGENT_PATH" 2>/dev/null || true
/bin/rm -f "$AGENT_PATH"
print "JARVIS 登录后自动启动已关闭。"
