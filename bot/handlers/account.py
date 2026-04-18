from aiogram import Router, F
from aiogram.types import CallbackQuery
from datetime import datetime

from db.models import User
from db.database import async_session_maker
from sqlalchemy import select

from bot.keyboards.user import get_account_inline_keyboard

router = Router()


def format_expiry(dt: datetime | None, lang: str) -> str:
    if not dt:
        return "—"

    if lang == "en":
        return dt.strftime("%Y-%m-%d %H:%M")
    return dt.strftime("%d.%m.%Y %H:%M")


def build_free_account_text(user: User, lang: str) -> str:
    remaining = max(0, (user.traffic_limit or 0) - (user.traffic_used or 0))

    if lang == "en":
        return (
            "🎁 <b>Free access</b>\n\n"
            f"📊 Traffic left: <b>{remaining} MB</b>\n"
            "📱 Devices: <b>1</b>\n\n"
            "⚠️ Limited speed and traffic\n\n"
            "🚀 Upgrade to get:\n"
            "• Unlimited traffic\n"
            "• Higher speed\n"
            "• More devices"
        )

    return (
        "🎁 <b>Бесплатный доступ</b>\n\n"
        f"📊 Осталось трафика: <b>{remaining} МБ</b>\n"
        "📱 Устройства: <b>1</b>\n\n"
        "⚠️ Ограниченная скорость и трафик\n\n"
        "🚀 Полный доступ даёт:\n"
        "• Безлимитный трафик\n"
        "• Максимальную скорость\n"
        "• Больше устройств"
    )


def build_paid_account_text(user: User, lang: str) -> str:
    expiry = format_expiry(user.subscription_expiry, lang)
    used = user.used_devices or 0
    limit = user.device_limit or 0

    if lang == "en":
        return (
            "👑 <b>Full access active</b>\n\n"
            "🚀 Everything works without limits\n\n"
            f"📅 Valid until: <b>{expiry}</b>\n"
            f"📱 Devices: <b>{used} / {limit}</b>\n\n"
            "➕ Need more devices?\n"
            "Tap <b>Add device</b>"
        )

    return (
        "👑 <b>Полный доступ активен</b>\n\n"
        "🚀 Всё работает без ограничений\n\n"
        f"📅 Доступ до: <b>{expiry}</b>\n"
        f"📱 Устройства: <b>{used} / {limit}</b>\n\n"
        "➕ Нужно ещё устройство?\n"
        "Нажмите <b>Добавить устройство</b>"
    )


@router.callback_query(F.data == "open_account")
async def open_account(callback: CallbackQuery) -> None:
    telegram_id = callback.from_user.id

    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

    if not user:
        await callback.answer("User not found", show_alert=True)
        return

    lang = user.language or "ru"

    if user.access_type == "paid":
        text = build_paid_account_text(user, lang)
    else:
        text = build_free_account_text(user, lang)

    await callback.message.edit_text(
        text,
        reply_markup=get_account_inline_keyboard(lang, user.access_type),
        parse_mode="HTML",
    )

    await callback.answer()
