from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.start import ensure_user, render_home_screen
from bot.keyboards.home import SUPPORT_URL
from services.referral_service import build_ref_code, get_referral_summary

router = Router()


def build_referral_text(
    *,
    bot_username: str,
    telegram_id: int,
    total_referrals: int,
    paid_referrals: int,
    total_bonus_days: int,
) -> str:
    ref_code = build_ref_code(telegram_id)
    ref_link = f"https://t.me/{bot_username}?start={ref_code}"

    return (
        "🎁 <b>Реферальная программа</b>\n\n"
        f"👥 Приглашено друзей: <b>{total_referrals}</b>\n"
        f"💳 Оплатили доступ: <b>{paid_referrals}</b>\n"
        f"🎉 Бонус получен: <b>+{total_bonus_days} дн.</b>\n\n"
        "Приглашайте друзей и получайте бонусы\n"
        "за их первую оплату:\n\n"
        "• 1 друг — +7 дней\n"
        "• 2 друга — +14 дней\n"
        "• 3 друга — +30 дней\n"
        "• 4 и дальше — +30 дней за каждого\n\n"
        "✨ Работает даже на бесплатном доступе\n\n"
        "🔗 <b>Ваша ссылка:</b>\n\n"
        f"<code>{ref_link}</code>\n\n"
        "Отправьте её другу"    )


def build_referral_keyboard(ref_link: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📨 Поделиться ссылкой",
            url=f"https://t.me/share/url?url={ref_link}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="💬 Поддержка",
            url=SUPPORT_URL,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="back_to_home",
        )
    )
    return builder.as_markup()


async def send_referral_screen(target: Message | CallbackQuery) -> None:
    telegram_id = target.from_user.id

    if isinstance(target, Message):
        await ensure_user(target)

    bot_info = await target.bot.get_me()
    summary = await get_referral_summary(telegram_id)

    ref_code = build_ref_code(telegram_id)
    ref_link = f"https://t.me/{bot_info.username}?start={ref_code}"

    text = build_referral_text(
        bot_username=bot_info.username,
        telegram_id=telegram_id,
        total_referrals=int(summary.get("total_referrals") or 0),
        paid_referrals=int(summary.get("paid_referrals") or 0),
        total_bonus_days=int(summary.get("total_bonus_days") or 0),
    )

    if isinstance(target, Message):
        await target.answer(
            text,
            reply_markup=build_referral_keyboard(ref_link),
            disable_web_page_preview=True,
            parse_mode="HTML",
        )
        return

    await target.message.edit_text(
        text,
        reply_markup=build_referral_keyboard(ref_link),
        disable_web_page_preview=True,
        parse_mode="HTML",
    )
    await target.answer()


@router.message(Command("ref"))
async def ref_command(message: Message) -> None:
    if message.from_user is None:
        return

    await send_referral_screen(message)


@router.callback_query(F.data == "open_referral")
async def open_referral(callback: CallbackQuery) -> None:
    await send_referral_screen(callback)


@router.callback_query(F.data == "back_to_home")
async def back_to_home(callback: CallbackQuery) -> None:
    await render_home_screen(callback)
    await callback.answer()
