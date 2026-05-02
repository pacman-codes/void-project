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

def get_extra_device_offer_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if lang == "en":
        builder.button(
            text="💳 Pay 79 ₽",
            callback_data="extra_device_pay",
            style="success",
        )
        builder.button(text="🏠 Home", callback_data="back_home")
    else:
        builder.button(
            text="💳 Оплатить 79 ₽",
            callback_data="extra_device_pay",
            style="success",
        )
        builder.button(text="🏠 Главная", callback_data="back_home")

    builder.adjust(1, 1)
    return builder.as_markup()


def get_extra_device_pending_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if lang == "en":
        builder.button(
            text="🔄 Check payment",
            callback_data="extra_device_check",
            style="primary",
        )
        builder.button(text="🏠 Home", callback_data="back_home")
    else:
        builder.button(
            text="🔄 Проверить оплату",
            callback_data="extra_device_check",
            style="primary",
        )
        builder.button(text="🏠 Главная", callback_data="back_home")

    builder.adjust(1, 1)
    return builder.as_markup()
