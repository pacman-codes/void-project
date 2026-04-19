#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"
VENV_ACTIVATE="$PROJECT_DIR/venv/bin/activate"

BOT_SERVICE_NAME="${BOT_SERVICE_NAME:-voidbot}"
WEBHOOK_SERVICE_NAME="${WEBHOOK_SERVICE_NAME:-voidbot-webhook}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: env file not found: $ENV_FILE"
  echo "Tip: export ENV_FILE=/path/to/.env before running, if needed."
  exit 1
fi

if [[ ! -f "$VENV_ACTIVATE" ]]; then
  echo "ERROR: venv activate script not found at $VENV_ACTIVATE"
  exit 1
fi

cd "$PROJECT_DIR"
source "$VENV_ACTIVATE"
export $(grep -v '^#' "$ENV_FILE" | xargs)

echo "== RELEASE START =="
echo "PROJECT_DIR=$PROJECT_DIR"
echo "ENV_FILE=$ENV_FILE"
echo "BOT_SERVICE_NAME=$BOT_SERVICE_NAME"
echo "WEBHOOK_SERVICE_NAME=$WEBHOOK_SERVICE_NAME"
echo

echo "== STEP 1: git status =="
git status --short
echo

echo "== STEP 2: git pull =="
git pull
echo

echo "== STEP 3: alembic upgrade head =="
alembic upgrade head
echo

echo "== STEP 4: restart bot service =="
sudo systemctl restart "$BOT_SERVICE_NAME"
echo

echo "== STEP 5: restart webhook service =="
sudo systemctl restart "$WEBHOOK_SERVICE_NAME"
echo

echo "== STEP 6: bot service status =="
systemctl --no-pager --full status "$BOT_SERVICE_NAME" | sed -n '1,20p'
echo

echo "== STEP 7: webhook service status =="
systemctl --no-pager --full status "$WEBHOOK_SERVICE_NAME" | sed -n '1,20p'
echo

echo "== STEP 8: current revision =="
alembic current
echo

echo "== STEP 9: recent bot logs =="
journalctl -u "$BOT_SERVICE_NAME" -n 30 --no-pager
echo

echo "== STEP 10: recent webhook logs =="
journalctl -u "$WEBHOOK_SERVICE_NAME" -n 30 --no-pager
echo

echo "== RELEASE DONE =="
