from typing import Union

from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from db.database import async_session_maker
from db.models import User
from services.access_service import get_access_status
from utils.texts import get_access_denied_text


TelegramEvent = Union[Message, CallbackQuery]


async def _get_user_language(telegram_id: int) -> str:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user and user.language:
            return user.language

    return "ru"


async def _send_reply(event: TelegramEvent, text: str) -> None:
    if isinstance(event, Message):
        await event.answer(text)
        return

    if isinstance(event, CallbackQuery):
        if event.message:
            await event.message.answer(text)
        await event.answer()


async def ensure_active_access(
    event: TelegramEvent,
    telegram_id: int,
) -> dict | None:
    """
    Универсальная проверка доступа.

    Если доступ есть:
        возвращает словарь access_status
    Если доступа нет:
        отправляет пользователю понятное сообщение
        и возвращает None
    """

    access_status = await get_access_status(telegram_id)

    if access_status["has_access"]:
        return access_status

    language = await _get_user_language(telegram_id)
    text = get_access_denied_text(language, access_status["reason"])
    await _send_reply(event, text)

    return None
