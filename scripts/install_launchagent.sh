#!/usr/bin/env bash
# Install a macOS LaunchAgent so Mr. Baton restarts on login/crash.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_SRC="$ROOT/scripts/com.misterbaton.bot.plist.template"
PLIST_DST="$HOME/Library/LaunchAgents/com.misterbaton.bot.plist"
LABEL="com.misterbaton.bot"
UID_NUM="$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Нет .venv — сначала: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi
if [[ ! -f "$ROOT/.env" ]]; then
  echo "Нет .env — скопируй .env.example и заполни ключи (или запусти scripts/setup_env.sh)"
  exit 1
fi

# Stop manual bot processes to avoid duplicate long-poll
pkill -f "$ROOT/.venv/bin/python bot/main.py" 2>/dev/null || true
pkill -f "Python bot/main.py" 2>/dev/null || true
sleep 1

sed "s|REPO_ROOT_PLACEHOLDER|$ROOT|g" "$PLIST_SRC" > "$PLIST_DST"

# modern macOS: bootout + bootstrap (unload/load often fail)
launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${UID_NUM}" "$PLIST_DST"
launchctl enable "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
launchctl kickstart -k "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true

sleep 2
if launchctl print "gui/${UID_NUM}/${LABEL}" 2>/dev/null | head -5 >/dev/null; then
  echo "OK: $LABEL активен (KeepAlive)"
else
  echo "WARN: launchctl print не подтвердил сервис — проверь логи"
fi
echo "Логи: $ROOT/logs/bot.stdout.log"
echo "Стоп: launchctl bootout gui/${UID_NUM}/${LABEL}"
