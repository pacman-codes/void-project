from datetime import datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from bot.keyboards.user import get_account_inline_keyboard
from db.database import async_session_maker
from db.models import User

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
            f"📊 Traffic left: <b>{remaining} MB</b>\n\n"
            "Good for basic use\n\n"
            "🔗 Access is available through the <b>Connection</b> on the main screen.\n\n"
            "💎 Full access gives:\n"
            "• Maximum speed\n"
            "• Stable unlimited usage"
        )

    return (
        "🆓 <b>Бесплатный доступ</b>\n\n"
        f"📊 Осталось трафика: <b>{remaining} МБ</b>\n\n"
        "Подходит для базового использования\n\n"
        "🔗 Доступ доступен через <b>подписочную ссылку</b> на главном экране.\n\n"
        "💎 Полный доступ открывает:\n"
        "• Максимальную скорость\n"
        "• Стабильную работу без ограничений"
    )


def build_paid_account_text(user: User, lang: str) -> str:
    expiry = format_expiry(user.subscription_expiry, lang)

    if lang == "en":
        return (
            "👑 <b>Full access active</b>\n\n"
            "🚀 Everything works without limits\n\n"
            f"📅 Valid until: <b>{expiry}</b>\n\n"
            "🔗 Connection is available on the main screen."
        )

    return (
        "👑 <b>Полный доступ активен</b>\n\n"
        "🚀 Всё работает без ограничений\n\n"
        f"📅 Доступ до: <b>{expiry}</b>\n\n"
        "🔗 Подключение доступна на главном экране."
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
