from datetime import datetime

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select, text

from bot.keyboards.user import (
    CHANNEL_URL,
    get_active_home_inline_keyboard,
    get_remove_keyboard,
    get_start_inline_keyboard,
    get_welcome_text,
)
from config.pricing import PARTNER_OFFER_CODE, PARTNER_OFFER_MAX_ASSIGNMENTS
from db.database import async_session_maker
from db.models import User, VPNAccess
from services.access_service import get_access_status
from services.vpn_service import VPNService, VPNServiceError

router = Router()

DEFAULT_TRAFFIC_LIMIT_MB = 3072


def format_expiry(value, lang: str) -> str:
    if value is None:
        return "Not set" if lang == "en" else "Не указано"

    if isinstance(value, datetime):
        if lang == "en":
            return value.strftime("%Y-%m-%d %H:%M")
        return value.strftime("%d.%m.%Y %H:%M")

    text_value = str(value)

    try:
        parsed = datetime.fromisoformat(text_value)
        if lang == "en":
            return parsed.strftime("%Y-%m-%d %H:%M")
        return parsed.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return text_value


def build_paid_start_text(
    lang: str,
    expiry,
    used_devices: int,
    device_limit: int,
) -> str:
    if lang == "en":
        return (
            "💎 <b>Full access active</b>\n\n"
            f"📅 Valid until: <b>{format_expiry(expiry, lang)}</b>\n"
            f"📱 Devices: <b>{used_devices} of {device_limit}</b>\n\n"
            "—\n\n"
            "⚡ High speed without limits\n"
            "🔒 Protected connection\n"
            "🌍 Stable operation\n\n"
            "💡 You can connect additional devices\n\n"
            f"📢 News and updates:\n{CHANNEL_URL}"
        )

    return (
        "💎 <b>Полный доступ активен</b>\n\n"
        f"📅 Действует до: <b>{format_expiry(expiry, lang)}</b>\n"
        f"📱 Устройства: <b>{used_devices} из {device_limit}</b>\n\n"
        "—\n\n"
        "⚡ Высокая скорость без ограничений\n"
        "🔒 Защищённое соединение\n"
        "🌍 Стабильная работа\n\n"
        "💡 Можно подключить дополнительные устройства\n\n"
        f"📢 Новости и обновления:\n{CHANNEL_URL}"
    )


def build_free_start_text(
    lang: str,
    traffic_used: int | None,
    traffic_limit: int | None,
    config_url: str | None,
    used_devices: int,
    device_limit: int,
) -> str:
    used_mb = traffic_used or 0
    limit_mb = traffic_limit or DEFAULT_TRAFFIC_LIMIT_MB
    left_mb = max(limit_mb - used_mb, 0)
    left_gb = left_mb / 1024
    limit_gb = limit_mb / 1024
    # Raw config is intentionally not shown on the home screen.
    # Users should use the subscription link button instead.

    if lang == "en":
        return (
            "🆓 <b>Free access</b>\n\n"
            f"📱 Devices: <b>{used_devices} of {device_limit}</b>\n"
            f"📊 Remaining traffic: <b>{left_gb:.1f} of {limit_gb:.0f} GB</b>\n\n"
            "Suitable for basic use\n\n"
            "—\n\n"
            "💎 <b>Full access unlocks:</b>\n\n"
            "⚡ Maximum speed\n"
            "📱 Multiple devices\n"
            "🌍 Stable operation without limits\n\n"
            f"📢 News and updates:\n{CHANNEL_URL}"
        )

    return (
        "🆓 <b>Бесплатный доступ</b>\n\n"
        f"📱 Устройства: <b>{used_devices} из {device_limit}</b>\n"
        f"📊 Осталось трафика: <b>{left_gb:.1f} из {limit_gb:.0f} ГБ</b>\n\n"
        "Подходит для базового использования\n\n"
        "—\n\n"
        "💎 <b>Полный доступ открывает:</b>\n\n"
        "⚡ Максимальную скорость\n"
        "📱 Несколько устройств\n"
        "🌍 Стабильную работу без ограничений\n\n"
        f"📢 Новости и обновления:\n{CHANNEL_URL}"
    )


async def ensure_user(message: Message) -> User:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                language="ru",
                traffic_limit=DEFAULT_TRAFFIC_LIMIT_MB,
                traffic_used=0,
                is_active=False,
                access_type=None,
                terms_accepted=False,
                payment_status=None,
                payment_id=None,
                device_limit=1,
                used_devices=0,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

        changed = False

        if user.username != message.from_user.username:
            user.username = message.from_user.username
            changed = True

        if user.first_name != message.from_user.first_name:
            user.first_name = message.from_user.first_name
            changed = True

        if user.last_name != message.from_user.last_name:
            user.last_name = message.from_user.last_name
            changed = True

        if user.traffic_limit is None:
            user.traffic_limit = DEFAULT_TRAFFIC_LIMIT_MB
            changed = True

        if user.traffic_used is None:
            user.traffic_used = 0
            changed = True

        if not user.language:
            user.language = "ru"
            changed = True

        if user.access_type not in {"free", "paid", None}:
            user.access_type = None
            changed = True

        if user.device_limit is None or user.device_limit <= 0:
            user.device_limit = 1
            changed = True

        if user.used_devices is None or user.used_devices < 0:
            user.used_devices = 0
            changed = True

        if changed:
            await session.commit()
            await session.refresh(user)

        return user


