#!/usr/bin/env bash
# Быстрая настройка .env через терминал (интерактивно).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env.example ]]; then
  echo "Нет .env.example"
  exit 1
fi

cp -n .env.example .env 2>/dev/null || true

ask() {
  local key="$1" hint="$2"
  local cur
  cur="$(grep -E "^${key}=" .env 2>/dev/null | head -1 | cut -d= -f2- || true)"
  if [[ -n "${cur}" ]]; then
    read -r -p "${key} [${cur:0:8}…]: " val || true
  else
    read -r -p "${key} (${hint}): " val || true
  fi
  if [[ -n "${val:-}" ]]; then
    if grep -qE "^${key}=" .env; then
      # portable-ish in-place replace
      python3 - "$key" "$val" <<'PY'
import sys
from pathlib import Path
key, val = sys.argv[1], sys.argv[2]
p = Path(".env")
lines = p.read_text(encoding="utf-8").splitlines()
out = []
found = False
for line in lines:
    if line.startswith(key + "="):
        out.append(f"{key}={val}")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"{key}={val}")
p.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
    else
      echo "${key}=${val}" >> .env
    fi
  fi
}

echo "Токен бота: @BotFather → /newbot или /token"
ask TELEGRAM_BOT_TOKEN "123456:ABC..."

echo "Твой Telegram id: @userinfobot"
ask OWNER_USER_ID "числовой id"

echo "Текст-модель (например Z.ai GLM): https://z.ai"
ask OPENAI_API_KEY "ключ"
ask OPENAI_BASE_URL "https://api.z.ai/api/paas/v4"
ask OPENAI_MODEL "glm-4.5-flash"

echo "Vision (например OpenRouter + Gemini): https://openrouter.ai/keys"
ask OPENAI_VISION_API_KEY "ключ или Enter чтобы пропустить"
ask OPENAI_VISION_BASE_URL "https://openrouter.ai/api/v1"
ask OPENAI_VISION_MODEL "gemini-2.5-flash"

echo
echo "Готово. Дальше:"
echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
echo "  .venv/bin/python bot/main.py"
echo "или постоянно на macOS: bash scripts/install_launchagent.sh"
