from __future__ import annotations

import html
import os
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import select

from config.config import settings
from config.runtime import DEV_MODE
from db.database import async_session_maker
from db.models import User, VPNAccess
from services.audit_log_service import log_user_event
from services.vpn_service import VPNService

DEFAULT_FREE_TRAFFIC_LIMIT_MB = 3072
DEFAULT_PAID_OVERUSE_NOTIFY_MB = 153600  # 150 GB


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)

    if raw is None:
        return default

    try:
        value = int(raw)
    except ValueError:
        return default

    return max(minimum, min(value, maximum))


def _get_paid_overuse_notify_mb() -> int:
    return _env_int(
        "PAID_TRAFFIC_OVERUSE_NOTIFY_MB",
        default=DEFAULT_PAID_OVERUSE_NOTIFY_MB,
        minimum=1024,
        maximum=10 * 1024 * 1024,
    )


def _get_admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_TELEGRAM_IDS", "")
    result: set[int] = set()

    for item in raw.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.add(int(item))
        except ValueError:
            continue

    return result


def _normalize_free_limit(value: int | None) -> int:
    if value is None or value <= 0:
        return DEFAULT_FREE_TRAFFIC_LIMIT_MB
    return int(value)


def _normalize_used(value: int | None) -> int:
    if value is None or value < 0:
        return 0
    return int(value)


