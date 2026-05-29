from __future__ import annotations

import html
import json
import os
from datetime import datetime
from typing import Any

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import select

from config.config import settings
from config.runtime import DEV_MODE
from db.database import async_session_maker
from db.models import User, UserEvent, VPNAccess
from services.audit_log_service import log_user_event
from services.vpn_service import VPNService
from services.panel_client import PanelClient
from services.server_registry import get_server_node, load_panel_credentials

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


async def get_traffic_sync_target_telegram_ids(limit: int = 100) -> list[int]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User.telegram_id)
            .join(VPNAccess, VPNAccess.user_id == User.id)
            .where(
                User.is_active.is_(True),
                User.access_type.in_(("free", "paid")),
                VPNAccess.is_active.is_(True),
            )
            .group_by(User.id, User.telegram_id)
            .order_by(User.id.asc())
            .limit(limit)
        )

        return [int(item) for item in result.scalars().all()]


async def _has_event(
    *,
    target_telegram_id: int,
    event_type: str,
) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserEvent.id)
            .where(
                UserEvent.target_telegram_id == target_telegram_id,
                UserEvent.event_type == event_type,
                UserEvent.status == "ok",
            )
            .limit(1)
        )

        return result.scalar_one_or_none() is not None


async def _send_user_traffic_message(
    *,
    telegram_id: int,
    text: str,
    event_type: str,
    source: str,
    details: dict[str, Any],
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if await _has_event(target_telegram_id=telegram_id, event_type=event_type):
        return

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    status = "ok"
    error: str | None = None

    try:
        await bot.send_message(telegram_id, text, reply_markup=reply_markup)
    except Exception as exc:
        status = "error"
        error = f"{type(exc).__name__}: {exc}"
    finally:
        await bot.session.close()

    event_details = dict(details)
    if error:
        event_details["error"] = error

    await log_user_event(
        event_type=event_type,
        target_telegram_id=telegram_id,
        actor_telegram_id=None,
        source=source,
        status=status,
        message="Free traffic notification sent" if status == "ok" else "Free traffic notification failed",
        details=event_details,
    )


async def _maybe_notify_free_traffic_thresholds(
    *,
    telegram_id: int,
    old_used_mb: int,
    snapshot: dict[str, Any],
    source: str,
) -> None:
    if snapshot.get("access_type") != "free":
        return

    limit_mb = int(snapshot.get("free_limit_mb") or DEFAULT_FREE_TRAFFIC_LIMIT_MB)
    used_mb = int(snapshot.get("traffic_used_mb") or 0)

    if limit_mb <= 0:
        return

    old_percent = (old_used_mb / limit_mb) * 100
    new_percent = (used_mb / limit_mb) * 100

    details = {
        "old_used_mb": old_used_mb,
        "used_mb": used_mb,
        "limit_mb": limit_mb,
        "left_mb": snapshot.get("free_left_mb"),
        "percent_used": snapshot.get("free_percent_used"),
    }

    if old_percent < 70 <= new_percent < 90:
        await _send_user_traffic_message(
            telegram_id=telegram_id,
            event_type="traffic_free_70_notified",
            source=source,
            details=details,
            text=(
                "⚠️ <b>Осталось меньше 1 ГБ бесплатного трафика</b>\n\n"
                "Бесплатный лимит почти израсходован. После 3 ГБ доступ остановится.\n\n"
                "Полный доступ снимает ограничение по трафику и открывает больше устройств."
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Тариф PRO 🤌",
                            callback_data="open_subscription",
                        )
                    ]
                ]
            ),
        )

    if old_percent < 90 <= new_percent < 100:
        await _send_user_traffic_message(
            telegram_id=telegram_id,
            event_type="traffic_free_90_notified",
            source=source,
            details=details,
            text=(
                "⚠️ <b>Бесплатный трафик почти закончился</b>\n\n"
                "Осталось совсем немного. После достижения лимита доступ остановится.\n\n"
                "Полный доступ — без лимита по трафику и с большим количеством устройств."
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Тариф PRO 🤌",
                            callback_data="open_subscription",
                        )
                    ]
                ]
            ),
        )


async def _notify_free_access_disabled(
    *,
    telegram_id: int,
    snapshot: dict[str, Any],
    source: str,
) -> None:
    await _send_user_traffic_message(
        telegram_id=telegram_id,
        event_type="traffic_free_disabled_notified",
        source=source,
        details=snapshot,
        text=(
            "⛔️ <b>Бесплатный лимит трафика закончился</b>\n\n"
            "Бесплатный доступ остановлен, потому что использовано 3 ГБ.\n\n"
            "Полный доступ — без лимита по трафику, с максимальной скоростью и большим количеством устройств."
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Тариф PRO 🤌",
                        callback_data="open_subscription",
                    )
                ]
            ]
        ),
    )


