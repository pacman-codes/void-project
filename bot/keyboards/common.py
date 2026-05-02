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

def get_language_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Русский"), KeyboardButton(text="English")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove(remove_keyboard=True)


def get_language_inline_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🇷🇺 Русский", callback_data="set_lang_ru")
    builder.button(text="🇬🇧 English", callback_data="set_lang_en")
    builder.adjust(2)
    return builder.as_markup()


def get_active_main_menu_keyboard(lang: str | None = None) -> ReplyKeyboardRemove:
    return get_remove_keyboard()


def get_main_keyboard(lang: str | None = None) -> ReplyKeyboardRemove:
    return get_remove_keyboard()
