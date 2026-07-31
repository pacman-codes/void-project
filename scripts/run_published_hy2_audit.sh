#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/vpn/telegram_bot}"
cd "${PROJECT_DIR}"

PYTHON_BIN="${PROJECT_DIR}/venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "ERROR: project Python not found: ${PYTHON_BIN}" >&2
  exit 1
fi

export PYTHONPATH="${PROJECT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

"${PYTHON_BIN}" - <<'PY'
from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from sqlalchemy import select

from db.database import async_session_maker
from db.models import VPNAccess
from scripts.audit_hy2_endpoints import (
    SECRETS_PATH,
    find_hysteria_binary,
    load_env_file,
    parse_bool,
    test_endpoint,
)
from services.server_registry import get_server_node
from services.subscription_topology import (
    CURRENT_SUBSCRIPTION_SERVER_CODES,
    get_hy2_device_number,
)


async def load_published_rows() -> dict[str, VPNAccess]:
    rows_by_code: dict[str, VPNAccess] = {}

    async with async_session_maker() as session:
        for code in CURRENT_SUBSCRIPTION_SERVER_CODES:
            result = await session.execute(
                select(VPNAccess)
                .where(
                    VPNAccess.server_name == code,
                    VPNAccess.device_number == get_hy2_device_number(code),
                    VPNAccess.is_active.is_(True),
                    VPNAccess.config_url.is_not(None),
                )
                .order_by(VPNAccess.updated_at.desc(), VPNAccess.id.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            if row is not None:
                rows_by_code[code] = row

    return rows_by_code


def main() -> int:
    print("== Exact published HY2 profile audit (secrets masked) ==")

    binary = find_hysteria_binary()
    if binary is None:
        print("ERROR: Hysteria binary not found")
        return 1

    if not Path(SECRETS_PATH).is_file():
        print(f"ERROR: secrets file not found: {SECRETS_PATH}")
        return 1

    secret_values = load_env_file(Path(SECRETS_PATH))
    rows_by_code = asyncio.run(load_published_rows())
    failures = 0

    for code in CURRENT_SUBSCRIPTION_SERVER_CODES:
        print()
        print(f"[{code}]")

        row = rows_by_code.get(code)
        if row is None:
            print("FAIL — active published HY2 DB row not found")
            failures += 1
            continue

        raw_uri = (row.config_url or "").strip()
        try:
            parts = urlsplit(raw_uri)
            query = dict(parse_qsl(parts.query, keep_blank_values=True))
        except Exception as exc:
            print(f"FAIL — URI parse error: {type(exc).__name__}: {exc}")
            failures += 1
            continue

        if parts.scheme not in {"hysteria2", "hy2"}:
            print(f"FAIL — wrong scheme: {parts.scheme!r}")
            failures += 1
            continue

        auth = unquote(parts.username or "")
        host = parts.hostname or ""
        port = int(parts.port or 443)
        sni = query.get("sni", host)

        try:
            insecure = parse_bool(query.get("insecure", "0"), default=False)
        except Exception as exc:
            print(f"FAIL — invalid insecure value: {exc}")
            failures += 1
            continue

        obfs_type = query.get("obfs", "").strip().lower()
        obfs_password = query.get("obfs-password", "")

        node = get_server_node(code)
        prefix = node.secret_ref
        expected_auth = secret_values.get(f"{prefix}_HY2_AUTH", "").strip()
        expected_port = int(
            secret_values.get(f"{prefix}_HY2_PORT", str(node.public_port))
            or node.public_port
        )
        expected_sni = (
            secret_values.get(f"{prefix}_HY2_SNI", node.public_host).strip()
            or node.public_host
        )

        print(f"db_access_id={row.id}")
        print(f"scheme={parts.scheme}")
        print(f"endpoint={host}:{port}")
        print(f"sni={sni}")
        print(f"insecure={insecure}")
        print(f"profile_name={unquote(parts.fragment)}")
        print(f"auth_present={bool(auth)} auth_length={len(auth)}")
        print(f"auth_matches_runtime_secret={auth == expected_auth}")
        print(f"endpoint_matches_runtime={host == node.public_host and port == expected_port}")
        print(f"sni_matches_runtime={sni == expected_sni}")
        print(f"obfs={obfs_type or '-'} obfs_password_present={bool(obfs_password)}")

        if not auth or not host:
            print("FAIL — published URI is missing auth or host")
            failures += 1
            continue

        if auth != expected_auth:
            print("FAIL — published auth differs from runtime secret")
            failures += 1
            continue

        if host != node.public_host or port != expected_port:
            print("FAIL — published endpoint differs from runtime configuration")
            failures += 1
            continue

        if sni != expected_sni:
            print("FAIL — published SNI differs from runtime configuration")
            failures += 1
            continue

        if not test_endpoint(
            binary=binary,
            code=f"{code}/published",
            host=host,
            port=port,
            auth=auth,
            sni=sni,
            insecure=insecure,
            obfs_type=obfs_type,
            obfs_password=obfs_password,
        ):
            failures += 1

    print()
    print(f"PUBLISHED_HY2_AUDIT_FAILURES={failures}")
    return 1 if failures else 0


raise SystemExit(main())
PY
