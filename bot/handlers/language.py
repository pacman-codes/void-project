from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from bot.keyboards.user import (
    get_active_home_inline_keyboard,
    get_language_inline_keyboard,
    get_start_inline_keyboard,
    get_welcome_text,
)
from db.database import async_session_maker
from db.models import User
from services.access_service import get_access_status
from utils.buttons import LANGUAGE_EN, LANGUAGE_RU

router = Router()

DEFAULT_TRAFFIC_LIMIT = 1000


def build_active_home_text(
    lang: str,
    expiry,
    access_type: str | None,
    traffic_used: int | None,
    traffic_limit: int | None,
) -> str:
    if access_type == "paid":
        if lang == "en":
            return (
                "👑 <b>Full access is active</b>\n\n"
                "🚀 Everything works without limits\n\n"
                f"📅 Valid until: <b>{expiry.strftime('%Y-%m-%d %H:%M') if expiry else 'Not set'}</b>\n\n"
                "👇 Management:"
            )

        return (
            "👑 <b>Полный доступ активен</b>\n\n"
            "🚀 Всё работает без ограничений\n\n"
            f"📅 До: <b>{expiry.strftime('%d.%m.%Y %H:%M') if expiry else 'Не указано'}</b>\n\n"
            "👇 Управление:"
        )

    used_mb = traffic_used or 0
    limit_mb = traffic_limit or 3072
    left_mb = max(limit_mb - used_mb, 0)
    left_gb = left_mb / 1024
    limit_gb = limit_mb / 1024

    if lang == "en":
        return (
            "🚀 <b>Internet accelerator</b>\n\n"
            "📊 <b>Free access is active</b>\n\n"
            f"Remaining:\n{left_gb:.1f} GB of {limit_gb:.0f} GB\n\n"
            "⚠️ Access is limited by traffic and devices\n\n"
            "👇 Actions:"
        )

    return (
        "🚀 <b>Ускоритель интернета</b>\n\n"
        "📊 <b>Бесплатный доступ активен</b>\n\n"
        f"Осталось:\n{left_gb:.1f} ГБ из {limit_gb:.0f} ГБ\n\n"
        "⚠️ Доступ ограничен трафиком и количеством устройств\n\n"
        "👇 Действия:"
    )


async def save_user_language(
    telegram_id: int,
    username: str | None,
    language: str,
) -> tuple[str, dict, User | None]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                language=language,
                traffic_limit=3072,
                traffic_used=0,
                is_active=True,
                access_type="free",
            )
            session.add(user)
        else:
            user.language = language

            if user.username != username:
                user.username = username

            if user.traffic_limit is None:
                user.traffic_limit = 3072

            if user.traffic_used is None:
                user.traffic_used = 0

            if not user.access_type:
                user.access_type = "free"

        await session.commit()
        await session.refresh(user)

    access = await get_access_status(telegram_id)
    return language, access, user


@router.message(Command("language"))
async def open_language_command(message: Message) -> None:
    await message.answer(
        "Выберите язык / Choose language",
        reply_markup=get_language_inline_keyboard(),
    )


@router.message(F.text.in_({LANGUAGE_RU, LANGUAGE_EN}))
async def open_language_from_menu(message: Message) -> None:
    await message.answer(
        "Выберите язык / Choose language",
        reply_markup=get_language_inline_keyboard(),
    )


@router.callback_query(F.data == "open_language")
async def open_language(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Выберите язык / Choose language",
        reply_markup=get_language_inline_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.in_({"set_lang_ru", "set_lang_en"}))
async def set_language_callback(callback: CallbackQuery) -> None:
    language = "en" if callback.data == "set_lang_en" else "ru"
    lang, access, user = await save_user_language(
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        language=language,
    )

    if access["has_access"]:
        await callback.message.edit_text(
            build_active_home_text(
                lang=lang,
                expiry=access["expiry"],
                access_type=access["access_type"],
                traffic_used=user.traffic_used if user else 0,
                traffic_limit=user.traffic_limit if user else 3072,
            ),
            reply_markup=get_active_home_inline_keyboard(lang, access["access_type"]),
            parse_mode="HTML",
        )
        await callback.answer("Done" if lang == "en" else "Готово")
        return

    await callback.message.edit_text(
        get_welcome_text(lang),
        reply_markup=get_start_inline_keyboard(lang),
        disable_web_page_preview=True,
        parse_mode="HTML",
    )
    await callback.answer("Done" if lang == "en" else "Готово")


@router.message(F.text.in_({"Русский", "English"}))
async def set_language_message(message: Message) -> None:
    language = "en" if message.text == "English" else "ru"
    lang, access, user = await save_user_language(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        language=language,
    )

    if access["has_access"]:
        await message.answer(
            build_active_home_text(
                lang=lang,
                expiry=access["expiry"],
                access_type=access["access_type"],
                traffic_used=user.traffic_used if user else 0,
                traffic_limit=user.traffic_limit if user else 3072,
            ),
            reply_markup=get_active_home_inline_keyboard(lang, access["access_type"]),
            parse_mode="HTML",
        )
        return

    await message.answer(
        get_welcome_text(lang),
        reply_markup=get_start_inline_keyboard(lang),
        disable_web_page_preview=True,
        parse_mode="HTML",
    )
