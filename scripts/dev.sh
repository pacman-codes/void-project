#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env.dev"
VENV_ACTIVATE="$PROJECT_DIR/venv/bin/activate"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: .env.dev not found at $ENV_FILE"
  exit 1
fi

if [[ ! -f "$VENV_ACTIVATE" ]]; then
  echo "ERROR: venv activate script not found at $VENV_ACTIVATE"
  exit 1
fi

cd "$PROJECT_DIR"
source "$VENV_ACTIVATE"
export $(grep -v '^#' "$ENV_FILE" | xargs)

cmd="${1:-help}"

case "$cmd" in
  run)
    python main.py
    ;;
  migrate)
    alembic upgrade head
    ;;
  current)
    alembic current
    ;;
  history)
    alembic history
    ;;
  db)
    psql "$DATABASE_URL"
    ;;
  env)
    python - <<'PY'
import os

keys = [
    "BOT_TOKEN",
    "DATABASE_URL",
    "WEBHOOK_HOST",
    "WEBHOOK_PORT",
    "YOOKASSA_SHOP_ID",
    "PANEL_ORIGIN",
    "ENABLE_REFERRAL",
    "ENABLE_LAUNCH_OFFER",
]

for key in keys:
    value = os.getenv(key)
    if key == "BOT_TOKEN" and value:
        value = value[:10] + "..." + value[-5:]
    print(f"{key}={value}")
PY
    ;;
  tables)
    python - <<'PY'
import os
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    engine = create_async_engine(os.getenv("DATABASE_URL"))
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """))
        for row in result.fetchall():
            print(row[0])
    await engine.dispose()

asyncio.run(main())
PY
    ;;
  smoke)
    python - <<'PY'
import os
import asyncio
import importlib
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def check_db():
    engine = create_async_engine(os.getenv("DATABASE_URL"))
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT current_database(), current_user"))
        row = result.fetchone()
        print(f"DB: {row[0]} | USER: {row[1]}")

        result = await conn.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """))
        tables = [r[0] for r in result.fetchall()]
        print("TABLES:")
        for name in tables:
            print(f"  - {name}")

    await engine.dispose()

print("ENV OK")
print(f"DATABASE_URL={os.getenv('DATABASE_URL')}")
print(f"WEBHOOK_HOST={os.getenv('WEBHOOK_HOST')}")
print(f"WEBHOOK_PORT={os.getenv('WEBHOOK_PORT')}")
print(f"ENABLE_LAUNCH_OFFER={os.getenv('ENABLE_LAUNCH_OFFER')}")

asyncio.run(check_db())

modules = [
    "bot.handlers.start",
    "bot.handlers.subscription",
    "bot.handlers.account",
    "bot.keyboards.user",
]

print("IMPORTS:")
for module in modules:
    importlib.import_module(module)
    print(f"  OK: {module}")

print("SMOKE CHECK OK")
PY
    ;;
  user-show)
    if [[ -z "${2:-}" ]]; then
      echo "Usage: ./scripts/dev.sh user-show <telegram_id>"
      exit 1
    fi
    python scripts/dev_user.py show "$2"
    ;;
  user-free)
    if [[ -z "${2:-}" ]]; then
      echo "Usage: ./scripts/dev.sh user-free <telegram_id>"
      exit 1
    fi
    python scripts/dev_user.py free "$2"
    ;;
  user-paid)
    if [[ -z "${2:-}" ]]; then
      echo "Usage: ./scripts/dev.sh user-paid <telegram_id> [days]"
      exit 1
    fi
    python scripts/dev_user.py paid "$2" "${3:-30}"
    ;;
  user-reset)
    if [[ -z "${2:-}" ]]; then
      echo "Usage: ./scripts/dev.sh user-reset <telegram_id>"
      exit 1
    fi
    python scripts/dev_user.py reset "$2"
    ;;
  user-key-show)
    if [[ -z "${2:-}" ]]; then
      echo "Usage: ./scripts/dev.sh user-key-show <telegram_id>"
      exit 1
    fi
    python scripts/dev_user.py key-show "$2"
    ;;
  user-key-create)
    if [[ -z "${2:-}" ]]; then
      echo "Usage: ./scripts/dev.sh user-key-create <telegram_id> [device_number]"
      exit 1
    fi
    python scripts/dev_user.py key-create "$2" "${3:-1}"
    ;;
  user-key-clear)
    if [[ -z "${2:-}" ]]; then
      echo "Usage: ./scripts/dev.sh user-key-clear <telegram_id>"
      exit 1
    fi
    python scripts/dev_user.py key-clear "$2"
    ;;
  logs)
    if [[ -n "${2:-}" ]]; then
      journalctl -u "$2" -f
    else
      echo "Usage: ./scripts/dev.sh logs <service_name>"
      echo "Example: ./scripts/dev.sh logs voidbot-dev"
      exit 1
    fi
    ;;
  help|*)
    echo "Usage: ./scripts/dev.sh <command>"
    echo
    echo "Commands:"
    echo "  run                    - run dev bot"
    echo "  migrate                - apply alembic migrations"
    echo "  current                - show current alembic revision"
    echo "  history                - show alembic history"
    echo "  db                     - open psql using DATABASE_URL from .env.dev"
    echo "  env                    - print important env values"
    echo "  tables                 - list public tables in current DB"
    echo "  smoke                  - quick smoke-check for env/db/imports"
    echo "  user-show ID           - show user and vpn_accesses"
    echo "  user-free ID           - set user to free and clear vpn_accesses"
    echo "  user-paid ID [N]       - set user to paid for N days (default 30)"
    echo "  user-reset ID          - delete user and vpn_accesses"
    echo "  user-key-show ID       - show only vpn_accesses"
    echo "  user-key-create ID [N] - create fake key for device N (default 1)"
    echo "  user-key-clear ID      - clear all vpn_accesses for user"
    echo "  logs NAME              - follow systemd logs for service NAME"
    ;;
esac
