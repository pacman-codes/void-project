#!/usr/bin/env python3
"""One-shot resumable VOID -> Soodoo transition notification sender.

Dry-run is the default. Sending requires both --send and a confirmation equal
to the SHA-256 of the exact UTF-8 message file approved by the owner.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from sqlalchemy import select, text

from config.config import settings
from db.database import async_session_maker
from db.models import User


MAX_MESSAGE_BYTES = 16 * 1024
DEFAULT_DELAY_SECONDS = 0.08


def read_message(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_MESSAGE_BYTES or b"\0" in raw:
        raise ValueError("invalid message")
    message = raw.decode("utf-8", "strict").strip()
    if not message:
        raise ValueError("empty message")
    return message, hashlib.sha256(raw).hexdigest()


def load_state(path: Path, message_sha: str) -> dict:
    if not path.exists():
        return {
            "version": 1,
            "message_sha256": message_sha,
            "results": {},
        }
    raw = path.read_bytes()
    if not raw or len(raw) > 16 * 1024 * 1024:
        raise ValueError("invalid state")
    state = json.loads(raw.decode("utf-8", "strict"))
    if (
        not isinstance(state, dict)
        or state.get("version") != 1
        or state.get("message_sha256") != message_sha
        or not isinstance(state.get("results"), dict)
    ):
        raise ValueError("state/message mismatch")
    return state


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (
        json.dumps(
            state,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(
        temp,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


async def recipient_ids() -> list[int]:
    async with async_session_maker() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text("SET LOCAL statement_timeout = '30s'"))
        ids = [
            int(value)
            for value in await session.scalars(
                select(User.telegram_id).order_by(User.telegram_id)
            )
        ]
        await session.rollback()
    if any(value <= 0 for value in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("invalid recipient identity")
    return ids


async def send_all(
    *,
    recipients: list[int],
    message: str,
    message_sha: str,
    state_path: Path,
    delay_seconds: float,
) -> dict[str, int]:
    state = load_state(state_path, message_sha)
    results = state["results"]
    bot = Bot(token=settings.BOT_TOKEN)

    try:
        for telegram_id in recipients:
            key = str(telegram_id)
            previous = results.get(key)
            if previous in {"delivered", "blocked"}:
                continue

            status = "failed"
            try:
                await bot.send_message(
                    chat_id=telegram_id,
                    text=message,
                    disable_web_page_preview=True,
                )
                status = "delivered"
            except TelegramRetryAfter as exc:
                await asyncio.sleep(max(float(exc.retry_after), 1.0))
                try:
                    await bot.send_message(
                        chat_id=telegram_id,
                        text=message,
                        disable_web_page_preview=True,
                    )
                    status = "delivered"
                except TelegramForbiddenError:
                    status = "blocked"
                except Exception:
                    status = "failed"
            except TelegramForbiddenError:
                status = "blocked"
            except TelegramBadRequest:
                status = "failed"
            except Exception:
                status = "failed"

            results[key] = status
            save_state(state_path, state)
            await asyncio.sleep(delay_seconds)
    finally:
        await bot.session.close()

    counts = {"delivered": 0, "blocked": 0, "failed": 0, "pending": 0}
    for telegram_id in recipients:
        status = results.get(str(telegram_id))
        if status in counts:
            counts[status] += 1
        else:
            counts["pending"] += 1
    return counts


async def async_main(args) -> int:
    message_path = Path(args.message).expanduser().resolve()
    state_path = Path(args.state).expanduser().resolve()
    message, digest = read_message(message_path)
    recipients = await recipient_ids()

    print("VOID_NOTIFICATION_PLAN_OK")
    print(f"RECIPIENTS={len(recipients)}")
    print(f"MESSAGE_SHA256={digest}")

    if not args.send:
        print("SEND_EXECUTED=no")
        return 0

    if args.confirm != digest:
        print("VOID_NOTIFICATION_FAILED=CONFIRM")
        return 2

    counts = await send_all(
        recipients=recipients,
        message=message,
        message_sha=digest,
        state_path=state_path,
        delay_seconds=max(0.05, float(args.delay)),
    )
    print("VOID_NOTIFICATION_SEND_DONE")
    print(f"DELIVERED={counts['delivered']}")
    print(f"BLOCKED={counts['blocked']}")
    print(f"FAILED={counts['failed']}")
    print(f"PENDING={counts['pending']}")
    return 0 if counts["failed"] == 0 and counts["pending"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--message", required=True)
    parser.add_argument(
        "--state",
        default="/home/vpn/telegram_bot/soodoo-transition-notify-state.json",
    )
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
