from __future__ import annotations

import asyncio
import logging
import os

from config.runtime import DEV_MODE
from services.traffic_service import (
    get_traffic_sync_target_telegram_ids,
    sync_user_traffic_from_panel,
)

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


def is_traffic_scheduler_enabled() -> bool:
    return _env_bool("TRAFFIC_SCHEDULER_ENABLED", default=not DEV_MODE)


async def run_traffic_sync_scheduler(
    *,
    interval_seconds: int,
    first_delay_seconds: int,
    limit: int,
) -> None:
    logger.info(
        "Traffic sync scheduler started: interval=%s first_delay=%s limit=%s",
        interval_seconds,
        first_delay_seconds,
        limit,
    )

    await asyncio.sleep(first_delay_seconds)

    while True:
        try:
            telegram_ids = await get_traffic_sync_target_telegram_ids(limit=limit)
            synced = 0
            failed = 0

            for telegram_id in telegram_ids:
                try:
                    await sync_user_traffic_from_panel(
                        telegram_id,
                        actor_telegram_id=None,
                        source="traffic_scheduler",
                    )
                    synced += 1
                except asyncio.CancelledError:
                    raise
                except Exception:
                    failed += 1
                    logger.exception(
                        "Traffic sync failed for telegram_id=%s",
                        telegram_id,
                    )

            logger.info(
                "Traffic sync scheduler run completed: targets=%s synced=%s failed=%s",
                len(telegram_ids),
                synced,
                failed,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Traffic sync scheduler run failed")

        await asyncio.sleep(interval_seconds)


def maybe_start_traffic_sync_scheduler() -> asyncio.Task | None:
    if not is_traffic_scheduler_enabled():
        logger.info("Traffic sync scheduler disabled")
        return None

    interval_seconds = _env_int(
        "TRAFFIC_SCHEDULER_INTERVAL_SECONDS",
        default=300,
        minimum=60,
        maximum=86400,
    )
    first_delay_seconds = _env_int(
        "TRAFFIC_SCHEDULER_FIRST_DELAY_SECONDS",
        default=30,
        minimum=1,
        maximum=3600,
    )
    limit = _env_int(
        "TRAFFIC_SCHEDULER_LIMIT",
        default=100,
        minimum=1,
        maximum=1000,
    )

    return asyncio.create_task(
        run_traffic_sync_scheduler(
            interval_seconds=interval_seconds,
            first_delay_seconds=first_delay_seconds,
            limit=limit,
        ),
        name="traffic-sync-scheduler",
    )
