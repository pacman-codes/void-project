from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select

from db.database import async_session_maker
from db.models import User, UserEvent, UserSubscriptionLink, VPNAccess
from services.server_registry import ServerRegistryError, load_server_nodes


DEFAULT_USERS_LIMIT = 50
MAX_USERS_LIMIT = 100
DEFAULT_EVENTS_LIMIT = 20
MAX_EVENTS_LIMIT = 50

_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_CONFIG_LINK_RE = re.compile(r"\b(?:vless|hy2|hysteria2)://[^\s\"']+", re.IGNORECASE)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def mask_token(value: object | None) -> str | None:
    if value is None:
        return None

    raw = str(value)
    if not raw:
        return None

    return f"****{raw[-4:]}" if len(raw) > 4 else "****"


def mask_uuid(value: object | None) -> str | None:
    if value is None:
        return None

    raw = str(value)
    if not raw:
        return None

    return f"****-****-****-{raw[-4:]}" if len(raw) >= 4 else "****-****-****"


def _mask_tail(value: object | None) -> str | None:
    if value is None:
        return None

    raw = str(value)
    if not raw:
        return None

    return f"****{raw[-4:]}" if len(raw) > 4 else "****"


def _sanitize_string(value: str) -> str:
    value = _CONFIG_LINK_RE.sub("hidden", value)
    return _UUID_RE.sub(lambda match: mask_uuid(match.group(0)) or "****-****-****", value)


def _sanitize_event_value(key: str, value: Any) -> Any:
    lower_key = key.lower()

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if any(part in lower_key for part in ("password", "secret", "private_key", "api_key")):
        return "hidden"

    if lower_key in {
        "config_url",
        "payment_confirmation_url",
        "confirmation_url",
        "subscription_url",
        "vless_url",
        "hy2_url",
    } or lower_key.endswith("_url"):
        return "hidden"

    if lower_key in {"token", "subscription_token", "access_token", "refresh_token", "csrf_token"}:
        return mask_token(value)

    if lower_key in {"uuid", "client_uuid", "panel_uuid"} or lower_key.endswith("_uuid"):
        return mask_uuid(value)

    if lower_key in {"payment_id", "external_id", "client_id"}:
        return _mask_tail(value)

    if isinstance(value, str):
        return _sanitize_string(value)

    if isinstance(value, list):
        return [_sanitize_event_value(key, item) for item in value[:20]]

    if isinstance(value, dict):
        return {
            str(child_key): _sanitize_event_value(str(child_key), child_value)
            for child_key, child_value in list(value.items())[:50]
        }

    return str(value)


def sanitize_event_details(details_json: str | None) -> dict[str, Any] | None:
    if not details_json:
        return None

    try:
        parsed = json.loads(details_json)
    except json.JSONDecodeError:
        return {"raw": _sanitize_string(details_json[:500])}

    if not isinstance(parsed, dict):
        return {"value": _sanitize_event_value("value", parsed)}

    return {
        str(key): _sanitize_event_value(str(key), value)
        for key, value in list(parsed.items())[:50]
    }


def serialize_user(
    user: User,
    *,
    active_access_count: int = 0,
    last_event: UserEvent | None = None,
) -> dict[str, Any]:
    return {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "access_type": user.access_type,
        "is_active": bool(user.is_active),
        "subscription_expiry": _dt(user.subscription_expiry),
        "traffic_used": user.traffic_used,
        "traffic_limit": user.traffic_limit,
        "device_limit": user.device_limit,
        "created_at": _dt(user.created_at),
        "active_access_row_count": active_access_count,
        "last_event": serialize_event_summary(last_event) if last_event else None,
    }


def serialize_event_summary(event: UserEvent | None) -> dict[str, Any] | None:
    if event is None:
        return None

    return {
        "event_type": event.event_type,
        "created_at": _dt(event.created_at),
    }


def serialize_event(event: UserEvent) -> dict[str, Any]:
    return {
        "event_type": event.event_type,
        "source": event.source,
        "status": event.status,
        "message": _sanitize_string(str(event.message)) if event.message else None,
        "actor_telegram_id": event.actor_telegram_id,
        "created_at": _dt(event.created_at),
        "details": sanitize_event_details(event.details_json),
    }


def _safe_limit(value: int | None, default: int, maximum: int) -> int:
    if value is None:
        return default

    return max(1, min(value, maximum))


