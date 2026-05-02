from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from services.user_service import get_user


async def safe_edit_text(
    message: Any,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = "HTML",
    disable_web_page_preview: bool | None = None,
) -> bool:
    if not isinstance(message, Message):
        return False

    try:
        await message.edit_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
        return True
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return False
        raise


async def safe_callback_answer(
    callback: CallbackQuery,
    text: str | None = None,
    show_alert: bool = False,
) -> None:
    if text:
        text = str(text).strip()
        if len(text) > 180:
            text = text[:180].rstrip() + "..."

    try:
        await callback.answer(text=text, show_alert=show_alert)
    except TelegramBadRequest as e:
        if "query is too old" in str(e) or "query ID is invalid" in str(e):
            return
        if "MESSAGE_TOO_LONG" in str(e):
            try:
                await callback.answer(
                    text="Ошибка. Откройте «Не работает»." if show_alert else None,
                    show_alert=show_alert,
                )
                return
            except TelegramBadRequest:
                return
        raise


async def get_lang(user_id: int) -> str:
    user = await get_user(user_id)
    if user and user.language:
        return user.language
    return "ru"
