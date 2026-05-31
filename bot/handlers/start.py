from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
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
from services.referral_service import assign_referral_from_start_code, build_ref_code

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
    first_name: str | None = None,
) -> str:
    display_name = first_name or ("friend" if lang == "en" else "друг")

    if lang == "en":
        return (
            f"{display_name}, thank you for being with us 😏\n\n"
            f"PRO subscription 🤌 is active until <b>{format_expiry(expiry, lang)}</b>\n\n"
            "We appreciate you and keep improving the service 🍔\n"
            'Feedback and suggestions go <a href="https://t.me/voidModeBot">here</a>.\n\n'
            "Do not forget to renew in time 👇"
        )

    return (
        f"{display_name}, спасибо, что с нами! 😏\n\n"
        f"Подписка PRO 🤌 действует до <b>{format_expiry(expiry, lang)}</b>\n\n"
        "Мы ценим вас и стараемся сделать сервис лучше 🍔\n"
        'Поддержка и предложения: @voidModeSupport.\n\n'
        "Не забудьте вовремя продлить доступ 👇"
    )


def build_free_start_text(
    lang: str,
    traffic_used: int | None,
    traffic_limit: int | None,
    config_url: str | None,
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
            "Your try-it plan 🤏 includes:\n\n"
            f"Traffic: <b>{left_gb:.1f} of {limit_gb:.0f} GB</b> / month\n"
            "1 device\n\n"
            "For comfort, we recommend PRO 🤌:\n"
            "• high speed\n"
            "• up to 7 devices available\n"
            "• unlimited traffic\n\n"
            "Thank you for being with us 🫶"
        )

    return (
        "Ваш тариф пощупать 🤏 включает:\n\n"
        f"Трафик: <b>{left_gb:.1f} из {limit_gb:.0f} ГБ</b> / месяц\n"
        "1 устройство\n\n"
        "Для удобства рекомендуем тариф PRO 🤌:\n"
        "• высокая скорость\n"
        "• до 7 устройств доступно\n"
        "• безлимитный трафик\n\n"
        "Спасибо, что вы с нами 🫶"
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
    # Legacy raw-key provisioning is disabled.
    # Users should receive a subscription link via subscription_parts/menu.py.
    return None


def build_free_limit_reached_text(lang: str = "ru") -> str:
    if lang == "en":
        return (
            "⛔️ <b>Free traffic limit is over</b>\n\n"
            "The free 3 GB limit has already been used.\n\n"
            "Full access removes the traffic limit and gives you more devices."
        )

    return (
        "⛔️ <b>Бесплатный лимит трафика закончился</b>\n\n"
        "Бесплатный доступ уже использован: <b>3 ГБ</b>.\n\n"
        "Полный доступ — без лимита по трафику, с максимальной скоростью и большим количеством устройств."
    )


def get_free_limit_reached_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="PRO plan 🤌" if lang == "en" else "Тариф PRO 🤌",
                    callback_data="subscription_paid",
                )
            ]
        ]
    )


async def build_home_text_and_keyboard(telegram_id: int) -> tuple[str, object, str]:
    user = await get_user_by_telegram_id(telegram_id)
    lang = user.language if user and user.language else "ru"
    access = await get_access_status(telegram_id)

    traffic_used = int(user.traffic_used or 0) if user else 0
    traffic_limit = int(user.traffic_limit or DEFAULT_TRAFFIC_LIMIT_MB) if user else DEFAULT_TRAFFIC_LIMIT_MB

    if traffic_limit <= 0:
        traffic_limit = DEFAULT_TRAFFIC_LIMIT_MB

    if (
        user
        and user.terms_accepted
        and user.access_type == "free"
        and traffic_used >= traffic_limit
    ):
        return build_free_limit_reached_text(lang), get_free_limit_reached_keyboard(lang), lang

    if not access["has_access"]:
        return get_welcome_text(lang), get_start_inline_keyboard(lang), lang

    access_type = access["access_type"]
    if access_type == "paid":
        return (
            build_paid_start_text(
                lang=lang,
                expiry=access["expiry"],
                first_name=user.first_name if user else None,
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
        partner_assigned = await try_assign_partner_offer(message.from_user.id, start_code)
        if not partner_assigned:
            await assign_referral_from_start_code(message.from_user.id, start_code)

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
