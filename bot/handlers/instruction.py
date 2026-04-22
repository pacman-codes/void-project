from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from bot.keyboards.user import (
    SUPPORT_URL,
    get_instruction_inline_keyboard,
    get_instruction_platform_inline_keyboard,
)
from db.database import async_session_maker
from db.models import User, VPNAccess
from services.user_service import get_user
from services.vpn_service import VPNService
from utils.buttons import INSTRUCTION_EN, INSTRUCTION_RU

router = Router()

PLATFORM_TITLES = {
    "ios": {"ru": "iPhone / iPad", "en": "iPhone / iPad"},
    "android": {"ru": "Android", "en": "Android"},
    "windows": {"ru": "Windows", "en": "Windows"},
    "macos": {"ru": "macOS", "en": "macOS"},
}


def build_instruction_text(lang: str) -> str:
    if lang == "en":
        return "📘 <b>Instruction</b>\n\nChoose your device:"
    return "📘 <b>Инструкция</b>\n\nВыберите ваше устройство:"


def build_platform_instruction_text(
    lang: str,
    platform: str,
    config_url: str | None,
) -> str:
    title = PLATFORM_TITLES[platform]["en" if lang == "en" else "ru"]

    safe_config = escape(config_url) if config_url else "..."

    if lang == "en":
        return (
            f"📲 <b>How to connect on {title}</b>\n\n"
            "1. Download <b>Happ</b> using the button below and come back here.\n\n"
            "2. Copy your personal key below.\n\n"
            "3. Open Happ, tap <b>Add / Import</b>, paste the key and enable the connection.\n\n"
            f"<code>{safe_config}</code>\n\n"
            f'👨🏻‍💻 If something does not work, contact our <a href="{SUPPORT_URL}">technical support</a>.'
        )

    return (
        f"📲 <b>Для подключения на {title}</b>\n\n"
        "1. Скачайте приложение <b>Happ</b> по кнопке ниже и вернитесь сюда.\n\n"
        "2. Скопируйте ваш ключ ниже.\n\n"
        "3. Откройте Happ, нажмите <b>Добавить / Импорт</b>, вставьте ключ и включите подключение.\n\n"
        f"<code>{safe_config}</code>\n\n"
        f'👨🏻‍💻 Если что-то не получается, напишите в нашу <a href="{SUPPORT_URL}">техническую поддержку</a>.'
    )


async def get_lang(user_id: int) -> str:
    user = await get_user(user_id)
    if user and user.language:
        return user.language
    return "ru"


async def get_primary_config_url(telegram_id: int) -> str | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(VPNAccess.config_url)
            .join(User, User.id == VPNAccess.user_id)
            .where(User.telegram_id == telegram_id, VPNAccess.device_number == 1)
        )
        config_url = result.scalar_one_or_none()

    if config_url:
        return config_url

    try:
        service = VPNService()
        result = await service.ensure_vpn_access_record(
            telegram_id=telegram_id,
            device_number=1,
            device_name="Устройство 1",
        )
        return result.get("config_url")
    except Exception:
        return None


@router.message(F.text.in_([INSTRUCTION_RU, INSTRUCTION_EN]))
async def instruction_handler(message: Message) -> None:
    if message.from_user is None:
        return

    lang = await get_lang(message.from_user.id)

    await message.answer(
        build_instruction_text(lang),
        reply_markup=get_instruction_inline_keyboard(lang),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "open_instruction")
async def open_instruction(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)

    await callback.message.edit_text(
        build_instruction_text(lang),
        reply_markup=get_instruction_inline_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_instruction_devices")
async def back_to_devices(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)

    await callback.message.edit_text(
        build_instruction_text(lang),
        reply_markup=get_instruction_inline_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    F.data.in_(
        [
            "instruction_ios",
            "instruction_android",
            "instruction_windows",
            "instruction_macos",
        ]
    )
)
async def open_platform_instruction(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)
    platform = callback.data.replace("instruction_", "")

    config_url = await get_primary_config_url(callback.from_user.id)

    if not config_url:
        await callback.answer(
            "Не удалось подготовить ссылку подключения."
            if lang == "ru"
            else "Failed to prepare connection link.",
            show_alert=True,
        )
        return

    await callback.message.edit_text(
        build_platform_instruction_text(lang, platform, config_url),
        reply_markup=get_instruction_platform_inline_keyboard(
            platform=platform,
            lang=lang,
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()
