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

def get_tariff_inline_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if lang == "en":
        builder.button(text="🎁 Free", callback_data="subscription_free", style="primary")
        builder.button(text="💎 Full access", callback_data="subscription_paid", style="success")
    else:
        builder.button(text="🎁 Бесплатно", callback_data="subscription_free", style="primary")
        builder.button(text="💎 Полный доступ", callback_data="subscription_paid", style="success")

    builder.adjust(1, 1)
    return builder.as_markup()
