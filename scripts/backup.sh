#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/vpn/telegram_bot"
BACKUP_ROOT="${BACKUP_ROOT:-/home/vpn/backups/telegram_bot}"
NOW="$(date -u +"%Y%m%dT%H%M%SZ")"
BACKUP_DIR="$BACKUP_ROOT/$NOW"

cd "$PROJECT_DIR"
mkdir -p "$BACKUP_DIR"

echo "== Backup start =="
echo "backup_dir=$BACKUP_DIR"

echo "== PostgreSQL dump =="
PG_DUMP_URL="$(python3 - << 'PY'
import os
from pathlib import Path

env = {}
for line in Path(".env").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    env[key] = value.strip().strip('"').strip("'")

url = env.get("DATABASE_URL", "")
if not url:
    raise SystemExit("DATABASE_URL is empty")

url = url.replace("postgresql+asyncpg://", "postgresql://")
print(url)
PY
)"

pg_dump "$PG_DUMP_URL" > "$BACKUP_DIR/botdb.sql"

echo "== Project env/system configs =="
cp .env "$BACKUP_DIR/env.prod"
cp -a /etc/systemd/system/voidbot.service "$BACKUP_DIR/voidbot.service" 2>/dev/null || true
cp -a /etc/systemd/system/voidbot-webhook.service "$BACKUP_DIR/voidbot-webhook.service" 2>/dev/null || true
cp -a /etc/systemd/system/void-subscription.service "$BACKUP_DIR/void-subscription.service" 2>/dev/null || true

mkdir -p "$BACKUP_DIR/nginx"
cp -a /etc/nginx/sites-available "$BACKUP_DIR/nginx/" 2>/dev/null || true
cp -a /etc/nginx/sites-enabled "$BACKUP_DIR/nginx/" 2>/dev/null || true

echo "== Git state =="
git rev-parse HEAD > "$BACKUP_DIR/git_head.txt"
git status --short > "$BACKUP_DIR/git_status.txt"

echo "== Manifest =="
cat > "$BACKUP_DIR/manifest.txt" << MANIFEST
created_at_utc=$NOW
project_dir=$PROJECT_DIR
git_head=$(cat "$BACKUP_DIR/git_head.txt")
files:
- botdb.sql
- env.prod
- systemd unit files
- nginx sites
- git_head.txt
- git_status.txt
MANIFEST

echo "== Compress =="
tar -C "$BACKUP_ROOT" -czf "$BACKUP_ROOT/$NOW.tar.gz" "$NOW"

echo "== Cleanup old backups =="
find "$BACKUP_ROOT" -maxdepth 1 -name "*.tar.gz" -type f -mtime +14 -print -delete || true
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +14 -print -exec rm -rf {} \; || true

echo "BACKUP OK: $BACKUP_ROOT/$NOW.tar.gz"