def _normalize_free_limit(value: int | None) -> int:
    if value is None or value <= 0:
        return DEFAULT_FREE_TRAFFIC_LIMIT_MB
    return int(value)


def _normalize_used(value: int | None) -> int:
    if value is None or value < 0:
        return 0
    return int(value)


def _month_start(dt: datetime | None = None) -> datetime:
    current = dt or datetime.utcnow()
    return current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _get_paid_period_used_mb(user: User, panel_total_mb: int) -> int:
    base_mb = _normalize_used(getattr(user, "traffic_period_base_mb", 0))
    return max(0, int(panel_total_mb) - base_mb)


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
        "traffic_period_started_at": user.traffic_period_started_at.isoformat() if user.traffic_period_started_at else None,
        "traffic_period_base_mb": _normalize_used(getattr(user, "traffic_period_base_mb", 0)),
        "traffic_period_panel_total_mb": _normalize_used(getattr(user, "traffic_period_panel_total_mb", 0)),
        "traffic_overuse_notified_at": user.traffic_overuse_notified_at.isoformat() if user.traffic_overuse_notified_at else None,

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


def _parse_json_dict(value: object | None) -> dict[str, Any]:
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    return {}


def _make_registry_panel_client(server) -> PanelClient:
    creds = load_panel_credentials(server)

    panel = object.__new__(PanelClient)
    panel.origin = server.panel_origin
    panel.base_path = server.panel_path
    panel.username = creds.username
    panel.password = creds.password
    panel.verify_ssl = False
    panel.timeout = _env_int("PANEL_TIMEOUT", default=20, minimum=3, maximum=120)

    return panel


def _stat_matches_access(stat: dict[str, Any], access: VPNAccess) -> bool:
    external_id = str(access.external_id or "")
    client_uuid = str(access.client_uuid or "")

    return bool(
        (external_id and str(stat.get("email", "")) == external_id)
        or (client_uuid and str(stat.get("uuid", "")) == client_uuid)
        or (client_uuid and str(stat.get("id", "")) == client_uuid)
    )


async def _get_client_traffic_from_inbound_raw(
    *,
    panel: PanelClient,
    inbound_id: int,
    access: VPNAccess,
) -> dict[str, Any]:
    raw = await panel.get_inbound_raw(inbound_id)

    stats = (
        raw.get("clientStats")
        or raw.get("client_stats")
        or raw.get("clientTraffics")
        or []
    )

    if isinstance(stats, list):
        for item in stats:
            if isinstance(item, dict) and _stat_matches_access(item, access):
                return item

    settings = _parse_json_dict(raw.get("settings"))
    clients = settings.get("clients") or []

    if isinstance(clients, list):
        for client in clients:
            if not isinstance(client, dict):
                continue

            if _stat_matches_access(client, access):
                # Some 3x-ui versions return clients in inbound settings but no traffic
                # row until traffic is recorded. Treat that as zero traffic, not sync failure.
                return {
                    "email": client.get("email") or access.external_id,
                    "uuid": client.get("id") or access.client_uuid,
                    "enable": bool(client.get("enable", True)),
                    "up": 0,
                    "down": 0,
                    "allTime": 0,
                }

    raise RuntimeError(
        f"client traffic not found in inbound raw: "
        f"inbound_id={inbound_id}, external_id={access.external_id}, uuid={access.client_uuid}"
    )


