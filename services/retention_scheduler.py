from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot

from services.retention_service import run_retention_once

logger = logging.getLogger(__name__)


def is_retention_scheduler_enabled() -> bool:
    return os.getenv("RETENTION_SCHEDULER_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


def get_retention_interval_seconds() -> int:
    return int(os.getenv("RETENTION_SCHEDULER_INTERVAL_SECONDS", "21600"))


def get_retention_first_delay_seconds() -> int:
    return int(os.getenv("RETENTION_SCHEDULER_FIRST_DELAY_SECONDS", "300"))


def get_retention_limit() -> int:
    return int(os.getenv("RETENTION_SCHEDULER_LIMIT", "100"))


async def run_retention_scheduler(
    bot: Bot,
    interval_seconds: int,
    first_delay_seconds: int,
    limit: int,
) -> None:
    logger.info(
        "Retention scheduler started: interval=%s first_delay=%s limit=%s",
        interval_seconds,
        first_delay_seconds,
        limit,
    )

    await asyncio.sleep(first_delay_seconds)

    while True:
        try:
            result = await run_retention_once(bot, limit=limit, dry_run=False)
            logger.info(
                "Retention scheduler run completed: candidates=%s sent=%s failed=%s",
                result.get("candidates"),
                result.get("sent"),
                result.get("failed"),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Retention scheduler run failed")

        await asyncio.sleep(interval_seconds)


def maybe_start_retention_scheduler(bot: Bot) -> asyncio.Task | None:
    if not is_retention_scheduler_enabled():
        logger.info("Retention scheduler disabled")
        return None

    return asyncio.create_task(
        run_retention_scheduler(
            bot=bot,
            interval_seconds=get_retention_interval_seconds(),
            first_delay_seconds=get_retention_first_delay_seconds(),
            limit=get_retention_limit(),
        )
    )