def build_traffic_snapshot(user: User) -> dict[str, Any]:
    used_mb = _normalize_used(user.traffic_used)
    free_limit_mb = _normalize_free_limit(user.traffic_limit)
    paid_overuse_notify_mb = _get_paid_overuse_notify_mb()

    free_left_mb = max(free_limit_mb - used_mb, 0)
    free_percent_used = round((used_mb / free_limit_mb) * 100, 2) if free_limit_mb > 0 else 0
    paid_threshold_percent = (
        round((used_mb / paid_overuse_notify_mb) * 100, 2)
        if paid_overuse_notify_mb > 0
        else 0
    )

    return {
        "user_id": user.id,
        "telegram_id": user.telegram_id,
        "access_type": user.access_type,
        "is_active": user.is_active,

        "traffic_used_mb": used_mb,
        "traffic_used_gb": round(used_mb / 1024, 2),

        "free_limit_mb": free_limit_mb,
        "free_limit_gb": round(free_limit_mb / 1024, 2),
        "free_left_mb": free_left_mb,
        "free_left_gb": round(free_left_mb / 1024, 2),
        "free_percent_used": free_percent_used,
        "free_limit_reached": user.access_type == "free" and used_mb >= free_limit_mb,

        "paid_overuse_notify_mb": paid_overuse_notify_mb,
        "paid_overuse_notify_gb": round(paid_overuse_notify_mb / 1024, 2),
        "paid_threshold_percent": paid_threshold_percent,
        "paid_overuse_reached": user.access_type == "paid" and used_mb >= paid_overuse_notify_mb,
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


def _mask(value: object | None, keep_start: int = 6, keep_end: int = 4) -> str:
    if value is None:
        return "-"

    raw = str(value)
    if not raw:
        return "-"

    if len(raw) <= keep_start + keep_end + 3:
        return raw

    return f"{raw[:keep_start]}...{raw[-keep_end:]}"


def _to_int(value: object | None) -> int:
    if value is None:
        return 0

    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _bytes_to_mb(value: int) -> int:
    return max(0, int(value) // (1024 * 1024))


async def collect_user_panel_traffic(telegram_id: int) -> dict[str, Any] | None:
    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()

        if user is None:
            return None

        access_result = await session.execute(
            select(VPNAccess)
            .where(
                VPNAccess.user_id == user.id,
                VPNAccess.is_active.is_(True),
            )
            .order_by(VPNAccess.device_number.asc(), VPNAccess.id.asc())
        )
        accesses = list(access_result.scalars().all())
        db_snapshot = build_traffic_snapshot(user)

    service = VPNService()
    panel = service._get_panel_client()

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    total_bytes = 0

    for access in accesses:
        label = f"access_id={access.id}, device={access.device_number}, external_id={_mask(access.external_id)}"

        if not access.external_id:
            errors.append(label + " — no external_id")
            continue

        try:
            stat = await panel.get_client_traffic_by_email(access.external_id)
        except Exception as exc:
            errors.append(label + f" — {type(exc).__name__}: {exc}")
            continue

        up_bytes = _to_int(stat.get("up"))
        down_bytes = _to_int(stat.get("down"))
        all_time_bytes = _to_int(stat.get("allTime"))
        current_total_bytes = up_bytes + down_bytes

        total_bytes += current_total_bytes

        records.append(
            {
                "access_id": access.id,
                "device_number": access.device_number,
                "external_id": _mask(access.external_id),
                "client_uuid": _mask(access.client_uuid),
                "panel_email": _mask(stat.get("email")),
                "panel_uuid": _mask(stat.get("uuid")),
                "enable": bool(stat.get("enable")),
                "up_bytes": up_bytes,
                "down_bytes": down_bytes,
                "all_time_bytes": all_time_bytes,
                "total_bytes": current_total_bytes,
                "total_mb": _bytes_to_mb(current_total_bytes),
                "last_online": _to_int(stat.get("lastOnline")),
            }
        )

    return {
        "telegram_id": telegram_id,
        "db_snapshot": db_snapshot,
        "records": records,
        "errors": errors,
        "active_access_count": len(accesses),
        "synced_access_count": len(records),
        "total_bytes": total_bytes,
        "total_mb": _bytes_to_mb(total_bytes),
        "total_gb": round(total_bytes / 1024 / 1024 / 1024, 2),
    }


async def sync_user_traffic_from_panel(
    telegram_id: int,
    *,
    actor_telegram_id: int | None = None,
    source: str = "panel_sync",
) -> dict[str, Any] | None:
    panel_snapshot = await collect_user_panel_traffic(telegram_id)

    if panel_snapshot is None:
        return None

    db_snapshot = panel_snapshot["db_snapshot"]
    old_used_mb = int(db_snapshot.get("traffic_used_mb") or 0)
    new_used_mb = int(panel_snapshot.get("total_mb") or 0)

    if panel_snapshot["errors"]:
        await log_user_event(
            event_type="traffic_panel_sync_failed",
            target_telegram_id=telegram_id,
            actor_telegram_id=actor_telegram_id,
            source=source,
            status="error",
            message="Panel traffic sync failed",
            details=panel_snapshot,
        )

        return {
            "status": "error",
            "updated": False,
            "snapshot": db_snapshot,
            "panel": panel_snapshot,
        }

    if new_used_mb == old_used_mb:
        await log_user_event(
            event_type="traffic_panel_synced",
            target_telegram_id=telegram_id,
            actor_telegram_id=actor_telegram_id,
            source=source,
            status="ok",
            message="Panel traffic synced without DB changes",
            details={
                "old_used_mb": old_used_mb,
                "new_used_mb": new_used_mb,
                "panel": panel_snapshot,
            },
        )

        return {
            "status": "ok",
            "updated": False,
            "snapshot": db_snapshot,
            "panel": panel_snapshot,
        }

    updated_snapshot = await set_user_traffic_used(
        telegram_id,
        new_used_mb,
        actor_telegram_id=actor_telegram_id,
        source=source,
    )

    await log_user_event(
        event_type="traffic_panel_synced",
        target_telegram_id=telegram_id,
        actor_telegram_id=actor_telegram_id,
        source=source,
        status="ok",
        message="Panel traffic synced and DB updated",
        details={
            "old_used_mb": old_used_mb,
            "new_used_mb": new_used_mb,
            "panel": panel_snapshot,
        },
    )

    return {
        "status": "ok",
        "updated": True,
        "snapshot": updated_snapshot,
        "panel": panel_snapshot,
    }


async def _notify_admins_paid_overuse(snapshot: dict[str, Any], source: str) -> None:
    admin_ids = _get_admin_ids()
    if not admin_ids:
        return

    text = (
        "⚠️ <b>Paid traffic overuse</b>\n\n"
        f"telegram_id: <code>{html.escape(str(snapshot.get('telegram_id')))}</code>\n"
        f"user_id: <code>{html.escape(str(snapshot.get('user_id')))}</code>\n"
        f"used: <code>{html.escape(str(snapshot.get('traffic_used_gb')))} GB</code>\n"
        f"threshold: <code>{html.escape(str(snapshot.get('paid_overuse_notify_gb')))} GB</code>\n"
        f"source: <code>{html.escape(source)}</code>"
    )

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    notified: list[int] = []
    failed: list[str] = []

    try:
        for admin_id in admin_ids:
            try:
                await bot.send_message(admin_id, text)
                notified.append(admin_id)
            except Exception as exc:
                failed.append(f"{admin_id}: {type(exc).__name__}: {exc}")
    finally:
        await bot.session.close()

    await log_user_event(
        event_type="traffic_paid_overuse_owner_notified",
        target_telegram_id=int(snapshot["telegram_id"]),
        source=source,
        status="ok" if notified else "error",
        message="Owner notification sent for paid traffic overuse",
        details={
            "notified": notified,
            "failed": failed,
            "snapshot": snapshot,
        },
    )


async def _disable_free_access_due_to_limit(
    telegram_id: int,
    *,
    actor_telegram_id: int | None,
    source: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()

        if user is None:
            return snapshot

        access_result = await session.execute(
            select(VPNAccess)
            .where(
                VPNAccess.user_id == user.id,
                VPNAccess.is_active.is_(True),
            )
            .order_by(VPNAccess.device_number.asc(), VPNAccess.id.asc())
        )
        active_accesses = list(access_result.scalars().all())

        access_payload = [
            {
                "access_id": access.id,
                "device_number": access.device_number,
                "client_uuid": access.client_uuid,
            }
            for access in active_accesses
        ]

    service = VPNService()
    deleted: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    for access in access_payload:
        client_uuid = access.get("client_uuid")
        label = f"access_id={access.get('access_id')}, device={access.get('device_number')}"

        if not client_uuid:
            skipped.append(label + " — no client_uuid")
            continue

        if DEV_MODE:
            skipped.append(label + " — DEV_MODE, panel delete skipped")
            continue

        try:
            await service._get_panel_client().delete_client(
                inbound_id=service.inbound_id,
                client_id=str(client_uuid),
            )
            deleted.append(label)
        except Exception as exc:
            errors.append(label + f" — {type(exc).__name__}: {exc}")

    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()

        if user is None:
            return snapshot

        access_result = await session.execute(
            select(VPNAccess)
            .where(VPNAccess.user_id == user.id)
            .order_by(VPNAccess.device_number.asc(), VPNAccess.id.asc())
        )
        accesses = list(access_result.scalars().all())

        disabled_access_ids: list[int] = []
        for access in accesses:
            if access.is_active:
                disabled_access_ids.append(access.id)
            access.is_active = False

        user.is_active = False
        user.device_limit = 1
        user.used_devices = 0

        await session.commit()
        await session.refresh(user)

        updated_snapshot = build_traffic_snapshot(user)

    await log_user_event(
        event_type="traffic_free_disabled",
        target_telegram_id=telegram_id,
        actor_telegram_id=actor_telegram_id,
        source=source,
        status="partial" if errors else "ok",
        message="Free access disabled because traffic limit was reached",
        details={
            "snapshot": updated_snapshot,
            "deleted": deleted,
            "skipped": skipped,
            "errors": errors,
            "disabled_access_ids": disabled_access_ids,
        },
    )

    return updated_snapshot


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
        old_access_type = user.access_type
        old_free_limit = _normalize_free_limit(user.traffic_limit)
        old_paid_threshold = _get_paid_overuse_notify_mb()

        user.traffic_used = normalized_used
        if user.traffic_limit is None or user.traffic_limit <= 0:
            user.traffic_limit = DEFAULT_FREE_TRAFFIC_LIMIT_MB

        await session.commit()
        await session.refresh(user)

        snapshot = build_traffic_snapshot(user)

    await log_user_event(
        event_type="traffic_updated",
        target_telegram_id=telegram_id,
        actor_telegram_id=actor_telegram_id,
        source=source,
        status="ok",
        message="Traffic usage updated",
        details={
            "access_type": old_access_type,
            "old_used_mb": old_used,
            "new_used_mb": normalized_used,
            "free_limit_mb": snapshot["free_limit_mb"],
            "paid_overuse_notify_mb": snapshot["paid_overuse_notify_mb"],
            "free_percent_used": snapshot["free_percent_used"],
            "paid_threshold_percent": snapshot["paid_threshold_percent"],
        },
    )

    if old_access_type == "free" and old_used < old_free_limit <= normalized_used:
        await log_user_event(
            event_type="traffic_free_limit_reached",
            target_telegram_id=telegram_id,
            actor_telegram_id=actor_telegram_id,
            source=source,
            status="warning",
            message="Free traffic limit reached",
            details=snapshot,
        )

        snapshot = await _disable_free_access_due_to_limit(
            telegram_id,
            actor_telegram_id=actor_telegram_id,
            source=source,
            snapshot=snapshot,
        )

    if old_access_type == "paid" and old_used < old_paid_threshold <= normalized_used:
        await log_user_event(
            event_type="traffic_paid_overuse_detected",
            target_telegram_id=telegram_id,
            actor_telegram_id=actor_telegram_id,
            source=source,
            status="warning",
            message="Paid traffic overuse threshold reached",
            details=snapshot,
        )
        await _notify_admins_paid_overuse(snapshot, source)

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
        event_type="traffic_reset",
        target_telegram_id=telegram_id,
        actor_telegram_id=actor_telegram_id,
        source=source,
        status="ok",
        message="Traffic usage reset",
        details={
            "access_type": snapshot.get("access_type"),
            "old_used_mb": old_used,
            "new_used_mb": 0,
            "free_limit_mb": snapshot["free_limit_mb"],
            "paid_overuse_notify_mb": snapshot["paid_overuse_notify_mb"],
        },
    )

    return snapshot
