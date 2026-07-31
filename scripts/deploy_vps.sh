#!/usr/bin/env bash
# Deploy Mr. Baton to VPS in a SEPARATE folder from abnormal_signal_bot.
# Host pattern from abnormal_signal_bot docs: root@89.127.196.166
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${DEPLOY_HOST:-root@89.127.196.166}"
REMOTE_DIR="${DEPLOY_DIR:-/root/misterbaton_bot}"
UNIT_NAME="misterbaton"

echo "==> Target: $HOST:$REMOTE_DIR (unit: $UNIT_NAME)"

if [[ ! -f "$ROOT/.env" ]]; then
  echo "Local .env missing — abort"
  exit 1
fi

echo "==> Ensure remote dir"
ssh -o StrictHostKeyChecking=accept-new "$HOST" "mkdir -p '$REMOTE_DIR'"

echo "==> Rsync code (no .venv / local data / logs)"
rsync -az --delete \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude 'data/' \
  --exclude 'logs/' \
  --exclude '__pycache__/' \
  --exclude '.git/' \
  --exclude '.DS_Store' \
  --exclude '.env' \
  --exclude '.idea/' \
  --exclude '.pytest_cache/' \
  --exclude '.github/' \
  "$ROOT/" "$HOST:$REMOTE_DIR/"

echo "==> Upload .env"
scp -q "$ROOT/.env" "$HOST:$REMOTE_DIR/.env"

echo "==> Python venv + deps on server"
ssh "$HOST" bash -s <<EOF
set -euo pipefail
cd '$REMOTE_DIR'
mkdir -p data logs
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
EOF

echo "==> Install systemd unit"
scp -q "$ROOT/deploy/systemd/misterbaton.service" "$HOST:/etc/systemd/system/${UNIT_NAME}.service"
ssh "$HOST" "systemctl daemon-reload && systemctl enable --now ${UNIT_NAME}.service && systemctl restart ${UNIT_NAME}.service && sleep 2 && systemctl is-active ${UNIT_NAME}.service && systemctl status ${UNIT_NAME}.service --no-pager -l | head -25"

echo "==> Done. Journal: ssh $HOST 'journalctl -u $UNIT_NAME -n 50 -f'"