async def get_admin_stats() -> dict[str, Any]:
    now = datetime.utcnow()

    async with async_session_maker() as session:
        total_users = await session.scalar(select(func.count(User.id)))
        active_users = await session.scalar(
            select(func.count(User.id)).where(User.is_active.is_(True))
        )
        paid_users = await session.scalar(
            select(func.count(User.id)).where(User.access_type == "paid")
        )
        free_users = await session.scalar(
            select(func.count(User.id)).where(User.access_type == "free")
        )
        trial_users = await session.scalar(
            select(func.count(User.id)).where(User.access_type == "trial")
        )
        none_access_users = await session.scalar(
            select(func.count(User.id)).where(
                or_(User.access_type.is_(None), User.access_type == "")
            )
        )
        expired_paid_users = await session.scalar(
            select(func.count(User.id)).where(
                User.access_type == "paid",
                User.subscription_expiry.is_not(None),
                User.subscription_expiry <= now,
            )
        )
        active_access_rows = await session.scalar(
            select(func.count(VPNAccess.id)).where(VPNAccess.is_active.is_(True))
        )
        active_subscription_links = await session.scalar(
            select(func.count(UserSubscriptionLink.id)).where(
                UserSubscriptionLink.is_active.is_(True)
            )
        )
        total_traffic_used = await session.scalar(
            select(func.coalesce(func.sum(User.traffic_used), 0))
        )

    return {
        "users": {
            "total": total_users or 0,
            "active": active_users or 0,
            "paid": paid_users or 0,
            "free": free_users or 0,
            "trial": trial_users or 0,
            "none": none_access_users or 0,
            "expired_paid": expired_paid_users or 0,
        },
        "access": {
            "active_access_rows": active_access_rows or 0,
            "active_subscription_links": active_subscription_links or 0,
        },
        "traffic": {
            "total_used_mb": int(total_traffic_used or 0),
        },
        "generated_at": _dt(now),
    }


async def get_admin_users(
    *,
    limit: int | None = None,
    offset: int = 0,
    access_type: str | None = None,
    query: str | None = None,
    sort: str | None = None,
) -> dict[str, Any]:
    safe_limit = _safe_limit(limit, DEFAULT_USERS_LIMIT, MAX_USERS_LIMIT)
    safe_offset = max(0, min(offset, 10000))

    stmt = select(User)

    if access_type == "none":
        stmt = stmt.where(or_(User.access_type.is_(None), User.access_type == ""))
    elif access_type in {"paid", "free", "trial"}:
        stmt = stmt.where(User.access_type == access_type)

    clean_query = (query or "").strip()
    if clean_query:
        if clean_query.isdigit():
            stmt = stmt.where(User.telegram_id == int(clean_query))
        else:
            stmt = stmt.where(User.username.ilike(f"%{clean_query.lstrip('@')}%"))

    if sort == "traffic_desc":
        stmt = stmt.order_by(func.coalesce(User.traffic_used, 0).desc(), User.id.desc())
    else:
        stmt = stmt.order_by(User.id.desc())

    stmt = stmt.limit(safe_limit).offset(safe_offset)

    async with async_session_maker() as session:
        result = await session.execute(stmt)
        users = list(result.scalars().all())

        user_ids = [user.id for user in users]
        telegram_ids = [user.telegram_id for user in users]

        access_counts: dict[int, int] = {}
        if user_ids:
            counts_result = await session.execute(
                select(VPNAccess.user_id, func.count(VPNAccess.id))
                .where(
                    VPNAccess.user_id.in_(user_ids),
                    VPNAccess.is_active.is_(True),
                )
                .group_by(VPNAccess.user_id)
            )
            access_counts = {int(user_id): int(count) for user_id, count in counts_result.all()}

        latest_events: dict[int, UserEvent] = {}
        if telegram_ids:
            ranked_events = (
                select(
                    UserEvent.id.label("id"),
                    func.row_number()
                    .over(
                        partition_by=UserEvent.target_telegram_id,
                        order_by=(UserEvent.created_at.desc(), UserEvent.id.desc()),
                    )
                    .label("row_number"),
                )
                .where(UserEvent.target_telegram_id.in_(telegram_ids))
                .subquery()
            )
            events_result = await session.execute(
                select(UserEvent)
                .join(ranked_events, UserEvent.id == ranked_events.c.id)
                .where(ranked_events.c.row_number == 1)
            )
            latest_events = {
                int(event.target_telegram_id): event
                for event in events_result.scalars().all()
                if event.target_telegram_id is not None
            }

    return {
        "limit": safe_limit,
        "offset": safe_offset,
        "users": [
            serialize_user(
                user,
                active_access_count=access_counts.get(user.id, 0),
                last_event=latest_events.get(user.telegram_id),
            )
            for user in users
        ],
    }


