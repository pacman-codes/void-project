from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

from db.database import async_session_maker
from db.models import User, UserEvent

logger = logging.getLogger(__name__)


def _json_dumps(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None

    return json.dumps(value, ensure_ascii=False, default=str)


async def log_user_event(
    *,
    event_type: str,
    target_telegram_id: int | None = None,
    actor_telegram_id: int | None = None,
    user_id: int | None = None,
    source: str = "bot",
    status: str = "ok",
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    try:
        async with async_session_maker() as session:
            resolved_user_id = user_id

            if resolved_user_id is None and target_telegram_id is not None:
                result = await session.execute(
                    select(User.id).where(User.telegram_id == target_telegram_id)
                )
                resolved_user_id = result.scalar_one_or_none()

            event = UserEvent(
                user_id=resolved_user_id,
                target_telegram_id=target_telegram_id,
                actor_telegram_id=actor_telegram_id,
                event_type=event_type,
                source=source,
                status=status,
                message=message,
                details_json=_json_dumps(details),
                created_at=datetime.utcnow(),
            )
            session.add(event)
            await session.commit()
    except Exception:
        logger.exception("Failed to write user event: %s", event_type)


async def get_recent_user_events(
    telegram_id: int,
    limit: int = 10,
) -> list[UserEvent]:
    safe_limit = max(1, min(limit, 30))

    async with async_session_maker() as session:
        result = await session.execute(
            select(UserEvent)
            .where(UserEvent.target_telegram_id == telegram_id)
            .order_by(UserEvent.created_at.desc(), UserEvent.id.desc())
            .limit(safe_limit)
        )
        return list(result.scalars().all())
