from aiogram.types import (
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.buttons import (
    INSTRUCTION_EN,
    INSTRUCTION_RU,
    LANGUAGE_EN,
    LANGUAGE_RU,
    MY_ACCOUNT_EN,
    MY_ACCOUNT_RU,
)

CHANNEL_HANDLE = "@voidOroProject"
CHANNEL_URL = "https://t.me/voidOroProject"
SUPPORT_URL = "https://t.me/voidModeSupport"

HAPP_DOWNLOAD_URLS = {
    "ios": "https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973",
    "android": "https://play.google.com/store/apps/details?id=com.happproxy",
    "windows": "https://disk.yandex.ru/d/L7LZFitZiiYSNQ",
    "macos": "https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973",
}

def get_instruction_inline_keyboard(
    lang: str | None = None,
    access_type: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="📱 iPhone / iPad" if lang == "en" else "📱 iPhone / iPad",
        callback_data="instruction_ios",
    )
    builder.button(
        text="📱 Android" if lang == "en" else "📱 Android",
        callback_data="instruction_android",
    )
    builder.button(
        text="🖥️ Windows" if lang == "en" else "🖥️ Windows",
        callback_data="instruction_windows",
    )
    builder.button(
        text="💻 macOS" if lang == "en" else "💻 macOS",
        callback_data="instruction_macos",
    )

    builder.adjust(2, 2)
    return builder.as_markup()


def get_instruction_platform_inline_keyboard(
    platform: str,
    lang: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    download_url = HAPP_DOWNLOAD_URLS.get(platform, "").strip()

    if download_url:
        builder.button(
            text="⬇️ Download Happ" if lang == "en" else "⬇️ Скачать Happ",
            url=download_url,
        )

    builder.button(
        text="⬅️ Back" if lang == "en" else "⬅️ Назад",
        callback_data="open_instruction",
    )

    builder.button(
        text="🏠 Home" if lang == "en" else "🏠 Главная",
        callback_data="back_home",
    )

    builder.adjust(1, 1, 1)
    return builder.as_markup()
