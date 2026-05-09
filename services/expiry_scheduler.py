from __future__ import annotations

import asyncio
import logging
import os

from config.runtime import DEV_MODE
from services.expiry_service import expire_paid_users_once

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)

    if raw is None:
        return default

    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)

    if raw is None:
        return default

    try:
        value = int(raw)
    except ValueError:
        return default

    return max(minimum, min(value, maximum))


def is_expiry_scheduler_enabled() -> bool:
    return _env_bool("EXPIRY_SCHEDULER_ENABLED", default=not DEV_MODE)


async def run_paid_expiry_scheduler(
    *,
    interval_seconds: int,
    first_delay_seconds: int,
    limit: int,
) -> None:
    logger.info(
        "Paid expiry scheduler started: interval=%s first_delay=%s limit=%s",
        interval_seconds,
        first_delay_seconds,
        limit,
    )

    await asyncio.sleep(first_delay_seconds)

    while True:
        try:
            result = await expire_paid_users_once(limit=limit, dry_run=False)
            logger.info(
                "Paid expiry scheduler run completed: found=%s processed=%s",
                result.get("found"),
                result.get("processed"),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Paid expiry scheduler run failed")

        await asyncio.sleep(interval_seconds)


def maybe_start_paid_expiry_scheduler() -> asyncio.Task | None:
    if not is_expiry_scheduler_enabled():
        logger.info("Paid expiry scheduler disabled")
        return None

    interval_seconds = _env_int(
        "EXPIRY_SCHEDULER_INTERVAL_SECONDS",
        default=1800,
        minimum=60,
        maximum=86400,
    )
    first_delay_seconds = _env_int(
        "EXPIRY_SCHEDULER_FIRST_DELAY_SECONDS",
        default=60,
        minimum=1,
        maximum=3600,
    )
    limit = _env_int(
        "EXPIRY_SCHEDULER_LIMIT",
        default=100,
        minimum=1,
        maximum=500,
    )

    return asyncio.create_task(
        run_paid_expiry_scheduler(
            interval_seconds=interval_seconds,
            first_delay_seconds=first_delay_seconds,
            limit=limit,
        ),
        name="paid-expiry-scheduler",
    )
