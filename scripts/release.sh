#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"
VENV_ACTIVATE="$PROJECT_DIR/venv/bin/activate"
SERVICE_NAME="${SERVICE_NAME:-telegram-bot}"

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
echo "SERVICE_NAME=$SERVICE_NAME"
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

echo "== STEP 4: restart service =="
sudo systemctl restart "$SERVICE_NAME"
echo

echo "== STEP 5: service status =="
systemctl --no-pager --full status "$SERVICE_NAME" | sed -n '1,20p'
echo

echo "== STEP 6: current revision =="
alembic current
echo

echo "== STEP 7: recent logs =="
journalctl -u "$SERVICE_NAME" -n 50 --no-pager
echo

echo "== RELEASE DONE =="
