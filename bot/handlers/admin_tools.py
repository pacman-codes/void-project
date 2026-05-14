from __future__ import annotations

import os
import html
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy import select

from config.runtime import DEV_MODE
from db.database import async_session_maker
from db.models import User, UserSubscriptionLink, VPNAccess
from services.vpn_service import VPNService, VPNServiceError
from services.audit_log_service import get_recent_user_events, log_user_event
from services.expiry_service import expire_paid_users_once
from services.traffic_service import (
    get_user_traffic_snapshot,
    reset_user_traffic,
    set_user_traffic_used,
    sync_user_traffic_from_panel,
)
from services.referral_service import get_referral_summary
from services.legacy_migration_service import (
    collect_legacy_migration_candidates,
    get_legacy_migration_snapshot,
    notify_legacy_migration_batch,
    notify_legacy_migration_user,
)

router = Router()


def get_admin_ids() -> set[int]:
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


def is_admin(message: Message) -> bool:
    if not message.from_user:
        return False
    return message.from_user.id in get_admin_ids()


def parse_admin_args(message: Message) -> list[str]:
    text = message.text or ""
    parts = text.split()
    return parts[1:]


def parse_target_and_days(message: Message, default_days: int = 30) -> tuple[int, int]:
    args = parse_admin_args(message)
    sender_id = message.from_user.id

    if not args:
        return sender_id, default_days

    if len(args) == 1:
        value = int(args[0])

        if value > 100000:
            return value, default_days

        return sender_id, value

    return int(args[0]), int(args[1])


def parse_target(message: Message) -> int:
    args = parse_admin_args(message)

    if not args:
        return message.from_user.id

    return int(args[0])


