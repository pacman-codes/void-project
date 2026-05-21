#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/vpn/telegram_bot"
BACKUP_ROOT="${BACKUP_ROOT:-/home/vpn/backups/telegram_bot}"

cd "$PROJECT_DIR"

set -a
. ./.env
set +a

if [ -z "${BOT_TOKEN:-}" ]; then
  echo "BOT_TOKEN is empty"
  exit 1
fi

if [ -z "${BACKUP_TELEGRAM_CHAT_ID:-}" ]; then
  echo "BACKUP_TELEGRAM_CHAT_ID is empty"
  exit 1
fi

if [ -z "${BACKUP_ENCRYPTION_PASSWORD:-}" ] || [ "$BACKUP_ENCRYPTION_PASSWORD" = "CHANGE_ME_STRONG_BACKUP_PASSWORD" ]; then
  echo "BACKUP_ENCRYPTION_PASSWORD is not configured"
  exit 1
fi

./scripts/backup.sh

latest="$(find "$BACKUP_ROOT" -maxdepth 1 -name "*.tar.gz" -type f -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)"

if [ -z "${latest:-}" ] || [ ! -s "$latest" ]; then
  echo "Latest backup not found"
  exit 1
fi

encrypted="${latest}.enc"

openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 \
  -in "$latest" \
  -out "$encrypted" \
  -pass env:BACKUP_ENCRYPTION_PASSWORD

/home/vpn/telegram_bot/venv/bin/python - << 'PY'
import os
from pathlib import Path

import httpx

backup_root = Path(os.getenv("BACKUP_ROOT", "/home/vpn/backups/telegram_bot"))
files = sorted(
    backup_root.glob("*.tar.gz.enc"),
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)

if not files:
    raise SystemExit("No encrypted backup found")

path = files[0]
token = os.environ["BOT_TOKEN"]
chat_id = os.environ["BACKUP_TELEGRAM_CHAT_ID"]

caption = f"🔐 VOID encrypted backup\n{path.name}"

with httpx.Client(timeout=120.0) as client:
    with path.open("rb") as f:
        response = client.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={"chat_id": chat_id, "caption": caption},
            files={"document": (path.name, f, "application/octet-stream")},
        )

if response.status_code != 200:
    raise SystemExit(
        f"Telegram upload failed: HTTP {response.status_code} {response.text[:300]}"
    )

print(f"TELEGRAM BACKUP SENT: {path.name}")
PY
