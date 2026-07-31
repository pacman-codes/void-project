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

import asyncio
import json
import os
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update

from db.database import async_session_maker
from db.models import VPNAccess

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
slot_names = {
    ("netherlands_1", 102): "🇳🇱Нидерланды 1",
    ("netherlands_1", 9002): "🇳🇱Нидерланды 2",
    ("prod_1", 104): "🇳🇱Быстрый 1",
    ("prod_1", 9003): "🇳🇱Быстрый 2",
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
    print("CHECK ONLY: no files or DB rows changed")
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


async def update_and_verify_rows() -> None:
    async with async_session_maker() as session:
        for (server_name, device_number), device_name in slot_names.items():
            result = await session.execute(
                update(VPNAccess)
                .where(
                    VPNAccess.server_name == server_name,
                    VPNAccess.device_number == device_number,
                )
                .values(device_name=device_name)
            )
            print(
                f"DB {server_name}/{device_number}: "
                f"updated_rows={int(result.rowcount or 0)} name={device_name!r}"
            )

        await session.commit()

        result = await session.execute(
            select(
                VPNAccess.server_name,
                VPNAccess.device_number,
                VPNAccess.device_name,
            )
            .where(
                VPNAccess.server_name.in_({"netherlands_1", "prod_1"}),
                VPNAccess.device_number.in_({102, 104, 9002, 9003}),
            )
            .order_by(VPNAccess.server_name, VPNAccess.device_number)
        )
        rows = result.all()

    observed = {
        (str(server_name), int(device_number)): str(device_name or "")
        for server_name, device_number, device_name in rows
    }

    for key, expected_name in slot_names.items():
        matching = [
            name
            for observed_key, name in observed.items()
            if observed_key == key
        ]
        if matching and any(name != expected_name for name in matching):
            raise SystemExit(
                f"ERROR: wrong DB name for {key[0]}/{key[1]}: {matching!r}"
            )

    print("DB profile names verified")


asyncio.run(update_and_verify_rows())

print(f"registry backup: {registry_backup}")
print(f"secrets backup: {secrets_backup}")
print("PROFILE NAME APPLY OK")
PY