async def get_or_create_user(telegram_id: int, message: Message | None = None) -> User:
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()

        if user:
            return user

        user = User(
            telegram_id=telegram_id,
            username=message.from_user.username if message and message.from_user else None,
            first_name=message.from_user.first_name if message and message.from_user else None,
            last_name=message.from_user.last_name if message and message.from_user else None,
            language="ru",
            is_active=False,
            access_type=None,
            payment_devices_to_add=0,
            device_limit=1,
            used_devices=0,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        return user


async def set_user_paid(telegram_id: int, days: int, message: Message) -> None:
    if days < 1 or days > 730:
        raise ValueError("days must be between 1 and 730")

    await get_or_create_user(telegram_id, message)

    expires_at = datetime.utcnow() + timedelta(days=days)

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one()

        user.access_type = "paid"
        user.is_active = True
        user.subscription_expiry = expires_at
        user.device_limit = max(user.device_limit or 0, 2)
        user.payment_status = None
        user.payment_id = None
        user.payment_kind = None
        user.payment_plan_code = None
        user.payment_devices_to_add = 0
        user.payment_confirmation_url = None

        await session.commit()

    service = VPNService()
    await service.ensure_vpn_access_record(
        telegram_id=telegram_id,
        device_number=1,
        device_name="Устройство 1",
    )


    await log_user_event(
        event_type="admin_paid",
        target_telegram_id=telegram_id,
        actor_telegram_id=message.from_user.id if message.from_user else None,
        source="admin_tools",
        status="ok",
        message="Paid access activated by admin",
        details={
            "days": days,
            "expires_at": expires_at.isoformat(),
            "device_limit": 2,
        },
    )


async def set_user_free(telegram_id: int, message: Message) -> None:
    await get_or_create_user(telegram_id, message)

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one()

        user.access_type = "free"
        user.is_active = True
        user.subscription_expiry = None
        user.device_limit = 1
        user.payment_status = None
        user.payment_id = None
        user.payment_kind = None
        user.payment_plan_code = None
        user.payment_devices_to_add = 0
        user.payment_confirmation_url = None

        await session.commit()

    service = VPNService()
    await service.ensure_vpn_access_record(
        telegram_id=telegram_id,
        device_number=1,
        device_name="Устройство 1",
    )

    await log_user_event(
        event_type="admin_free",
        target_telegram_id=telegram_id,
        actor_telegram_id=message.from_user.id if message.from_user else None,
        source="admin_tools",
        status="ok",
        message="Free access activated by admin",
        details={
            "device_limit": 1,
        },
    )


async def reset_user_profile(telegram_id: int, message: Message) -> None:
    await get_or_create_user(telegram_id, message)

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one()

        user.access_type = None
        user.is_active = False
        user.subscription_expiry = None
        user.terms_accepted = False
        user.terms_accepted_at = None
        user.payment_status = None
        user.payment_id = None
        user.payment_kind = None
        user.payment_plan_code = None
        user.payment_devices_to_add = 0
        user.payment_confirmation_url = None
        user.payment_promo_code = None
        user.promo_applied = False
        user.promo_type = None
        user.partner_offer_code = None
        user.partner_offer_used = False
        user.device_limit = 1
        user.used_devices = 0

        access_result = await session.execute(
            select(VPNAccess).where(VPNAccess.user_id == user.id)
        )
        for access in access_result.scalars().all():
            access.is_active = False

        link_result = await session.execute(
            select(UserSubscriptionLink).where(UserSubscriptionLink.user_id == user.id)
        )
        for link in link_result.scalars().all():
            link.is_active = False

        await session.commit()

    await log_user_event(
        event_type="admin_reset",
        target_telegram_id=telegram_id,
        actor_telegram_id=message.from_user.id if message.from_user else None,
        source="admin_tools",
        status="ok",
        message="User profile reset by admin",
    )




async def collect_cleanup_targets(telegram_id: int) -> tuple[User | None, list[VPNAccess]]:
    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()

        if user is None:
            return None, []

        access_result = await session.execute(
            select(VPNAccess)
            .where(VPNAccess.user_id == user.id)
            .order_by(VPNAccess.device_number.asc(), VPNAccess.id.asc())
        )
        accesses = list(access_result.scalars().all())

        return user, accesses


def build_cleanup_preview_text(
    telegram_id: int,
    user: User | None,
    accesses: list[VPNAccess],
) -> str:
    if user is None:
        return f"Пользователь не найден\ntelegram_id: {telegram_id}"

    lines = [
        "🧹 <b>Panel cleanup check</b>",
        "",
        f"telegram_id: <code>{telegram_id}</code>",
        f"user_id: <code>{user.id}</code>",
        f"username: <code>{user.username or '-'}</code>",
        f"access_type: <code>{user.access_type or '-'}</code>",
        "",
    ]

    if not accesses:
        lines.append("VPNAccess записей нет.")
        return "\n".join(lines)

    lines.append("Будут затронуты только DB-записи этого пользователя:")
    lines.append("")

    for access in accesses:
        lines.extend(
            [
                f"• device_number: <code>{access.device_number}</code>",
                f"  access_id: <code>{access.id}</code>",
                f"  active: <code>{access.is_active}</code>",
                f"  server_name: <code>{access.server_name or '-'}</code>",
                f"  external_id: <code>{h(mask_value(access.external_id))}</code>",
                f"  client_uuid: <code>{h(mask_value(access.client_uuid))}</code>",
                "",
            ]
        )

    lines.append("Для реального удаления: /adminClean " + str(telegram_id))
    return "\n".join(lines)


async def cleanup_user_panel_and_db(telegram_id: int, actor_telegram_id: int | None = None) -> dict:
    user, accesses = await collect_cleanup_targets(telegram_id)

    if user is None:
        return {
            "user_found": False,
            "telegram_id": telegram_id,
            "deleted": [],
            "skipped": [],
            "errors": [],
        }

    service = VPNService()
    deleted: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    for access in accesses:
        label = (
            f"access_id={access.id}, "
            f"device={access.device_number}, "
            f"external_id={access.external_id or '-'}, "
            f"client_uuid={access.client_uuid or '-'}"
        )

        if not access.client_uuid:
            skipped.append(label + " — no client_uuid")
            continue

        if DEV_MODE:
            skipped.append(label + " — DEV_MODE, panel delete skipped")
            continue

        try:
            await service._get_panel_client().delete_client(
                inbound_id=service.inbound_id,
                client_id=access.client_uuid,
            )
            deleted.append(label)
        except Exception as exc:
            errors.append(label + f" — {type(exc).__name__}: {exc}")

    if errors:
        return {
            "user_found": True,
            "telegram_id": telegram_id,
            "deleted": deleted,
            "skipped": skipped,
            "errors": errors,
        }

    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        db_user = user_result.scalar_one_or_none()

        if db_user is not None:
            access_result = await session.execute(
                select(VPNAccess).where(VPNAccess.user_id == db_user.id)
            )
            for access in access_result.scalars().all():
                access.is_active = False

            link_result = await session.execute(
                select(UserSubscriptionLink).where(UserSubscriptionLink.user_id == db_user.id)
            )
            for link in link_result.scalars().all():
                link.is_active = False

            db_user.used_devices = 0

        await session.commit()

    await log_user_event(
        event_type="admin_clean",
        target_telegram_id=telegram_id,
        actor_telegram_id=actor_telegram_id,
        source="admin_tools",
        status="ok",
        message="Panel and DB access cleanup completed by admin",
        details={
            "deleted_count": len(deleted),
            "skipped_count": len(skipped),
            "error_count": len(errors),
        },
    )

    return {
        "user_found": True,
        "telegram_id": telegram_id,
        "deleted": deleted,
        "skipped": skipped,
        "errors": errors,
    }




def mask_value(value: object | None, keep_start: int = 6, keep_end: int = 4) -> str:
    if value is None:
        return "-"

    raw = str(value)
    if not raw:
        return "-"

    if len(raw) <= keep_start + keep_end + 3:
        return raw

    return f"{raw[:keep_start]}...{raw[-keep_end:]}"


def format_dt(value: datetime | None) -> str:
    if value is None:
        return "-"

    return value.strftime("%Y-%m-%d %H:%M:%S UTC")


def format_time_left(expiry: datetime | None) -> str:
    if expiry is None:
        return "-"

    delta = expiry - datetime.utcnow()
    total_seconds = int(delta.total_seconds())

    if total_seconds <= 0:
        return "expired"

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    if days > 0:
        return f"{days}d {hours}h"

    if hours > 0:
        return f"{hours}h {minutes}m"

    return f"{minutes}m"


def h(value: object | None) -> str:
    if value is None:
        return "-"

    raw = str(value)
    if not raw:
        return "-"

    return html.escape(raw)


def bool_h(value: bool | None) -> str:
    return "yes" if value else "no"


async def load_admin_user_snapshot(
    telegram_id: int,
) -> tuple[User | None, list[VPNAccess], list[UserSubscriptionLink]]:
    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()

        if user is None:
            return None, [], []

        access_result = await session.execute(
            select(VPNAccess)
            .where(VPNAccess.user_id == user.id)
            .order_by(VPNAccess.device_number.asc(), VPNAccess.id.asc())
        )
        accesses = list(access_result.scalars().all())

        link_result = await session.execute(
            select(UserSubscriptionLink)
            .where(UserSubscriptionLink.user_id == user.id)
            .order_by(UserSubscriptionLink.id.asc())
        )
        links = list(link_result.scalars().all())

        return user, accesses, links


def build_admin_user_text(
    telegram_id: int,
    user: User | None,
    accesses: list[VPNAccess],
    links: list[UserSubscriptionLink],
) -> str:
    if user is None:
        return f"User not found: <code>{telegram_id}</code>"

    active_accesses = [access for access in accesses if access.is_active]
    inactive_accesses = [access for access in accesses if not access.is_active]
    active_links = [link for link in links if link.is_active]
    inactive_links = [link for link in links if not link.is_active]

    lines = [
        "👤 <b>Admin user</b>",
        "",
        f"db_user_id: <code>{user.id}</code>",
        f"telegram_id: <code>{user.telegram_id}</code>",
        f"username: <code>{h(user.username)}</code>",
        f"first_name: <code>{h(user.first_name)}</code>",
        f"last_name: <code>{h(user.last_name)}</code>",
        f"language: <code>{h(user.language)}</code>",
        "",
        f"is_active: <code>{bool_h(user.is_active)}</code>",
        f"access_type: <code>{h(user.access_type)}</code>",
        f"subscription_expiry: <code>{format_dt(user.subscription_expiry)}</code>",
        f"time_left: <code>{format_time_left(user.subscription_expiry)}</code>",
        "",
        f"traffic_used: <code>{user.traffic_used}</code>",
        f"traffic_limit: <code>{h(user.traffic_limit)}</code>",
        f"device_limit: <code>{user.device_limit}</code>",
        f"used_devices: <code>{user.used_devices}</code>",
        "",
        f"payment_status: <code>{h(user.payment_status)}</code>",
        f"payment_id: <code>{h(mask_value(user.payment_id))}</code>",
        f"payment_kind: <code>{h(user.payment_kind)}</code>",
        f"payment_plan_code: <code>{h(user.payment_plan_code)}</code>",
        f"payment_devices_to_add: <code>{user.payment_devices_to_add}</code>",
        f"first_paid_at: <code>{format_dt(user.first_paid_at)}</code>",
        "",
        f"payment_promo_code: <code>{h(user.payment_promo_code)}</code>",
        f"promo_applied: <code>{bool_h(user.promo_applied)}</code>",
        f"promo_type: <code>{h(user.promo_type)}</code>",
        f"partner_offer_code: <code>{h(user.partner_offer_code)}</code>",
        f"partner_offer_used: <code>{bool_h(user.partner_offer_used)}</code>",
        "",
        f"terms_accepted: <code>{bool_h(user.terms_accepted)}</code>",
        f"terms_accepted_at: <code>{format_dt(user.terms_accepted_at)}</code>",
        "",
        "🔑 <b>VPN access</b>",
        f"total: <code>{len(accesses)}</code>, active: <code>{len(active_accesses)}</code>, inactive: <code>{len(inactive_accesses)}</code>",
    ]

    if accesses:
        lines.append("")
        for access in accesses[:10]:
            lines.extend(
                [
                    f"• access_id: <code>{access.id}</code>",
                    f"  server_name: <code>{h(access.server_name)}</code>",
                    f"  device: <code>{access.device_number}</code> / <code>{h(access.device_name)}</code>",
                    f"  active: <code>{bool_h(access.is_active)}</code>",
                    f"  external_id: <code>{h(mask_value(access.external_id))}</code>",
                    f"  client_uuid: <code>{h(mask_value(access.client_uuid))}</code>",
                    f"  config_url: <code>{'present' if access.config_url else 'empty'}</code>",
                    f"  created_at: <code>{format_dt(access.created_at)}</code>",
                    f"  updated_at: <code>{format_dt(access.updated_at)}</code>",
                    "",
                ]
            )

        if len(accesses) > 10:
            lines.append(f"...and {len(accesses) - 10} more VPNAccess records")
            lines.append("")

    lines.extend(
        [
            "🔗 <b>Subscription links</b>",
            f"total: <code>{len(links)}</code>, active: <code>{len(active_links)}</code>, inactive: <code>{len(inactive_links)}</code>",
        ]
    )

    if links:
        lines.append("")
        for link in links[:10]:
            lines.extend(
                [
                    f"• link_id: <code>{link.id}</code>",
                    f"  active: <code>{bool_h(link.is_active)}</code>",
                    f"  token: <code>{h(mask_value(link.token))}</code>",
                    f"  created_at: <code>{format_dt(link.created_at)}</code>",
                    f"  last_used_at: <code>{format_dt(link.last_used_at)}</code>",
                    f"  migrated_at: <code>{format_dt(link.migrated_at)}</code>",
                    f"  raw_disable_after: <code>{format_dt(link.raw_disable_after)}</code>",
                    f"  token_rotated_at: <code>{format_dt(link.token_rotated_at)}</code>",
                    "",
                ]
            )

        if len(links) > 10:
            lines.append(f"...and {len(links) - 10} more subscription links")

    text = "\n".join(lines).strip()

    if len(text) > 3900:
        text = text[:3800].rstrip() + "\n\n...truncated"

    return text




def build_admin_help_text() -> str:
    return (
        "🛠 <b>Admin commands</b>\n\n"
        "<b>User</b>\n"
        "/adminUser [telegram_id]\n"
        "Показать безопасный summary пользователя.\n\n"
        "/adminEvents [telegram_id] [limit]\n"
        "Показать историю событий пользователя.\n\n"
        "<b>Access</b>\n"
        "/adminPaid [telegram_id] [days]\n"
        "Вручную активировать paid.\n\n"
        "/adminFree [telegram_id]\n"
        "Вручную активировать free.\n\n"
        "/adminRes [telegram_id]\n"
        "Сбросить профиль пользователя.\n\n"
        "<b>Cleanup</b>\n"
        "/adminCleanCheck [telegram_id]\n"
        "Предпросмотр cleanup без удаления.\n\n"
        "/adminClean [telegram_id]\n"
        "Отключить DB-доступы/subscription links и почистить panel clients.\n\n"
        "<b>Traffic</b>\n"
        "/adminTraffic [telegram_id]\n"
        "Показать трафик пользователя.\n\n"
        "/adminTrafficSet [telegram_id] [used_mb]\n"
        "Вручную установить использованный трафик.\n\n"
        "/adminTrafficReset [telegram_id]\n"
        "Сбросить использованный трафик.\n\n"
        "<b>Expiry</b>\n"
        "/adminExpireCheck [limit]\n"
        "Проверить истёкшие paid без изменений.\n\n"
        "/adminExpireRun [limit]\n"
        "Перевести истёкшие paid в free.\n\n"
        "<b>Examples</b>\n"
        "<code>/adminUser 1600207976</code>\n"
        "<code>/adminEvents 1600207976 20</code>\n"
        "<code>/adminPaid 1600207976 30</code>"
    )


@router.message(F.text.regexp(r"^/adminHelp(?:@\w+)?(?:\s|$)"))
async def admin_help_command(message: Message) -> None:
    if not is_admin(message):
        return

    await message.answer(build_admin_help_text(), parse_mode="HTML")


@router.message(F.text.regexp(r"^/adminUser(?:@\w+)?(?:\s|$)"))
async def admin_user_command(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        telegram_id = parse_target(message)
    except ValueError:
        await message.answer("Формат: /adminUser &lt;telegram_id&gt;")
        return

    try:
        user, accesses, links = await load_admin_user_snapshot(telegram_id)
        await log_user_event(
            event_type="admin_user_lookup",
            target_telegram_id=telegram_id,
            actor_telegram_id=message.from_user.id if message.from_user else None,
            user_id=user.id if user else None,
            source="admin_tools",
            status="ok" if user else "not_found",
            message="Admin user lookup",
        )
        await message.answer(build_admin_user_text(telegram_id, user, accesses, links))
    except Exception as exc:
        await message.answer(f"Ошибка adminUser: {type(exc).__name__}: {html.escape(str(exc))}")




def build_admin_events_text(telegram_id: int, events: list) -> str:
    if not events:
        return f"📜 <b>Admin events</b>\n\ntelegram_id: <code>{telegram_id}</code>\nСобытий нет."

    lines = [
        "📜 <b>Admin events</b>",
        "",
        f"telegram_id: <code>{telegram_id}</code>",
        f"events: <code>{len(events)}</code>",
        "",
    ]

    max_total_len = 3600

    for event in events:
        details = event.details_json or "-"
        if len(details) > 140:
            details = details[:140].rstrip() + "..."

        item_lines = [
            f"• <code>{format_dt(event.created_at)}</code>",
            f"  type: <code>{h(event.event_type)}</code>",
            f"  status: <code>{h(event.status)}</code>",
            f"  actor: <code>{h(event.actor_telegram_id)}</code>",
            f"  source: <code>{h(event.source)}</code>",
            f"  message: <code>{h(event.message)}</code>",
            f"  details: <code>{h(details)}</code>",
            "",
        ]

        candidate = "\n".join(lines + item_lines).strip()
        if len(candidate) > max_total_len:
            lines.append("...truncated")
            break

        lines.extend(item_lines)

    return "\n".join(lines).strip()


@router.message(F.text.regexp(r"^/adminEvents(?:@\w+)?(?:\s|$)"))
async def admin_events_command(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        args = parse_admin_args(message)

        if not args:
            if not message.from_user:
                await message.answer("Формат: /adminEvents &lt;telegram_id&gt; [limit]")
                return
            target_id = message.from_user.id
            limit = 10
        else:
            target_id = int(args[0])
            limit = int(args[1]) if len(args) > 1 else 10

        limit = max(1, min(limit, 30))
    except ValueError:
        await message.answer("Формат: /adminEvents &lt;telegram_id&gt; [limit]")
        return

    try:
        events = await get_recent_user_events(target_id, limit)
        await message.answer(build_admin_events_text(target_id, events))
    except Exception as exc:
        await message.answer(f"Ошибка adminEvents: {type(exc).__name__}: {html.escape(str(exc))}")




def build_expiry_result_text(title: str, result: dict) -> str:
    lines = [
        f"⏳ <b>{h(title)}</b>",
        "",
        f"dry_run: <code>{result.get('dry_run')}</code>",
        f"found: <code>{result.get('found')}</code>",
        f"processed: <code>{result.get('processed')}</code>",
        f"checked_at: <code>{h(result.get('checked_at'))}</code>",
        "",
    ]

    results = result.get("results") or []
    if not results:
        lines.append("Expired paid users not found.")
        return "\n".join(lines)

    for item in results[:20]:
        lines.extend(
            [
                f"• telegram_id: <code>{h(item.get('telegram_id'))}</code>",
                f"  user_id: <code>{h(item.get('user_id'))}</code>",
                f"  status: <code>{h(item.get('status'))}</code>",
                f"  message: <code>{h(item.get('message'))}</code>",
                f"  old_expiry: <code>{h(item.get('old_subscription_expiry'))}</code>",
                f"  extra_active_count: <code>{h(item.get('extra_active_count'))}</code>",
                f"  deleted: <code>{len(item.get('deleted') or [])}</code>",
                f"  skipped: <code>{len(item.get('skipped') or [])}</code>",
                f"  errors: <code>{len(item.get('errors') or [])}</code>",
                "",
            ]
        )

    if len(results) > 20:
        lines.append(f"...and {len(results) - 20} more")

    text = "\n".join(lines).strip()
    if len(text) > 3900:
        text = text[:3800].rstrip() + "\n\n...truncated"

    return text


def parse_optional_limit(message: Message, default: int = 50) -> int:
    args = parse_admin_args(message)
    if not args:
        return default
    return max(1, min(int(args[0]), 200))







def build_legacy_list_text(items: list[dict]) -> str:
    lines = [
        "🧭 Legacy candidates",
        "",
        f"found: {len(items)}",
        "",
    ]

    if not items:
        lines.append("Кандидатов нет.")
        return "\n".join(lines)

    for item in items:
        block = [
            f"• telegram_id: {item.get('telegram_id')}",
            f"  user_id: {item.get('user_id')}",
            f"  access_type: {item.get('access_type')}",
            f"  category: {item.get('category')}",
            f"  should_notify: {item.get('should_notify')}",
            f"  already_notified: {item.get('already_notified')}",
            f"  legacy_clients: {item.get('legacy_panel_client_count')}",
            "",
        ]

        candidate_text = "\n".join(lines + block).strip()
        if len(candidate_text) > 3600:
            lines.append("...truncated")
            break

        lines.extend(block)

    return "\n".join(lines).strip()


def build_legacy_migration_text(snapshot: dict | None) -> str:
    if snapshot is None:
        return "Пользователь не найден"

    if not snapshot.get("user_found"):
        return f"🧭 <b>Legacy migration</b>\n\ntelegram_id: <code>{h(snapshot.get('telegram_id'))}</code>\nПользователь не найден."

    lines = [
        "🧭 <b>Legacy migration</b>",
        "",
        f"telegram_id: <code>{h(snapshot.get('telegram_id'))}</code>",
        f"user_id: <code>{h(snapshot.get('user_id'))}</code>",
        f"access_type: <code>{h(snapshot.get('access_type'))}</code>",
        f"is_active: <code>{h(snapshot.get('is_active'))}</code>",
        "",
        f"category: <code>{h(snapshot.get('category'))}</code>",
        f"should_notify: <code>{h(snapshot.get('should_notify'))}</code>",
        f"already_notified: <code>{h(snapshot.get('already_notified'))}</code>",
        f"grace_days: <code>{h(snapshot.get('legacy_grace_days'))}</code>",
        f"disable_after: <code>{h(snapshot.get('legacy_disable_after'))}</code>",
        "",
        f"active DB access: <code>{h(snapshot.get('active_db_access_count'))}</code>",
        f"panel clients by tgId: <code>{h(snapshot.get('panel_client_count'))}</code>",
        f"current panel clients: <code>{h(snapshot.get('current_panel_client_count'))}</code>",
        f"legacy panel clients: <code>{h(snapshot.get('legacy_panel_client_count'))}</code>",
        "",
    ]

    legacy_clients = snapshot.get("legacy_clients") or []
    if legacy_clients:
        lines.append("<b>Legacy clients:</b>")
        for item in legacy_clients[:10]:
            lines.extend(
                [
                    f"• email: <code>{h(item.get('email'))}</code>",
                    f"  uuid: <code>{h(item.get('uuid'))}</code>",
                    f"  enable: <code>{h(item.get('enable'))}</code>",
                    "",
                ]
            )

    current_clients = snapshot.get("current_clients") or []
    if current_clients:
        lines.append("<b>Current clients:</b>")
        for item in current_clients[:10]:
            lines.extend(
                [
                    f"• email: <code>{h(item.get('email'))}</code>",
                    f"  uuid: <code>{h(item.get('uuid'))}</code>",
                    f"  enable: <code>{h(item.get('enable'))}</code>",
                    "",
                ]
            )

    text = "\n".join(lines).strip()
    if len(text) > 3900:
        text = text[:3800].rstrip() + "\n\n...truncated"

    return text


def build_legacy_notify_result_text(result: dict | None) -> str:
    if result is None:
        return "Пользователь не найден"

    return (
        "🧭 <b>Legacy notify</b>\n\n"
        f"telegram_id: <code>{h(result.get('telegram_id'))}</code>\n"
        f"status: <code>{h(result.get('status'))}</code>\n"
        f"sent: <code>{h(result.get('sent'))}</code>\n"
        f"category: <code>{h(result.get('category'))}</code>\n"
        f"message: <code>{h(result.get('message'))}</code>"
    )


def build_legacy_notify_all_text(result: dict) -> str:
    lines = [
        "🧭 <b>Legacy notify all</b>",
        "",
        f"checked_at: <code>{h(result.get('checked_at'))}</code>",
        f"limit: <code>{h(result.get('limit'))}</code>",
        f"found: <code>{h(result.get('found'))}</code>",
        f"processed: <code>{h(result.get('processed'))}</code>",
        f"sent: <code>{h(result.get('sent'))}</code>",
        f"skipped: <code>{h(result.get('skipped'))}</code>",
        "",
    ]

    for item in (result.get("results") or [])[:20]:
        lines.extend(
            [
                f"• telegram_id: <code>{h(item.get('telegram_id'))}</code>",
                f"  status: <code>{h(item.get('status'))}</code>",
                f"  sent: <code>{h(item.get('sent'))}</code>",
                f"  category: <code>{h(item.get('category'))}</code>",
                f"  legacy_clients: <code>{h(item.get('legacy_panel_client_count'))}</code>",
                "",
            ]
        )

    text = "\n".join(lines).strip()
    if len(text) > 3900:
        text = text[:3800].rstrip() + "\n\n...truncated"

    return text


@router.message(F.text.regexp(r"^/adminLegacyCheck(?:@\w+)?(?:\s|$)"))
async def admin_legacy_check_command(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        target_id = parse_target(message)
    except ValueError:
        await message.answer("Формат: /adminLegacyCheck [telegram_id]")
        return

    try:
        snapshot = await get_legacy_migration_snapshot(target_id)
        await message.answer(build_legacy_migration_text(snapshot), parse_mode="HTML")
    except Exception as exc:
        await message.answer(f"Ошибка adminLegacyCheck: {type(exc).__name__}: {html.escape(str(exc))}")


@router.message(F.text.regexp(r"^/adminLegacyNotify(?:@\w+)?(?:\s|$)"))
async def admin_legacy_notify_command(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        target_id = parse_target(message)
    except ValueError:
        await message.answer("Формат: /adminLegacyNotify [telegram_id]")
        return

    try:
        result = await notify_legacy_migration_user(
            target_id,
            bot=message.bot,
            actor_telegram_id=message.from_user.id if message.from_user else None,
            source="admin_legacy_notify",
            force=True,
        )
        await message.answer(build_legacy_notify_result_text(result), parse_mode="HTML")
    except Exception as exc:
        await message.answer(f"Ошибка adminLegacyNotify: {type(exc).__name__}: {html.escape(str(exc))}")


@router.message(F.text.regexp(r"^/adminLegacyNotifyAll(?:@\w+)?(?:\s|$)"))
async def admin_legacy_notify_all_command(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        limit = parse_optional_limit(message, default=50)
    except ValueError:
        await message.answer("Формат: /adminLegacyNotifyAll [limit]")
        return

    try:
        result = await notify_legacy_migration_batch(
            bot=message.bot,
            limit=limit,
            actor_telegram_id=message.from_user.id if message.from_user else None,
            source="admin_legacy_notify_all",
        )
        await message.answer(build_legacy_notify_all_text(result), parse_mode="HTML")
    except Exception as exc:
        await message.answer(f"Ошибка adminLegacyNotifyAll: {type(exc).__name__}: {html.escape(str(exc))}")


def build_admin_traffic_text(snapshot: dict | None) -> str:
    if snapshot is None:
        return "Пользователь не найден"

    lines = [
        "📊 <b>Traffic</b>",
        "",
        f"telegram_id: <code>{h(snapshot.get('telegram_id'))}</code>",
        f"user_id: <code>{h(snapshot.get('user_id'))}</code>",
        f"access_type: <code>{h(snapshot.get('access_type'))}</code>",
        f"is_active: <code>{h(snapshot.get('is_active'))}</code>",
        "",
        f"used: <code>{h(snapshot.get('traffic_used_mb'))} MB</code> "
        f"(<code>{h(snapshot.get('traffic_used_gb'))} GB</code>)",
        "",
    ]

    if snapshot.get("access_type") == "free":
        lines.extend(
            [
                "<b>Free limit</b>",
                f"limit: <code>{h(snapshot.get('free_limit_mb'))} MB</code> "
                f"(<code>{h(snapshot.get('free_limit_gb'))} GB</code>)",
                f"left: <code>{h(snapshot.get('free_left_mb'))} MB</code> "
                f"(<code>{h(snapshot.get('free_left_gb'))} GB</code>)",
                f"used percent: <code>{h(snapshot.get('free_percent_used'))}%</code>",
                f"limit reached: <code>{h(snapshot.get('free_limit_reached'))}</code>",
            ]
        )
    elif snapshot.get("access_type") == "paid":
        lines.extend(
            [
                "<b>Paid overuse</b>",
                f"notify after: <code>{h(snapshot.get('paid_overuse_notify_mb'))} MB</code> "
                f"(<code>{h(snapshot.get('paid_overuse_notify_gb'))} GB</code>)",
                f"threshold percent: <code>{h(snapshot.get('paid_threshold_percent'))}%</code>",
                f"overuse reached: <code>{h(snapshot.get('paid_overuse_reached'))}</code>",
            ]
        )
    else:
        lines.extend(
            [
                "<b>Limits</b>",
                f"free limit: <code>{h(snapshot.get('free_limit_gb'))} GB</code>",
                f"paid notify after: <code>{h(snapshot.get('paid_overuse_notify_gb'))} GB</code>",
            ]
        )

    return "\n".join(lines)


@router.message(F.text.regexp(r"^/adminTraffic(?:@\w+)?(?:\s|$)"))
async def admin_traffic_command(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        target_id = parse_target(message)
    except ValueError:
        await message.answer("Формат: /adminTraffic [telegram_id]")
        return

    try:
        snapshot = await get_user_traffic_snapshot(target_id)
        await message.answer(build_admin_traffic_text(snapshot), parse_mode="HTML")
    except Exception as exc:
        await message.answer(f"Ошибка adminTraffic: {type(exc).__name__}: {html.escape(str(exc))}")


def build_admin_traffic_sync_text(result: dict | None) -> str:
    if result is None:
        return "Пользователь не найден"

    snapshot = result.get("snapshot")
    panel = result.get("panel") or {}

    lines = [
        build_admin_traffic_text(snapshot),
        "",
        "🔄 <b>Panel sync</b>",
        "",
        f"status: <code>{h(result.get('status'))}</code>",
        f"updated: <code>{h(result.get('updated'))}</code>",
        f"active access records: <code>{h(panel.get('active_access_count'))}</code>",
        f"synced records: <code>{h(panel.get('synced_access_count'))}</code>",
        f"panel total: <code>{h(panel.get('total_mb'))} MB</code> "
        f"(<code>{h(panel.get('total_gb'))} GB</code>)",
        "",
    ]

    records = panel.get("records") or []
    if records:
        lines.append("<b>Records:</b>")
        for item in records[:10]:
            lines.extend(
                [
                    f"• access_id: <code>{h(item.get('access_id'))}</code>",
                    f"  device: <code>{h(item.get('device_number'))}</code>",
                    f"  external_id: <code>{h(item.get('external_id'))}</code>",
                    f"  up: <code>{h(item.get('up_bytes'))}</code>",
                    f"  down: <code>{h(item.get('down_bytes'))}</code>",
                    f"  total_mb: <code>{h(item.get('total_mb'))}</code>",
                    "",
                ]
            )

    errors = panel.get("errors") or []
    if errors:
        lines.append("<b>Errors:</b>")
        for item in errors[:10]:
            lines.append(f"• <code>{h(item)}</code>")

    text = "\n".join(lines).strip()
    if len(text) > 3900:
        text = text[:3800].rstrip() + "\n\n...truncated"

    return text


@router.message(F.text.regexp(r"^/adminTrafficSync(?:@\w+)?(?:\s|$)"))
async def admin_traffic_sync_command(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        target_id = parse_target(message)
    except ValueError:
        await message.answer("Формат: /adminTrafficSync [telegram_id]")
        return

    try:
        result = await sync_user_traffic_from_panel(
            target_id,
            actor_telegram_id=message.from_user.id if message.from_user else None,
            source="admin_traffic_sync",
        )
        await message.answer(build_admin_traffic_sync_text(result), parse_mode="HTML")
    except Exception as exc:
        await message.answer(f"Ошибка adminTrafficSync: {type(exc).__name__}: {html.escape(str(exc))}")


@router.message(F.text.regexp(r"^/adminTrafficSet(?:@\w+)?(?:\s|$)"))
async def admin_traffic_set_command(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        args = parse_admin_args(message)
        if len(args) == 1:
            if not message.from_user:
                await message.answer("Формат: /adminTrafficSet [telegram_id] [used_mb]")
                return
            target_id = message.from_user.id
            used_mb = int(args[0])
        elif len(args) >= 2:
            target_id = int(args[0])
            used_mb = int(args[1])
        else:
            await message.answer("Формат: /adminTrafficSet [telegram_id] [used_mb]")
            return
    except ValueError:
        await message.answer("Формат: /adminTrafficSet [telegram_id] [used_mb]")
        return

    try:
        snapshot = await set_user_traffic_used(
            target_id,
            used_mb,
            actor_telegram_id=message.from_user.id if message.from_user else None,
        )
        await message.answer(build_admin_traffic_text(snapshot), parse_mode="HTML")
    except Exception as exc:
        await message.answer(f"Ошибка adminTrafficSet: {type(exc).__name__}: {html.escape(str(exc))}")


@router.message(F.text.regexp(r"^/adminTrafficReset(?:@\w+)?(?:\s|$)"))
async def admin_traffic_reset_command(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        target_id = parse_target(message)
    except ValueError:
        await message.answer("Формат: /adminTrafficReset [telegram_id]")
        return

    try:
        snapshot = await reset_user_traffic(
            target_id,
            actor_telegram_id=message.from_user.id if message.from_user else None,
        )
        await message.answer(build_admin_traffic_text(snapshot), parse_mode="HTML")
    except Exception as exc:
        await message.answer(f"Ошибка adminTrafficReset: {type(exc).__name__}: {html.escape(str(exc))}")


@router.message(F.text.regexp(r"^/adminExpireCheck(?:@\w+)?(?:\s|$)"))
async def admin_expire_check(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        limit = parse_optional_limit(message)
    except ValueError:
        await message.answer("Формат: /adminExpireCheck [limit]")
        return

    try:
        result = await expire_paid_users_once(limit=limit, dry_run=True)
        await message.answer(build_expiry_result_text("Paid expiry check", result))
    except Exception as exc:
        await message.answer(f"Ошибка adminExpireCheck: {type(exc).__name__}: {html.escape(str(exc))}")


@router.message(F.text.regexp(r"^/adminExpireRun(?:@\w+)?(?:\s|$)"))
async def admin_expire_run(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        limit = parse_optional_limit(message)
    except ValueError:
        await message.answer("Формат: /adminExpireRun [limit]")
        return

    try:
        result = await expire_paid_users_once(limit=limit, dry_run=False)
        await message.answer(build_expiry_result_text("Paid expiry run", result))
    except Exception as exc:
        await message.answer(f"Ошибка adminExpireRun: {type(exc).__name__}: {html.escape(str(exc))}")


@router.message(F.text.regexp(r"^/adminCleanCheck(?:@\w+)?(?:\s|$)"))
async def admin_clean_check(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        target_id = parse_target(message)
        user, accesses = await collect_cleanup_targets(target_id)
    except ValueError:
        await message.answer("Формат: /adminCleanCheck [telegram_id]")
        return
    except Exception as exc:
        await message.answer(f"Ошибка adminCleanCheck: {type(exc).__name__}: {exc}")
        return

    await log_user_event(
        event_type="admin_clean_check",
        target_telegram_id=target_id,
        actor_telegram_id=message.from_user.id if message.from_user else None,
        user_id=user.id if user else None,
        source="admin_tools",
        status="ok" if user else "not_found",
        message="Admin cleanup preview",
        details={
            "access_count": len(accesses),
        },
    )

    await message.answer(
        build_cleanup_preview_text(target_id, user, accesses),
        parse_mode="HTML",
    )


@router.message(F.text.regexp(r"^/adminClean(?:@\w+)?(?:\s|$)"))
async def admin_clean(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        target_id = parse_target(message)
        result = await cleanup_user_panel_and_db(target_id, actor_telegram_id=message.from_user.id if message.from_user else None)
    except ValueError:
        await message.answer("Формат: /adminClean [telegram_id]")
        return
    except Exception as exc:
        await message.answer(f"Ошибка adminClean: {type(exc).__name__}: {exc}")
        return

    if not result["user_found"]:
        await message.answer(f"Пользователь не найден\ntelegram_id: {target_id}")
        return

    lines = [
        "🧹 <b>Panel cleanup выполнен</b>",
        "",
        f"telegram_id: <code>{target_id}</code>",
        f"deleted: <code>{len(result['deleted'])}</code>",
        f"skipped: <code>{len(result['skipped'])}</code>",
        f"errors: <code>{len(result['errors'])}</code>",
        "",
    ]

    if result["deleted"]:
        lines.append("<b>Deleted:</b>")
        lines.extend(f"• <code>{item}</code>" for item in result["deleted"][:10])
        lines.append("")

    if result["skipped"]:
        lines.append("<b>Skipped:</b>")
        lines.extend(f"• <code>{item}</code>" for item in result["skipped"][:10])
        lines.append("")

    if result["errors"]:
        lines.append("<b>Errors:</b>")
        lines.extend(f"• <code>{item}</code>" for item in result["errors"][:10])
        lines.append("")
        lines.append("DB-записи не отключены, потому что были ошибки удаления в panel.")
    else:
        lines.append("DB-доступы и подписочные ссылки отключены.")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(F.text.regexp(r"^/adminPaid(?:@\w+)?(?:\s|$)"))
async def admin_paid(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        target_id, days = parse_target_and_days(message)
        await set_user_paid(target_id, days, message)
    except ValueError:
        await message.answer("Формат: /adminPaid [telegram_id] [days]")
        return
    except VPNServiceError as exc:
        await message.answer(f"Paid записан, но ключи не подготовлены: {exc}")
        return
    except Exception as exc:
        await message.answer(f"Ошибка adminPaid: {type(exc).__name__}: {exc}")
        return

    await message.answer(f"✅ paid активирован\ntelegram_id: {target_id}\nдней: {days}")


@router.message(F.text.regexp(r"^/adminFree(?:@\w+)?(?:\s|$)"))
async def admin_free(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        target_id = parse_target(message)
        await set_user_free(target_id, message)
    except ValueError:
        await message.answer("Формат: /adminFree [telegram_id]")
        return
    except VPNServiceError as exc:
        await message.answer(f"Free записан, но ключ не подготовлен: {exc}")
        return
    except Exception as exc:
        await message.answer(f"Ошибка adminFree: {type(exc).__name__}: {exc}")
        return

    await message.answer(f"✅ free активирован\ntelegram_id: {target_id}")


@router.message(F.text.regexp(r"^/adminRes(?:@\w+)?(?:\s|$)"))
async def admin_reset(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        target_id = parse_target(message)
        await reset_user_profile(target_id, message)
    except ValueError:
        await message.answer("Формат: /adminRes [telegram_id]")
        return
    except Exception as exc:
        await message.answer(f"Ошибка adminRes: {type(exc).__name__}: {exc}")
        return

    await message.answer(
        "✅ profile reset выполнен\n"
        f"telegram_id: {target_id}\n\n"
        "DB-доступы и подписочные ссылки отключены. "
        "Panel cleanup сделаем отдельной безопасной командой позже."
    )


@router.message(F.text.regexp(r"^/adminLegacyList(?:@\w+)?(?:\s|$)"))
async def admin_legacy_list_command(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        limit = parse_optional_limit(message, default=50)
    except ValueError:
        await message.answer("Формат: /adminLegacyList [limit]")
        return

    try:
        telegram_ids = await collect_legacy_migration_candidates(limit=limit)
        snapshots = []

        for telegram_id in telegram_ids:
            snapshots.append(await get_legacy_migration_snapshot(telegram_id))

        lines = [
            "🧭 Legacy candidates",
            "",
            f"found: {len(snapshots)}",
            "",
        ]

        if not snapshots:
            lines.append("Кандидатов нет.")

        for item in snapshots:
            block = [
                f"• telegram_id: {item.get('telegram_id')}",
                f"  user_id: {item.get('user_id')}",
                f"  access_type: {item.get('access_type')}",
                f"  category: {item.get('category')}",
                f"  should_notify: {item.get('should_notify')}",
                f"  already_notified: {item.get('already_notified')}",
                f"  legacy_clients: {item.get('legacy_panel_client_count')}",
                "",
            ]

            candidate_text = "\n".join(lines + block).strip()
            if len(candidate_text) > 3600:
                lines.append("...truncated")
                break

            lines.extend(block)

        await message.answer("\n".join(lines).strip())
    except Exception as exc:
        await message.answer(f"Ошибка adminLegacyList: {type(exc).__name__}: {html.escape(str(exc))}")


@router.message(F.text.regexp(r"^/adminRefs(?:@\w+)?(?:\s|$)"))
async def admin_refs_command(message: Message) -> None:
    if not is_admin(message):
        return

    try:
        target_id = parse_target(message)
    except ValueError:
        await message.answer("Формат: /adminRefs [telegram_id]")
        return

    try:
        summary = await get_referral_summary(target_id)

        if not summary.get("user_found"):
            await message.answer(f"Пользователь не найден: {target_id}")
            return

        lines = [
            "🎁 Referrals",
            "",
            f"telegram_id: {summary.get('telegram_id')}",
            f"ref_code: {summary.get('ref_code')}",
            f"total_referrals: {summary.get('total_referrals')}",
            f"paid_referrals: {summary.get('paid_referrals')}",
            f"total_bonus_days: {summary.get('total_bonus_days')}",
            "",
        ]

        referrals = summary.get("referrals") or []
        if not referrals:
            lines.append("Рефералов пока нет.")

        for item in referrals[:30]:
            lines.extend(
                [
                    f"• {item.get('referred_telegram_id')} @{item.get('username') or '-'}",
                    f"  paid: {item.get('is_paid')}",
                    f"  bonus_days: {item.get('bonus_days')}",
                    "",
                ]
            )

        await message.answer("\n".join(lines).strip())
    except Exception as exc:
        await message.answer(f"Ошибка adminRefs: {type(exc).__name__}: {html.escape(str(exc))}")
