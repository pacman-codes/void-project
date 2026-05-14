from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import select
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.user import (
    SUPPORT_URL,
    get_instruction_inline_keyboard,
    get_instruction_platform_inline_keyboard,
)
from db.database import async_session_maker
from db.models import User, VPNAccess
from services.user_service import get_user
from services.vpn_service import VPNService, VPNServiceError
from utils.buttons import INSTRUCTION_EN, INSTRUCTION_RU

router = Router()


HAPP_DOWNLOAD_URLS = {
    "ios": "https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973",
    "android": "https://play.google.com/store/apps/details?id=com.happproxy",
    "android_apk": "https://disk.yandex.ru/d/L7LZFitZiiYSNQ",
    "windows": "https://disk.yandex.ru/d/L7LZFitZiiYSNQ",
    "macos": "https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973",
    "linux": "https://disk.yandex.ru/d/L7LZFitZiiYSNQ",
    "appletv": "https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973",
    "androidtv": "https://play.google.com/store/apps/details?id=com.happproxy",
}


def build_main_instruction_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if lang == "en":
        builder.button(text="🛠 Detailed instruction", callback_data="open_detailed_instruction")
        builder.button(text="iOS", url=HAPP_DOWNLOAD_URLS["ios"])
        builder.button(text="Android (Google Play)", url=HAPP_DOWNLOAD_URLS["android"])
        builder.button(text="Android (APK)", url=HAPP_DOWNLOAD_URLS["android_apk"])
        builder.button(text="Windows", url=HAPP_DOWNLOAD_URLS["windows"])
        builder.button(text="MacOS", url=HAPP_DOWNLOAD_URLS["macos"])
        builder.button(text="Linux", url=HAPP_DOWNLOAD_URLS["linux"])
        builder.button(text="AppleTV", url=HAPP_DOWNLOAD_URLS["appletv"])
        builder.button(text="AndroidTV", url=HAPP_DOWNLOAD_URLS["androidtv"])
        builder.button(text="🏠 Home", callback_data="back_home")
    else:
        builder.button(text="🛠 Подробная инструкция", callback_data="open_detailed_instruction")
        builder.button(text="iOS", url=HAPP_DOWNLOAD_URLS["ios"])
        builder.button(text="Android (Google Play)", url=HAPP_DOWNLOAD_URLS["android"])
        builder.button(text="Android (APK)", url=HAPP_DOWNLOAD_URLS["android_apk"])
        builder.button(text="Windows", url=HAPP_DOWNLOAD_URLS["windows"])
        builder.button(text="MacOS", url=HAPP_DOWNLOAD_URLS["macos"])
        builder.button(text="Linux", url=HAPP_DOWNLOAD_URLS["linux"])
        builder.button(text="AppleTV", url=HAPP_DOWNLOAD_URLS["appletv"])
        builder.button(text="AndroidTV", url=HAPP_DOWNLOAD_URLS["androidtv"])
        builder.button(text="🏠 На главную", callback_data="back_home")

    builder.adjust(1, 1, 2, 2, 2, 2, 1)
    return builder.as_markup()


def build_detailed_instruction_text(lang: str) -> str:
    if lang == "en":
        return (
            "📖 <b>Detailed instruction</b>\n\n"
            "1. Download the app for your device.\n"
            "2. Open <b>Connection</b> in this bot.\n"
            "3. Tap your link to copy it.\n"
            "4. Open the app.\n"
            "5. Find import/add subscription.\n"
            "6. Paste the copied link.\n"
            "7. Save and tap connect ✅\n\n"
            f'If something does not work, contact <a href="{SUPPORT_URL}">support</a>.'
        )

    return (
        "📖 <b>Подробная инструкция</b>\n\n"
        "1. Скачай приложение для своего устройства.\n"
        "2. Здесь же, в боте, открой <b>Подключение</b>.\n"
        "3. Нажми на свою ссылку, чтобы скопировать её.\n"
        "4. Открой приложение.\n"
        "5. Найди импорт/добавление подписки.\n"
        "6. Вставь скопированную ссылку.\n"
        "7. Сохрани и нажми подключение ✅\n\n"
        f'Если что-то не получается, напиши в <a href="{SUPPORT_URL}">поддержку</a>.'
    )

PLATFORM_TITLES = {
    "ios": {"ru": "iPhone / iPad", "en": "iPhone / iPad"},
    "android": {"ru": "Android", "en": "Android"},
    "windows": {"ru": "Windows", "en": "Windows"},
    "macos": {"ru": "macOS", "en": "macOS"},
}


def build_instruction_text(lang: str) -> str:
    if lang == "en":
        return (
            "📖 <b>Instruction</b>\n\n"
            "1. Download the app for your device using the buttons below.\n"
            "2. In this bot, open <b>Connection</b>.\n"
            "3. Tap your link to copy it.\n"
            "4. Paste it into the app.\n"
            "5. Tap connect ✅"
        )

    return (
        "📖 <b>Инструкция:</b>\n\n"
        "1. Скачай приложение для своего устройства (ссылки ниже)\n"
        "2. Здесь же, в боте, открой <b>Подключение</b>\n"
        "3. Нажми на свою ссылку, чтобы скопировать её\n"
        "4. Вставь её в приложение\n"
        "5. Нажми «Подключиться» ✅"
    )


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
    except VPNServiceError:
        return None
    except Exception:
        return None


@router.message(F.text.in_([INSTRUCTION_RU, INSTRUCTION_EN]))
async def instruction_handler(message: Message) -> None:
    if message.from_user is None:
        return

    lang = await get_lang(message.from_user.id)

    await message.answer(
        build_instruction_text(lang),
        reply_markup=build_main_instruction_keyboard(lang),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "open_instruction")
async def open_instruction(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)

    await callback.message.edit_text(
        build_instruction_text(lang),
        reply_markup=build_main_instruction_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_instruction_devices")
async def back_to_devices(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)

    await callback.message.edit_text(
        build_instruction_text(lang),
        reply_markup=build_main_instruction_keyboard(lang),
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


@router.callback_query(F.data == "open_detailed_instruction")
async def open_detailed_instruction(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)

    await callback.message.edit_text(
        build_detailed_instruction_text(lang),
        reply_markup=build_main_instruction_keyboard(lang),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()