async def get_admin_user_detail(telegram_id: int) -> dict[str, Any] | None:
    async with async_session_maker() as session:
        user_result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_result.scalar_one_or_none()

        if user is None:
            return None

        access_result = await session.execute(
            select(VPNAccess)
            .where(
                VPNAccess.user_id == user.id,
                VPNAccess.is_active.is_(True),
            )
            .order_by(VPNAccess.server_name.asc(), VPNAccess.device_name.asc(), VPNAccess.id.asc())
        )
        active_accesses = list(access_result.scalars().all())

        link_result = await session.execute(
            select(UserSubscriptionLink)
            .where(UserSubscriptionLink.user_id == user.id)
            .order_by(UserSubscriptionLink.id.desc())
            .limit(10)
        )
        links = list(link_result.scalars().all())

        events_result = await session.execute(
            select(UserEvent)
            .where(UserEvent.target_telegram_id == telegram_id)
            .order_by(UserEvent.created_at.desc(), UserEvent.id.desc())
            .limit(DEFAULT_EVENTS_LIMIT)
        )
        events = list(events_result.scalars().all())

    return {
        "user": serialize_user(
            user,
            active_access_count=len(active_accesses),
            last_event=events[0] if events else None,
        ),
        "active_accesses": [
            {
                "server_name": access.server_name,
                "device_name": access.device_name,
                "is_active": bool(access.is_active),
            }
            for access in active_accesses
        ],
        "subscription_links": {
            "exists": bool(links),
            "active_count": sum(1 for link in links if link.is_active),
            "items": [
                {
                    "is_active": bool(link.is_active),
                    "token_masked": mask_token(link.token),
                    "last_used_at": _dt(link.last_used_at),
                }
                for link in links
            ],
        },
        "recent_events": [serialize_event(event) for event in events],
    }


async def get_admin_user_events(telegram_id: int, limit: int | None = None) -> dict[str, Any]:
    safe_limit = _safe_limit(limit, DEFAULT_EVENTS_LIMIT, MAX_EVENTS_LIMIT)

    async with async_session_maker() as session:
        result = await session.execute(
            select(UserEvent)
            .where(UserEvent.target_telegram_id == telegram_id)
            .order_by(UserEvent.created_at.desc(), UserEvent.id.desc())
            .limit(safe_limit)
        )
        events = list(result.scalars().all())

    return {
        "telegram_id": telegram_id,
        "limit": safe_limit,
        "events": [serialize_event(event) for event in events],
    }


async def get_admin_traffic_summary() -> dict[str, Any]:
    async with async_session_maker() as session:
        total_result = await session.execute(
            select(
                func.count(User.id),
                func.coalesce(func.sum(User.traffic_used), 0),
                func.coalesce(func.sum(User.traffic_limit), 0),
            )
        )
        total_users, total_used_mb, total_limit_mb = total_result.one()

        access_type_expr = func.coalesce(User.access_type, "none")
        by_access_result = await session.execute(
            select(
                access_type_expr,
                func.count(User.id),
                func.coalesce(func.sum(User.traffic_used), 0),
                func.coalesce(func.sum(User.traffic_limit), 0),
            ).group_by(access_type_expr)
        )
        by_access_rows = by_access_result.all()

    return {
        "total_users": int(total_users or 0),
        "total_used_mb": int(total_used_mb or 0),
        "total_limit_mb": int(total_limit_mb or 0),
        "by_access_type": [
            {
                "access_type": row[0] or "none",
                "users": int(row[1] or 0),
                "traffic_used_mb": int(row[2] or 0),
                "traffic_limit_mb": int(row[3] or 0),
            }
            for row in by_access_rows
        ],
    }


async def get_admin_servers() -> dict[str, Any]:
    try:
        nodes = load_server_nodes()
    except (OSError, ServerRegistryError) as exc:
        return {
            "registry_available": False,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
            "servers": [],
        }

    return {
        "registry_available": True,
        "servers": [
            {
                "code": node.code,
                "display_name": node.display_name,
                "provider": node.provider,
                "enabled": bool(node.enabled),
                "priority": node.priority,
                "protocol": node.protocol,
                "network": node.network,
                "public_endpoint": node.endpoint,
            }
            for node in nodes
        ],
    }
