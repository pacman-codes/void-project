#!/usr/bin/env python3
"""Export a secret-free VOID user manifest for the protected Soodoo importer."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text

from db.database import async_session_maker
from db.models import User


def utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_document(users: list[User], exported_at: datetime) -> dict[str, Any]:
    return {
        "version": 1,
        "source": "void",
        "exported_at": utc_iso(exported_at),
        "users": [
            {
                "telegram_id": int(user.telegram_id),
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "language_code": user.language,
                "subscription_expiry": utc_iso(user.subscription_expiry),
                "device_limit": max(1, int(user.device_limit or 1)),
                "is_active": bool(user.is_active),
                "access_type": user.access_type,
            }
            for user in users
        ],
    }


def encode_document(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def write_private(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        fd = os.open(
            temp,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp.unlink()


async def export_manifest(output: Path) -> int:
    async with async_session_maker() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text("SET LOCAL statement_timeout = '30s'"))
        users = list(
            await session.scalars(
                select(User).order_by(User.telegram_id)
            )
        )
        await session.rollback()

    if not users:
        print("VOID_EXPORT_FAILED=NO_USERS")
        return 2

    ids = [int(user.telegram_id) for user in users]
    if any(value <= 0 for value in ids) or len(ids) != len(set(ids)):
        print("VOID_EXPORT_FAILED=IDENTITY")
        return 2

    now = datetime.now(timezone.utc)
    document = build_document(users, now)
    raw = encode_document(document)
    digest = hashlib.sha256(raw).hexdigest()
    write_private(output, raw)

    future = 0
    paid_active = 0
    for user in users:
        expiry = user.subscription_expiry
        if expiry is not None:
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry.astimezone(timezone.utc) > now:
                future += 1
                if bool(user.is_active) or str(user.access_type or "").lower() == "paid":
                    paid_active += 1

    print("VOID_EXPORT_OK")
    print(f"SOURCE_USERS={len(users)}")
    print(f"SOURCE_FUTURE_EXPIRY={future}")
    print(f"SOURCE_PAID_ACTIVE={paid_active}")
    print(f"MANIFEST_BYTES={len(raw)}")
    print(f"MANIFEST_SHA256={digest}")
    print(f"OUTPUT={output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()
    return asyncio.run(export_manifest(output))


if __name__ == "__main__":
    raise SystemExit(main())