async def sync_is_active(telegram_id: int, has_access: bool) -> None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user is not None and user.is_active != has_access:
            user.is_active = has_access
            await session.commit()


async def remove_reply_keyboard(message: Message) -> None:
    service_message = await message.answer(".", reply_markup=get_remove_keyboard())
    try:
        await message.bot.delete_message(
            chat_id=service_message.chat.id,
            message_id=service_message.message_id,
        )
    except Exception:
        pass


async def get_user_by_telegram_id(telegram_id: int) -> User | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


async def get_primary_config_url(telegram_id: int) -> str | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(VPNAccess.config_url)
            .join(User, User.id == VPNAccess.user_id)
            .where(
                User.telegram_id == telegram_id,
                VPNAccess.device_number == 1,
            )
        )
        return result.scalar_one_or_none()


async def ensure_primary_config_url(telegram_id: int, access_type: str | None) -> str | None:
    if access_type not in {"free", "paid"}:
        return None

    existing = await get_primary_config_url(telegram_id)
    if existing:
        return existing

    try:
        service = VPNService()
        result = await service.ensure_vpn_access_record(
            telegram_id=telegram_id,
            device_number=1,
            device_name="Устройство 1",
        )
        return result.get("config_url")
    except VPNServiceError:
        return None
    except Exception:
        return None


async def build_home_text_and_keyboard(telegram_id: int) -> tuple[str, object, str]:
    user = await get_user_by_telegram_id(telegram_id)
    lang = user.language if user and user.language else "ru"
    access = await get_access_status(telegram_id)

    if not access["has_access"]:
        return get_welcome_text(lang), get_start_inline_keyboard(lang), lang

    access_type = access["access_type"]
    used_devices = user.used_devices if user else 0
    device_limit = user.device_limit if user else 1

    if device_limit is None or device_limit <= 0:
        device_limit = 1

    used_devices = max(0, used_devices or 0)
    used_devices = min(used_devices, device_limit)

    if access_type == "paid":
        return (
            build_paid_start_text(
                lang=lang,
                expiry=access["expiry"],
                used_devices=used_devices,
                device_limit=device_limit,
            ),
            get_active_home_inline_keyboard(lang, access_type),
            lang,
        )

    config_url = await ensure_primary_config_url(telegram_id, access_type)

    return (
        build_free_start_text(
            lang=lang,
            traffic_used=user.traffic_used if user else 0,
            traffic_limit=user.traffic_limit if user else DEFAULT_TRAFFIC_LIMIT_MB,
            config_url=config_url,
            used_devices=used_devices,
            device_limit=device_limit,
        ),
        get_active_home_inline_keyboard(lang, access_type),
        lang,
    )


async def render_home_screen(target: Message | CallbackQuery) -> None:
    telegram_id = target.from_user.id
    text, keyboard, _lang = await build_home_text_and_keyboard(telegram_id)

    if isinstance(target, Message):
        await target.answer(
            text,
            reply_markup=keyboard,
            disable_web_page_preview=True,
            parse_mode="HTML",
        )
        return

    await target.message.edit_text(
        text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
        parse_mode="HTML",
    )


PARTNER_OFFER_LOCK_KEY = 982451653


async def try_assign_partner_offer(telegram_id: int, start_code: str | None) -> bool:
    if not start_code:
        return False

    start_code = start_code.strip()
    if start_code != PARTNER_OFFER_CODE:
        return False

    async with async_session_maker() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": PARTNER_OFFER_LOCK_KEY},
        )

        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return False

        if user.first_paid_at is not None:
            return False

        if user.partner_offer_code == PARTNER_OFFER_CODE:
            return True

        if user.partner_offer_code:
            return False

        count_result = await session.execute(
            select(func.count(User.id)).where(
                User.partner_offer_code == PARTNER_OFFER_CODE
            )
        )
        assigned_count = int(count_result.scalar() or 0)

        if assigned_count >= PARTNER_OFFER_MAX_ASSIGNMENTS:
            return False

        user.partner_offer_code = PARTNER_OFFER_CODE
        user.partner_offer_used = False
        await session.commit()
        return True

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if message.from_user is None:
        return

    user = await ensure_user(message)

    start_code = ""
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            start_code = parts[1].strip()

    if start_code:
        await try_assign_partner_offer(message.from_user.id, start_code)

    access = await get_access_status(message.from_user.id)

    await remove_reply_keyboard(message)
    await sync_is_active(message.from_user.id, access["has_access"])

    if not access["has_access"] and user.access_type is None:
        await message.answer(
            get_welcome_text(user.language or "ru"),
            reply_markup=get_start_inline_keyboard(user.language or "ru"),
            disable_web_page_preview=True,
            parse_mode="HTML",
        )
        return

    await render_home_screen(message)


@router.callback_query(F.data == "back_home")
async def back_home(callback: CallbackQuery) -> None:
    access = await get_access_status(callback.from_user.id)
    await sync_is_active(callback.from_user.id, access["has_access"])
    await render_home_screen(callback)
    await callback.answer()
