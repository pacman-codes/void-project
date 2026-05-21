#!/usr/bin/env bash
set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/home/vpn/backups/telegram_bot}"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-24}"

echo "== Backup check =="
echo "backup_root=$BACKUP_ROOT"
echo "max_age_hours=$MAX_AGE_HOURS"

latest="$(find "$BACKUP_ROOT" -maxdepth 1 -name "*.tar.gz" -type f -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)"

if [ -z "${latest:-}" ]; then
  echo "No backup archives found"
  exit 1
fi

echo "latest=$latest"

if [ ! -s "$latest" ]; then
  echo "Latest backup is empty"
  exit 1
fi

now="$(date +%s)"
mtime="$(stat -c %Y "$latest")"
age_seconds="$((now - mtime))"
max_seconds="$((MAX_AGE_HOURS * 3600))"

echo "age_seconds=$age_seconds"

if [ "$age_seconds" -gt "$max_seconds" ]; then
  echo "Latest backup is too old"
  exit 1
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

tar -tzf "$latest" >/tmp/void_backup_tar_list.txt

if ! grep -q "botdb.sql" /tmp/void_backup_tar_list.txt; then
  echo "botdb.sql not found in backup"
  exit 1
fi

tar -xzf "$latest" -C "$tmpdir"

sql_file="$(find "$tmpdir" -name botdb.sql -type f | head -1)"
if [ -z "$sql_file" ] || [ ! -s "$sql_file" ]; then
  echo "botdb.sql missing or empty after extract"
  exit 1
fi

if ! grep -q "PostgreSQL database dump" "$sql_file"; then
  echo "botdb.sql does not look like pg_dump output"
  exit 1
fi

echo "BACKUP CHECK OK"
