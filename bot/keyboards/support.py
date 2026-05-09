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

def _is_paid(access_type: str | None) -> bool:
    return access_type == "paid"


def get_support_inline_keyboard(
    lang: str | None = None,
    access_type: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="💬 Contact support" if lang == "en" else "💬 Написать в поддержку",
        url=SUPPORT_URL,
    )
    builder.button(
        text="📘 Instruction" if lang == "en" else "📘 Инструкция",
        callback_data="open_instruction",
    )
    builder.button(
        text="🌐 Language" if lang == "en" else "🌐 Язык",
        callback_data="open_language",
    )
    builder.button(
        text="🏠 Home" if lang == "en" else "🏠 Главная",
        callback_data="back_home",
    )

    builder.adjust(1, 1, 2)
    return builder.as_markup()
