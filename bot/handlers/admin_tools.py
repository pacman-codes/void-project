from __future__ import annotations

import os
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
