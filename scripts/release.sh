#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"
BOT_SERVICE_NAME=voidbot
WEBHOOK_SERVICE_NAME=voidbot-webhook

# Функция для вывода в лог
log() {
  echo "[INFO] $1"
}

# Шаг 1: проверка git-состояния
git_status() {
  git_status_output=$(git status --short)
  if [[ -n "$git_status_output" ]]; then
    echo "Git tree is not clean. Please commit your changes or reset."
    exit 1
  fi
  log "Git status: Clean"
}

# Шаг 2: git pull
git_pull() {
  log "Pulling latest changes from remote..."
  git pull
  log "Git pull complete."
}

# Шаг 3: alembic upgrade
alembic_upgrade() {
  log "Running alembic migrations..."
  alembic upgrade head
  log "Alembic upgrade complete."
}

# Шаг 4: перезапуск бота
restart_bot_service() {
  log "Restarting bot service..."
  sudo systemctl restart "$BOT_SERVICE_NAME"
  log "Bot service restarted."
}

# Шаг 5: перезапуск webhook сервиса
restart_webhook_service() {
  log "Restarting webhook service..."
  sudo systemctl restart "$WEBHOOK_SERVICE_NAME"
  log "Webhook service restarted."
}

# Шаг 6: статус бота
status_bot_service() {
  log "Checking bot service status..."
  systemctl status "$BOT_SERVICE_NAME"
}

# Шаг 7: статус webhook сервиса
status_webhook_service() {
  log "Checking webhook service status..."
  systemctl status "$WEBHOOK_SERVICE_NAME"
}

# Шаг 8: проверка текущей версии alembic
check_alembic_version() {
  log "Checking alembic version..."
  alembic current
}

# Шаг 9: последние логи бота
recent_bot_logs() {
  log "Fetching recent bot logs..."
  journalctl -u "$BOT_SERVICE_NAME" -n 10
}

# Шаг 10: последние логи webhook
recent_webhook_logs() {
  log "Fetching recent webhook logs..."
  journalctl -u "$WEBHOOK_SERVICE_NAME" -n 10
}

# Основной процесс
release() {
  log "== RELEASE START =="

  log "PROJECT_DIR=$PROJECT_DIR"
  log "ENV_FILE=$ENV_FILE"
  log "BOT_SERVICE_NAME=$BOT_SERVICE_NAME"
  log "WEBHOOK_SERVICE_NAME=$WEBHOOK_SERVICE_NAME"

  git_status
  git_pull
  alembic_upgrade
  restart_bot_service
  restart_webhook_service
  status_bot_service
  status_webhook_service
  check_alembic_version
  recent_bot_logs
  recent_webhook_logs

  log "== RELEASE DONE =="
}

# Условие для --dry-run
if [[ "$1" == "--dry-run" ]]; then
  log "Dry run mode: Skipping actual operations."
  exit 0
fi

# Запуск
release