async def _get_client_traffic_for_access(
    *,
    panel: PanelClient,
    inbound_id: int,
    access: VPNAccess,
) -> dict[str, Any]:
    last_error: Exception | None = None

    if access.external_id:
        try:
            return await panel.get_client_traffic_by_email(access.external_id)
        except Exception as exc:
            last_error = exc

    if access.client_uuid:
        try:
            stats = await panel.get_client_traffic_by_uuid(access.client_uuid)
            for item in stats:
                if isinstance(item, dict) and _stat_matches_access(item, access):
                    return item
            if stats and isinstance(stats[0], dict):
                return stats[0]
        except Exception as exc:
            last_error = exc

    try:
        return await _get_client_traffic_from_inbound_raw(
            panel=panel,
            inbound_id=inbound_id,
            access=access,
        )
    except Exception as exc:
        if last_error is not None:
            raise last_error
        raise exc


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
    legacy_panel: PanelClient | None = None
    legacy_inbound_id = int(getattr(service, "inbound_id", 0) or 0)

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    total_bytes = 0

    for access in accesses:
        label = (
            f"access_id={access.id}, device={access.device_number}, "
            f"server={access.server_name or '-'}, external_id={_mask(access.external_id)}"
        )

        if not access.external_id:
            errors.append(label + " — no external_id")
            continue

        panel_label = "legacy"
        inbound_id = legacy_inbound_id

        try:
            server_name = (access.server_name or "").strip()

            if server_name and server_name not in {"main", "dev"}:
                server = get_server_node(server_name)
                panel = _make_registry_panel_client(server)
                inbound_id = int(server.inbound_id)
                panel_label = server.code
            else:
                if legacy_panel is None:
                    legacy_panel = service._get_panel_client()
                panel = legacy_panel

            stat = await _get_client_traffic_for_access(
                panel=panel,
                inbound_id=inbound_id,
                access=access,
            )
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
                "server_name": access.server_name,
                "panel": panel_label,
                "inbound_id": inbound_id,
                "external_id": _mask(access.external_id),
                "client_uuid": _mask(access.client_uuid),
                "panel_email": _mask(stat.get("email")),
                "panel_uuid": _mask(stat.get("uuid") or stat.get("id")),
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
    raw_panel_total_mb = int(panel_snapshot.get("total_mb") or 0)
    new_used_mb = raw_panel_total_mb
    synced_access_count = int(panel_snapshot.get("synced_access_count") or 0)

    if db_snapshot.get("access_type") == "paid":
        async with async_session_maker() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()

            if user is not None:
                now = datetime.utcnow()
                current_period_start = _month_start(now)

                if (
                    user.traffic_period_started_at is None
                    or user.traffic_period_started_at < current_period_start
                    or _normalize_used(user.traffic_period_panel_total_mb) > raw_panel_total_mb
                ):
                    user.traffic_period_started_at = current_period_start
                    user.traffic_period_base_mb = raw_panel_total_mb
                    user.traffic_period_panel_total_mb = raw_panel_total_mb
                    user.traffic_used = 0
                    user.traffic_overuse_notified_at = None
                    await session.commit()
                    await session.refresh(user)

                    old_used_mb = 0
                    db_snapshot = build_traffic_snapshot(user)

                new_used_mb = _get_paid_period_used_mb(user, raw_panel_total_mb)
                user.traffic_period_panel_total_mb = raw_panel_total_mb
                await session.commit()

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

    # Important: after free limit is reached, access records are disabled.
    # In that state panel total becomes 0 because there is nothing active to sync.
    # Do not overwrite the saved limit-reached traffic value with 0.
    if synced_access_count == 0 and new_used_mb == 0 and old_used_mb > 0:
        panel_snapshot["total_mb"] = old_used_mb
        panel_snapshot["total_gb"] = round(old_used_mb / 1024, 2)

        await log_user_event(
            event_type="traffic_panel_synced",
            target_telegram_id=telegram_id,
            actor_telegram_id=actor_telegram_id,
            source=source,
            status="ok",
            message="Panel traffic sync skipped because there are no active access records",
            details={
                "old_used_mb": old_used_mb,
                "new_used_mb": new_used_mb,
                "kept_used_mb": old_used_mb,
                "panel": panel_snapshot,
            },
        )

        return {
            "status": "ok",
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
            skipped.append(label + " — DEV_MODE, panel disable skipped")
            continue

        try:
            await service._get_panel_client().update_client_enable(
                inbound_id=service.inbound_id,
                client_id=str(client_uuid),
                enable=False,
            )
            deleted.append(label + " — panel client disabled")
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
            "panel_disabled": deleted,
            "skipped": skipped,
            "errors": errors,
            "disabled_access_ids": disabled_access_ids,
        },
    )

    await _notify_free_access_disabled(
        telegram_id=telegram_id,
        snapshot=updated_snapshot,
        source=source,
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

    if old_access_type == "free":
        await _maybe_notify_free_traffic_thresholds(
            telegram_id=telegram_id,
            old_used_mb=old_used,
            snapshot=snapshot,
            source=source,
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
        should_notify = True

        async with async_session_maker() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()

            if user is not None and user.traffic_overuse_notified_at is not None:
                period_start = user.traffic_period_started_at or _month_start()
                if user.traffic_overuse_notified_at >= period_start:
                    should_notify = False

            if user is not None and should_notify:
                user.traffic_overuse_notified_at = datetime.utcnow()
                await session.commit()

        if should_notify:
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

        if user.access_type == "paid":
            user.traffic_period_started_at = _month_start()
            user.traffic_period_base_mb = _normalize_used(user.traffic_period_panel_total_mb)
            user.traffic_overuse_notified_at = None

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
