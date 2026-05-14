from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from db.database import async_session_maker
from db.models import User, UserEvent, UserSubscriptionLink, VPNAccess
from services.audit_log_service import log_user_event
from services.panel_client import InboundClient
from services.vpn_service import VPNService

LEGACY_GRACE_DAYS = 3

PAID_EVENT = "legacy_migration_paid_notified"
FREE_EVENT = "legacy_migration_free_notified"
NO_ACCESS_EVENT = "legacy_migration_no_access_notified"


def _now() -> datetime:
    return datetime.utcnow()


def _mask(value: object | None, keep_start: int = 6, keep_end: int = 4) -> str:
    if value is None:
        return "-"

    raw = str(value)
    if not raw:
        return "-"

    if len(raw) <= keep_start + keep_end + 3:
        return raw

    return f"{raw[:keep_start]}...{raw[-keep_end:]}"


def _client_tg_id(client: InboundClient) -> int | None:
    try:
        return int(str(client.tg_id).strip())
    except (TypeError, ValueError):
        return None


def _event_type_for_category(category: str) -> str:
    if category == "paid_legacy":
        return PAID_EVENT
    if category == "free_legacy":
        return FREE_EVENT
    return NO_ACCESS_EVENT


def _notification_text(category: str) -> str:
    if category == "paid_legacy":
        return (
            "👋 <b>Пожалуйста, обновите подключение</b>\n\n"
            "Мы переводим VOID на новый формат через подписочную ссылку, чтобы сервис было проще поддерживать, "
            "а вам — удобнее получать актуальную конфигурацию без ручной замены ключей.\n\n"
            "Ваш доступ остаётся активным, нужно только один раз добавить подписку заново в Happ или любой другой удобный клиент.\n\n"
            f"Старый способ подключения будет работать ещё <b>{LEGACY_GRACE_DAYS} дня</b>, "
            "чтобы вы спокойно успели перейти на новый формат 🫡"
        )

    if category == "free_legacy":
        return (
            "👋 <b>Пожалуйста, обновите подключение</b>\n\n"
            "Мы обновляем формат VOID через подписочную ссылку, чтобы подключение было удобнее для пользователей "
            "и проще в поддержке для нас.\n\n"
            f"Бесплатный доступ остаётся доступен, но старый способ подключения будет работать ещё <b>{LEGACY_GRACE_DAYS} дня</b>.\n\n"
            "Добавьте подписку заново в Happ или любой другой удобный клиент, "
            "а если хотите больше скорости и трафика — переходите на полный доступ 🫡"
        )

    return (
        "👋 <b>Вы уже запускали VOID</b>\n\n"
        "Доступ пока не активирован, но можно сразу подключить полный доступ и пользоваться VOID без лимита трафика.\n\n"
        "Мы как раз улучшаем сервис, чтобы подключение было проще, стабильнее и удобнее для вас 🫡"
    )


def _notification_keyboard(category: str) -> InlineKeyboardMarkup:
    if category == "paid_legacy":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔗 Добавить конфигурацию",
                        callback_data="open_subscription_link",
                    )
                ]
            ]
        )

    if category == "free_legacy":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔗 Добавить конфигурацию",
                        callback_data="open_subscription_link",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Тариф PRO 🤌",
                        callback_data="open_subscription",
                    )
                ],
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Тариф PRO 🤌",
                    callback_data="open_subscription",
                )
            ]
        ]
    )


async def _already_notified(telegram_id: int, event_type: str) -> bool:
    terminal_error_markers = (
        "bot was blocked by the user",
        "user is deactivated",
        "chat not found",
        "user not found",
    )

    async with async_session_maker() as session:
        result = await session.execute(
            select(UserEvent.status, UserEvent.message)
            .where(
                UserEvent.target_telegram_id == telegram_id,
                UserEvent.event_type == event_type,
            )
            .order_by(UserEvent.created_at.desc(), UserEvent.id.desc())
            .limit(20)
        )
        rows = list(result.all())

    for status, message in rows:
        if status == "ok":
            return True

        message_text = str(message or "").lower()
        if status == "error" and any(marker in message_text for marker in terminal_error_markers):
            return True

    return False


