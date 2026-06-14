from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl

from config.config import settings


class AdminMiniAppAuthError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AdminMiniAppIdentity:
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    auth_date: int | None


def parse_admin_miniapp_telegram_ids(raw: str | None = None) -> set[int]:
    source = settings.ADMIN_MINIAPP_TELEGRAM_IDS if raw is None else raw
    result: set[int] = set()

    for item in source.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.add(int(item))
        except ValueError:
            continue

    return result


def verify_telegram_webapp_init_data(
    init_data: str,
    *,
    bot_token: str | None = None,
    max_age_seconds: int | None = None,
    now_seconds: int | None = None,
) -> dict[str, str]:
    if not init_data:
        raise AdminMiniAppAuthError(401, "missing_init_data", "Telegram initData is required")

    token = (bot_token if bot_token is not None else settings.BOT_TOKEN).strip()
    if not token:
        raise AdminMiniAppAuthError(503, "bot_token_not_configured", "BOT_TOKEN is not configured")

    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    values = dict(pairs)
    provided_hash = values.get("hash", "")

    if not provided_hash:
        raise AdminMiniAppAuthError(401, "missing_hash", "Telegram initData hash is required")

    data_check_string = "\n".join(
        sorted(f"{key}={value}" for key, value in pairs if key != "hash")
    )

    secret_key = hmac.new(
        b"WebAppData",
        token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, provided_hash):
        raise AdminMiniAppAuthError(401, "invalid_signature", "Telegram initData signature is invalid")

    auth_date_raw = values.get("auth_date")
    if not auth_date_raw:
        raise AdminMiniAppAuthError(401, "missing_auth_date", "Telegram auth_date is required")

    try:
        auth_date = int(auth_date_raw)
    except ValueError as exc:
        raise AdminMiniAppAuthError(401, "invalid_auth_date", "Telegram auth_date is invalid") from exc

    max_age = (
        settings.ADMIN_MINIAPP_INITDATA_MAX_AGE_SECONDS
        if max_age_seconds is None
        else max_age_seconds
    )
    current = int(time.time()) if now_seconds is None else now_seconds

    if auth_date > current + 60:
        raise AdminMiniAppAuthError(401, "future_auth_date", "Telegram auth_date is in the future")

    if max_age > 0 and current - auth_date > max_age:
        raise AdminMiniAppAuthError(401, "stale_init_data", "Telegram initData is too old")

    return values


def _parse_webapp_user(raw_user: str | None) -> dict[str, Any]:
    if not raw_user:
        raise AdminMiniAppAuthError(401, "missing_user", "Telegram initData user is required")

    try:
        user = json.loads(raw_user)
    except json.JSONDecodeError as exc:
        raise AdminMiniAppAuthError(401, "invalid_user", "Telegram initData user is invalid") from exc

    if not isinstance(user, dict):
        raise AdminMiniAppAuthError(401, "invalid_user", "Telegram initData user must be an object")

    return user


def authenticate_admin_init_data(init_data: str) -> AdminMiniAppIdentity:
    values = verify_telegram_webapp_init_data(init_data)
    user = _parse_webapp_user(values.get("user"))

    try:
        telegram_id = int(user["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AdminMiniAppAuthError(401, "missing_telegram_id", "Telegram user id is required") from exc

    allowed_ids = parse_admin_miniapp_telegram_ids()
    if telegram_id not in allowed_ids:
        raise AdminMiniAppAuthError(403, "forbidden", "Telegram user is not allowed")

    auth_date: int | None = None
    if values.get("auth_date"):
        try:
            auth_date = int(values["auth_date"])
        except ValueError:
            auth_date = None

    return AdminMiniAppIdentity(
        telegram_id=telegram_id,
        username=user.get("username") if isinstance(user.get("username"), str) else None,
        first_name=user.get("first_name") if isinstance(user.get("first_name"), str) else None,
        last_name=user.get("last_name") if isinstance(user.get("last_name"), str) else None,
        auth_date=auth_date,
    )
