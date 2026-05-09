from __future__ import annotations

from typing import Any

from sqlalchemy import select

from db.database import async_session_maker
from db.models import User
from services.audit_log_service import log_user_event

DEFAULT_FREE_TRAFFIC_LIMIT_MB = 3072


def _normalize_limit(value: int | None) -> int:
    if value is None or value <= 0:
        return DEFAULT_FREE_TRAFFIC_LIMIT_MB
    return int(value)


def _normalize_used(value: int | None) -> int:
    if value is None or value < 0:
        return 0
    return int(value)


def build_traffic_snapshot(user: User) -> dict[str, Any]:
    used_mb = _normalize_used(user.traffic_used)
    limit_mb = _normalize_limit(user.traffic_limit)
    left_mb = max(limit_mb - used_mb, 0)
    percent_used = round((used_mb / limit_mb) * 100, 2) if limit_mb > 0 else 0

    return {
        "user_id": user.id,
        "telegram_id": user.telegram_id,
        "access_type": user.access_type,
        "traffic_used_mb": used_mb,
        "traffic_limit_mb": limit_mb,
        "traffic_left_mb": left_mb,
        "traffic_used_gb": round(used_mb / 1024, 2),
        "traffic_limit_gb": round(limit_mb / 1024, 2),
        "traffic_left_gb": round(left_mb / 1024, 2),
        "percent_used": percent_used,
        "limit_reached": used_mb >= limit_mb,
    }


async def get_user_traffic_snapshot(telegram_id: int) -> dict[str, Any] | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return None

        changed = False

        if user.traffic_limit is None or user.traffic_limit <= 0:
            user.traffic_limit = DEFAULT_FREE_TRAFFIC_LIMIT_MB
            changed = True

        if user.traffic_used is None or user.traffic_used < 0:
            user.traffic_used = 0
            changed = True

        if changed:
            await session.commit()
            await session.refresh(user)

        return build_traffic_snapshot(user)


async def set_user_traffic_used(
    telegram_id: int,
    used_mb: int,
    *,
    actor_telegram_id: int | None = None,
    source: str = "admin_tools",
) -> dict[str, Any] | None:
    normalized_used = max(0, int(used_mb))

    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return None

        old_used = _normalize_used(user.traffic_used)
        old_limit = _normalize_limit(user.traffic_limit)

        user.traffic_used = normalized_used
        if user.traffic_limit is None or user.traffic_limit <= 0:
            user.traffic_limit = DEFAULT_FREE_TRAFFIC_LIMIT_MB

        await session.commit()
        await session.refresh(user)

        snapshot = build_traffic_snapshot(user)

    await log_user_event(
        event_type="traffic_free_updated",
        target_telegram_id=telegram_id,
        actor_telegram_id=actor_telegram_id,
        source=source,
        status="ok",
        message="Free traffic usage updated",
        details={
            "old_used_mb": old_used,
            "new_used_mb": normalized_used,
            "limit_mb": snapshot["traffic_limit_mb"],
            "percent_used": snapshot["percent_used"],
        },
    )

    if old_used < old_limit and snapshot["limit_reached"]:
        await log_user_event(
            event_type="traffic_free_limit_reached",
            target_telegram_id=telegram_id,
            actor_telegram_id=actor_telegram_id,
            source=source,
            status="warning",
            message="Free traffic limit reached",
            details=snapshot,
        )

    return snapshot


async def reset_user_traffic(
    telegram_id: int,
    *,
    actor_telegram_id: int | None = None,
    source: str = "admin_tools",
) -> dict[str, Any] | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return None

        old_used = _normalize_used(user.traffic_used)

        user.traffic_used = 0
        if user.traffic_limit is None or user.traffic_limit <= 0:
            user.traffic_limit = DEFAULT_FREE_TRAFFIC_LIMIT_MB

        await session.commit()
        await session.refresh(user)

        snapshot = build_traffic_snapshot(user)

    await log_user_event(
        event_type="traffic_free_reset",
        target_telegram_id=telegram_id,
        actor_telegram_id=actor_telegram_id,
        source=source,
        status="ok",
        message="Free traffic usage reset",
        details={
            "old_used_mb": old_used,
            "new_used_mb": 0,
            "limit_mb": snapshot["traffic_limit_mb"],
        },
    )

    return snapshot