async def _load_user_and_active_accesses(
    telegram_id: int,
) -> tuple[User | None, list[VPNAccess]]:
    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()

        if user is None:
            return None, []

        access_result = await session.execute(
            select(VPNAccess)
            .where(
                VPNAccess.user_id == user.id,
                VPNAccess.is_active.is_(True),
            )
            .order_by(VPNAccess.device_number.asc(), VPNAccess.id.asc())
        )
        accesses = list(access_result.scalars().all())

        return user, accesses


async def _get_enabled_panel_clients_by_tg_id(telegram_id: int) -> list[InboundClient]:
    service = VPNService()
    inbound = await service._get_panel_client().get_inbound_info(service.inbound_id)

    result: list[InboundClient] = []
    for client in inbound.clients:
        if not client.enable:
            continue

        if _client_tg_id(client) == telegram_id:
            result.append(client)

    return result


def _build_client_payload(client: InboundClient, is_current: bool) -> dict[str, Any]:
    return {
        "email": _mask(client.email),
        "uuid": _mask(client.id),
        "tg_id": client.tg_id,
        "enable": client.enable,
        "is_current": is_current,
    }


async def get_legacy_migration_snapshot(telegram_id: int) -> dict[str, Any]:
    user, active_accesses = await _load_user_and_active_accesses(telegram_id)

    if user is None:
        return {
            "user_found": False,
            "telegram_id": telegram_id,
            "category": None,
            "should_notify": False,
            "message": "User not found",
        }

    active_emails = {access.external_id for access in active_accesses if access.external_id}
    active_uuids = {access.client_uuid for access in active_accesses if access.client_uuid}

    async with async_session_maker() as session:
        links_result = await session.execute(
            select(UserSubscriptionLink)
            .where(UserSubscriptionLink.user_id == user.id)
            .order_by(UserSubscriptionLink.id.asc())
        )
        subscription_links = list(links_result.scalars().all())

    active_subscription_links = [link for link in subscription_links if link.is_active]
    used_subscription_links = [
        link for link in active_subscription_links
        if link.last_used_at is not None or link.migrated_at is not None
    ]
    needs_subscription_migration = len(used_subscription_links) == 0

    panel_clients = await _get_enabled_panel_clients_by_tg_id(telegram_id)

    current_clients: list[dict[str, Any]] = []
    legacy_clients: list[dict[str, Any]] = []

    for client in panel_clients:
        is_current = client.email in active_emails or client.id in active_uuids
        payload = _build_client_payload(client, is_current)

        if is_current:
            current_clients.append(payload)
        else:
            legacy_clients.append(payload)

    access_type = user.access_type
    has_legacy = len(legacy_clients) > 0

    category: str | None = None
    should_notify = False

    if access_type == "paid" and (has_legacy or needs_subscription_migration):
        category = "paid_legacy"
        should_notify = True
    elif access_type == "free" and (has_legacy or needs_subscription_migration):
        category = "free_legacy"
        should_notify = True
    elif access_type not in {"free", "paid"}:
        category = "no_access"
        should_notify = True

    event_type = _event_type_for_category(category) if category else None
    already_notified = await _already_notified(telegram_id, event_type) if event_type else False

    return {
        "user_found": True,
        "user_id": user.id,
        "telegram_id": telegram_id,
        "access_type": access_type,
        "is_active": user.is_active,
        "category": category,
        "should_notify": should_notify,
        "already_notified": already_notified,
        "event_type": event_type,
        "legacy_grace_days": LEGACY_GRACE_DAYS,
        "legacy_disable_after": (_now() + timedelta(days=LEGACY_GRACE_DAYS)).isoformat(),
        "active_db_access_count": len(active_accesses),
        "subscription_link_count": len(subscription_links),
        "active_subscription_link_count": len(active_subscription_links),
        "used_subscription_link_count": len(used_subscription_links),
        "needs_subscription_migration": needs_subscription_migration,
        "panel_client_count": len(panel_clients),
        "current_panel_client_count": len(current_clients),
        "legacy_panel_client_count": len(legacy_clients),
        "current_clients": current_clients,
        "legacy_clients": legacy_clients,
    }


