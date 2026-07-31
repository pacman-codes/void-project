#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/vpn/telegram_bot}"
REGISTRY_PATH="${SERVER_REGISTRY_PATH:-/etc/void/servers.json}"
SECRETS_PATH="${SERVER_SECRETS_PATH:-/etc/void/server_secrets.env}"
MODE="${1:-check}"

if [[ "${MODE}" != "check" && "${MODE}" != "--apply" ]]; then
  echo "Usage: $0 [check|--apply]" >&2
  exit 2
fi

cd "${PROJECT_DIR}"

PYTHON_BIN="${PROJECT_DIR}/venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "ERROR: project Python not found: ${PYTHON_BIN}" >&2
  exit 1
fi

export REGISTRY_PATH SECRETS_PATH MODE

"${PYTHON_BIN}" - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

registry_path = Path(os.environ["REGISTRY_PATH"])
secrets_path = Path(os.environ["SECRETS_PATH"])
apply_changes = os.environ["MODE"] == "--apply"

vless_names = {
    "netherlands_1": "🇳🇱Нидерланды 1",
    "prod_1": "🇳🇱Быстрый 1",
}
hy2_names = {
    "netherlands_1": "🇳🇱Нидерланды 2",
    "prod_1": "🇳🇱Быстрый 2",
}

registry = json.loads(registry_path.read_text())
servers = registry.get("servers")
if not isinstance(servers, list):
    raise SystemExit("ERROR: registry has no servers list")

by_code = {
    str(item.get("code", "")): item
    for item in servers
    if isinstance(item, dict)
}

missing = [code for code in vless_names if code not in by_code]
if missing:
    raise SystemExit("ERROR: missing registry node(s): " + ", ".join(missing))

secret_name_updates: dict[str, str] = {}
for code, name in vless_names.items():
    node = by_code[code]
    secret_ref = str(node.get("secret_ref", "")).strip()
    if not secret_ref:
        raise SystemExit(f"ERROR: {code} has empty secret_ref")

    print(
        f"{code}: VLESS name {node.get('display_name')!r} -> {name!r}; "
        f"HY2 name key {secret_ref}_HY2_NAME -> {hy2_names[code]!r}"
    )
    node["display_name"] = name
    secret_name_updates[f"{secret_ref}_HY2_NAME"] = hy2_names[code]

if not apply_changes:
    print("CHECK ONLY: no files changed")
    raise SystemExit(0)

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
registry_backup = registry_path.with_name(f"{registry_path.name}.bak_profile_names_{stamp}")
secrets_backup = secrets_path.with_name(f"{secrets_path.name}.bak_profile_names_{stamp}")

shutil.copy2(registry_path, registry_backup)
shutil.copy2(secrets_path, secrets_backup)

registry_stat = registry_path.stat()
secrets_stat = secrets_path.stat()


def atomic_write(path: Path, text: str, source_stat: os.stat_result) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())

        os.chmod(temporary_path, stat.S_IMODE(source_stat.st_mode))
        os.chown(temporary_path, source_stat.st_uid, source_stat.st_gid)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


registry_text = json.dumps(registry, ensure_ascii=False, indent=2) + "\n"
atomic_write(registry_path, registry_text, registry_stat)

lines = secrets_path.read_text().splitlines()
remaining = dict(secret_name_updates)
updated_lines: list[str] = []

for raw in lines:
    stripped = raw.strip()
    if stripped and not stripped.startswith("#") and "=" in raw:
        key = raw.split("=", 1)[0].strip()
        if key in remaining:
            updated_lines.append(f"{key}={remaining.pop(key)}")
            continue
    updated_lines.append(raw)

if remaining:
    if updated_lines and updated_lines[-1].strip():
        updated_lines.append("")
    updated_lines.append("# Current public profile names")
    for key, value in remaining.items():
        updated_lines.append(f"{key}={value}")

atomic_write(secrets_path, "\n".join(updated_lines).rstrip() + "\n", secrets_stat)

print(f"registry backup: {registry_backup}")
print(f"secrets backup: {secrets_backup}")
print("PROFILE NAME FILE UPDATE OK")
PY

if [[ "${MODE}" == "check" ]]; then
  exit 0
fi

echo "== update existing technical row names =="
db <<'SQL'
BEGIN;

UPDATE vpn_accesses
SET device_name = '🇳🇱Нидерланды 1'
WHERE server_name = 'netherlands_1'
  AND device_number = 102
  AND device_name IS DISTINCT FROM '🇳🇱Нидерланды 1';

UPDATE vpn_accesses
SET device_name = '🇳🇱Нидерланды 2'
WHERE server_name = 'netherlands_1'
  AND device_number = 9002
  AND device_name IS DISTINCT FROM '🇳🇱Нидерланды 2';

UPDATE vpn_accesses
SET device_name = '🇳🇱Быстрый 1'
WHERE server_name = 'prod_1'
  AND device_number = 104
  AND device_name IS DISTINCT FROM '🇳🇱Быстрый 1';

UPDATE vpn_accesses
SET device_name = '🇳🇱Быстрый 2'
WHERE server_name = 'prod_1'
  AND device_number = 9003
  AND device_name IS DISTINCT FROM '🇳🇱Быстрый 2';

COMMIT;
SQL

echo "== verify names =="
"${PYTHON_BIN}" - <<'PY'
from services.server_registry import get_server_node

assert get_server_node("netherlands_1").display_name == "🇳🇱Нидерланды 1"
assert get_server_node("prod_1").display_name == "🇳🇱Быстрый 1"
print("registry profile names OK")
PY

db <<'SQL'
SELECT
    server_name,
    device_number,
    device_name,
    COUNT(*) AS rows
FROM vpn_accesses
WHERE (server_name, device_number) IN (
    ('netherlands_1', 102),
    ('netherlands_1', 9002),
    ('prod_1', 104),
    ('prod_1', 9003)
)
GROUP BY server_name, device_number, device_name
ORDER BY server_name, device_number;
SQL

echo "PROFILE NAME APPLY OK"
