from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from db.database import async_session_maker as SessionMaker
except ImportError:  # fallback for older project naming
    from db.database import async_session as SessionMaker

from db.models import User, UserEvent, UserSubscriptionLink
from services.retention_texts import build_retention_text


MAX_RETENTION_PUSHES_TOTAL = 10


@dataclass(frozen=True)
class RetentionCandidate:
    user_id: int
    telegram_id: int
    username: str | None
    first_name: str | None
    access_type: str | None
    scenario: str
    stage: str
    cycle_key: str
    text: str


def _now() -> datetime:
    return datetime.utcnow()


def _json_contains_cycle(cycle_key: str) -> str:
    return f'"cycle_key": "{cycle_key}"'


async def _user_retention_pushes_count(session: AsyncSession, telegram_id: int) -> int:
    result = await session.execute(
        select(func.count(UserEvent.id)).where(
            UserEvent.target_telegram_id == telegram_id,
            UserEvent.event_type.like("retention_%_sent"),
        )
    )
    return int(result.scalar() or 0)


async def _already_sent(session: AsyncSession, telegram_id: int, event_type: str, cycle_key: str) -> bool:
    result = await session.execute(
        select(UserEvent.id)
        .where(
            UserEvent.target_telegram_id == telegram_id,
            UserEvent.event_type == event_type,
            UserEvent.status == "ok",
            UserEvent.details_json.contains(_json_contains_cycle(cycle_key)),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _last_retention_sent_at(session: AsyncSession, telegram_id: int) -> datetime | None:
    result = await session.execute(
        select(UserEvent.created_at)
        .where(
            UserEvent.target_telegram_id == telegram_id,
            UserEvent.event_type.like("retention_%_sent"),
            UserEvent.status == "ok",
        )
        .order_by(UserEvent.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _can_send(
    session: AsyncSession,
    telegram_id: int,
    event_type: str,
    cycle_key: str,
    min_gap: timedelta = timedelta(days=3),
) -> bool:
    if await _already_sent(session, telegram_id, event_type, cycle_key):
        return False

    total = await _user_retention_pushes_count(session, telegram_id)
    if total >= MAX_RETENTION_PUSHES_TOTAL:
        return False

    last_sent_at = await _last_retention_sent_at(session, telegram_id)
    if last_sent_at and (_now() - last_sent_at) < min_gap:
        return False

    return True


def _candidate(
    user: User,
    scenario: str,
    stage: str,
    cycle_key: str,
) -> RetentionCandidate:
    return RetentionCandidate(
        user_id=user.id,
        telegram_id=user.telegram_id,
        username=user.username,
        first_name=getattr(user, "first_name", None),
        access_type=user.access_type,
        scenario=scenario,
        stage=stage,
        cycle_key=cycle_key,
        text=build_retention_text(scenario, stage, getattr(user, "first_name", None)),
    )


async def collect_retention_candidates(limit: int = 100) -> list[RetentionCandidate]:
    now = _now()
    candidates: list[RetentionCandidate] = []

    async with SessionMaker() as session:
        # FREE users with link/no link/usage states.
        free_result = await session.execute(
            select(User)
            .where(
                User.access_type == "free",
                User.is_active.is_(True),
            )
            .order_by(User.id.asc())
            .limit(limit)
        )
        free_users = list(free_result.scalars().all())

        for user in free_users:
            # Do not push users who already started a paid payment flow.
            if getattr(user, "payment_status", None):
                continue

            link_result = await session.execute(
                select(UserSubscriptionLink)
                .where(
                    UserSubscriptionLink.user_id == user.id,
                    UserSubscriptionLink.is_active.is_(True),
                )
                .order_by(UserSubscriptionLink.created_at.desc())
                .limit(1)
            )
            link = link_result.scalar_one_or_none()

            traffic_used = int(user.traffic_used or 0)
            traffic_limit = int(user.traffic_limit or 3072)

            if not link:
                cycle_key = f"free_no_link:{user.id}:{(user.created_at or now).date().isoformat()}"
                event_type = "retention_free_no_link_sent"
                if await _can_send(session, user.telegram_id, event_type, cycle_key):
                    candidates.append(_candidate(user, "free_no_link", "start", cycle_key))
                continue

            if traffic_used <= 0:
                cycle_key = f"free_no_usage:link:{link.id}:{(link.created_at or now).date().isoformat()}"
                event_type = "retention_free_no_usage_sent"
                if await _can_send(session, user.telegram_id, event_type, cycle_key):
                    candidates.append(_candidate(user, "free_no_usage", "start", cycle_key))
                continue

            if traffic_limit > 0:
                pct = traffic_used / traffic_limit
                if pct >= 1:
                    stage = "100"
                elif pct >= 0.9:
                    stage = "90"
                elif pct >= 0.7:
                    stage = "70"
                else:
                    stage = ""

                if stage:
                    month_key = now.strftime("%Y-%m")
                    cycle_key = f"free_near_limit:{user.id}:{month_key}:{stage}"
                    event_type = f"retention_free_near_limit_{stage}_sent"
                    if await _can_send(session, user.telegram_id, event_type, cycle_key):
                        candidates.append(_candidate(user, "free_near_limit", stage, cycle_key))
                    continue

            cycle_key = f"free_usage:{user.id}:{now.strftime('%Y-%m')}"
            event_type = "retention_free_usage_sent"
            if await _can_send(session, user.telegram_id, event_type, cycle_key):
                candidates.append(_candidate(user, "free_usage", "start", cycle_key))

        # PAID expiry/expired users.
        paid_result = await session.execute(
            select(User)
            .where(
                User.access_type == "paid",
                User.is_active.is_(True),
                User.subscription_expiry.is_not(None),
            )
            .order_by(User.subscription_expiry.asc())
            .limit(limit)
        )
        paid_users = list(paid_result.scalars().all())

        for user in paid_users:
            expiry = user.subscription_expiry
            if not expiry:
                continue

            delta = expiry - now

            if timedelta(days=6) < delta <= timedelta(days=7):
                scenario, stage = "paid_expiring", "7d"
            elif timedelta(days=2) < delta <= timedelta(days=3):
                scenario, stage = "paid_expiring", "3d"
            elif timedelta(hours=12) < delta <= timedelta(days=1):
                scenario, stage = "paid_expiring", "1d"
            elif timedelta(0) < delta <= timedelta(hours=12):
                scenario, stage = "paid_expiring", "today"
            elif delta <= timedelta(0):
                scenario, stage = "paid_expired", "start"
            else:
                continue

            expiry_key = expiry.date().isoformat()
            cycle_key = f"{scenario}:{user.id}:{expiry_key}:{stage}"
            event_type = f"retention_{scenario}_{stage}_sent"
            if await _can_send(session, user.telegram_id, event_type, cycle_key, min_gap=timedelta(hours=12)):
                candidates.append(_candidate(user, scenario, stage, cycle_key))

    return candidates[:limit]


async def log_retention_event(
    session: AsyncSession,
    candidate: RetentionCandidate,
    status: str,
    message: str,
    error: str | None = None,
) -> None:
    event_type = f"retention_{candidate.scenario}_{candidate.stage}_sent"
    details = {
        "scenario": candidate.scenario,
        "stage": candidate.stage,
        "cycle_key": candidate.cycle_key,
        "username": candidate.username,
    }
    if error:
        details["error"] = error

    session.add(
        UserEvent(
            user_id=candidate.user_id,
            target_telegram_id=candidate.telegram_id,
            actor_telegram_id=None,
            event_type=event_type,
            source="retention",
            status=status,
            message=message,
            details_json=json.dumps(details, ensure_ascii=False),
            created_at=_now(),
        )
    )


async def run_retention_once(bot: Bot, limit: int = 100, dry_run: bool = True) -> dict:
    candidates = await collect_retention_candidates(limit=limit)

    result = {
        "dry_run": dry_run,
        "candidates": len(candidates),
        "sent": 0,
        "failed": 0,
        "items": [
            {
                "telegram_id": c.telegram_id,
                "username": c.username,
                "first_name": c.first_name,
                "access_type": c.access_type,
                "scenario": c.scenario,
                "stage": c.stage,
                "cycle_key": c.cycle_key,
                "text": c.text,
            }
            for c in candidates
        ],
    }

    if dry_run:
        return result

    async with SessionMaker() as session:
        for candidate in candidates:
            try:
                await bot.send_message(candidate.telegram_id, candidate.text)
                await log_retention_event(
                    session,
                    candidate,
                    status="ok",
                    message="Retention notification sent",
                )
                result["sent"] += 1
            except Exception as exc:  # TelegramForbiddenError etc.
                await log_retention_event(
                    session,
                    candidate,
                    status="error",
                    message="Retention notification failed",
                    error=repr(exc),
                )
                result["failed"] += 1

        await session.commit()

    return result