async def notify_legacy_migration_user(
    telegram_id: int,
    *,
    bot: Bot,
    actor_telegram_id: int | None = None,
    source: str = "admin_legacy_notify",
    force: bool = False,
) -> dict[str, Any]:
    snapshot = await get_legacy_migration_snapshot(telegram_id)

    if not snapshot.get("user_found"):
        return {
            **snapshot,
            "status": "not_found",
            "sent": False,
        }

    if not snapshot.get("should_notify"):
        return {
            **snapshot,
            "status": "skipped",
            "sent": False,
            "message": "No legacy migration notification needed",
        }

    if snapshot.get("already_notified") and not force:
        return {
            **snapshot,
            "status": "already_notified",
            "sent": False,
            "message": "User was already notified",
        }

    category = snapshot["category"]
    event_type = snapshot["event_type"]

    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=_notification_text(category),
            reply_markup=_notification_keyboard(category),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as exc:
        await log_user_event(
            event_type=event_type,
            target_telegram_id=telegram_id,
            actor_telegram_id=actor_telegram_id,
            source=source,
            status="error",
            message=f"Legacy migration notification failed: {type(exc).__name__}: {exc}",
            details=snapshot,
        )
        return {
            **snapshot,
            "status": "error",
            "sent": False,
            "message": f"{type(exc).__name__}: {exc}",
        }

    await log_user_event(
        event_type=event_type,
        target_telegram_id=telegram_id,
        actor_telegram_id=actor_telegram_id,
        source=source,
        status="ok",
        message="Legacy migration notification sent",
        details=snapshot,
    )

    return {
        **snapshot,
        "status": "ok",
        "sent": True,
        "message": "Notification sent",
    }


async def collect_legacy_migration_candidates(limit: int = 50) -> list[int]:
    safe_limit = max(1, min(int(limit), 500))

    async with async_session_maker() as session:
        users_result = await session.execute(
            select(User)
            .where(
                User.access_type.in_(["free", "paid"]),
                User.is_active.is_(True),
            )
            .order_by(User.id.asc())
            .limit(10000)
        )
        users = list(users_result.scalars().all())

    result: list[int] = []
    now = _now()

    for user in users:
        if user.access_type == "paid":
            if not user.subscription_expiry or user.subscription_expiry <= now:
                continue

        snapshot = await get_legacy_migration_snapshot(user.telegram_id)

        if snapshot.get("already_notified"):
            continue

        if snapshot.get("category") not in {"paid_legacy", "free_legacy"}:
            continue

        if not snapshot.get("should_notify"):
            continue

        legacy_panel_client_count = int(snapshot.get("legacy_panel_client_count") or 0)

        if legacy_panel_client_count <= 0:
            continue

        result.append(user.telegram_id)

        if len(result) >= safe_limit:
            break

    return result[:safe_limit]


async def notify_legacy_migration_batch(
    *,
    bot: Bot,
    limit: int = 50,
    actor_telegram_id: int | None = None,
    source: str = "admin_legacy_notify_all",
) -> dict[str, Any]:
    candidates = await collect_legacy_migration_candidates(limit=limit)

    results: list[dict[str, Any]] = []
    for telegram_id in candidates:
        result = await notify_legacy_migration_user(
            telegram_id,
            bot=bot,
            actor_telegram_id=actor_telegram_id,
            source=source,
            force=False,
        )
        results.append(result)

    return {
        "checked_at": _now().isoformat(),
        "limit": limit,
        "found": len(candidates),
        "processed": len(results),
        "sent": len([item for item in results if item.get("sent")]),
        "skipped": len([item for item in results if not item.get("sent")]),
        "results": results,
    }
