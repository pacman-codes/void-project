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
    await service.ensure_vpn_access_record(
        telegram_id=telegram_id,
        device_number=2,
        device_name="Устройство 2",
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
                f"  external_id: <code>{access.external_id or '-'}</code>",
                f"  client_uuid: <code>{access.client_uuid or '-'}</code>",
                "",
            ]
        )

    lines.append("Для реального удаления: /adminClean " + str(telegram_id))
    return "\n".join(lines)


async def cleanup_user_panel_and_db(telegram_id: int) -> dict:
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
        await message.answer(build_admin_user_text(telegram_id, user, accesses, links))
    except Exception as exc:
        await message.answer(f"Ошибка adminUser: {type(exc).__name__}: {html.escape(str(exc))}")


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
        result = await cleanup_user_panel_and_db(target_id)
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
