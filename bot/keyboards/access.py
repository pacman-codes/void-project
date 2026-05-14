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


def get_after_regenerate_key_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🔑 Devices" if lang == "en" else "🔑 Устройства",
        callback_data="open_add_device",
        style="primary",
    )
    builder.button(
        text="📘 Instruction" if lang == "en" else "📘 Инструкция",
        callback_data="open_instruction",
    )
    builder.button(
        text="🏠 Home" if lang == "en" else "🏠 Главная",
        callback_data="back_home",
    )

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def get_confirm_regenerate_key_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Yes, refresh key" if lang == "en" else "✅ Да, обновить ключ",
        callback_data="confirm_regenerate_key",
        style="danger",
    )
    builder.button(
        text="⬅️ Back" if lang == "en" else "⬅️ Назад",
        callback_data="open_support",
    )

    builder.adjust(1, 1)
    return builder.as_markup()


def get_access_inline_keyboard(
    lang: str | None = None,
    access_type: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if _is_paid(access_type):
        builder.button(
            text="Renew access" if lang == "en" else "Продлить доступ",
            callback_data="open_renew",
            style="success",
        )
        builder.button(
            text="🔑 Devices" if lang == "en" else "🔑 Устройства",
            callback_data="open_add_device",
            style="primary",
        )
    else:
        builder.button(
            text="💎 Full access" if lang == "en" else "💎 Полный доступ",
            callback_data="open_subscription",
            style="success",
        )

    builder.button(
        text="📘 Instruction" if lang == "en" else "📘 Инструкция",
        callback_data="open_instruction",
    )
    builder.button(
        text="❌ Not working" if lang == "en" else "❌ Не работает",
        callback_data="open_support",
        style="danger",
    )
    builder.button(
        text="🏠 Home" if lang == "en" else "🏠 Главная",
        callback_data="back_home",
    )

    if _is_paid(access_type):
        builder.adjust(2, 2, 1)
    else:
        builder.adjust(1, 2, 1)

    return builder.as_markup()


def get_device_limit_reached_keyboard(
    lang: str | None = None,
    access_type: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if _is_paid(access_type):
        if lang == "en":
            builder.button(
                text="🔑 Add one more device — 79 ₽/month",
                callback_data="open_extra_device_offer",
                style="success",
            )
            builder.button(text="🏠 Home", callback_data="back_home")
        else:
            builder.button(
                text="🔑 Добавить ещё одно устройство — 79 ₽/мес",
                callback_data="open_extra_device_offer",
                style="success",
            )
            builder.button(text="🏠 Главная", callback_data="back_home")
        builder.adjust(1, 1)
        return builder.as_markup()

    if lang == "en":
        builder.button(
            text="PRO plan 🤌",
            callback_data="open_subscription",
            style="success",
        )
        builder.button(text="🏠 Home", callback_data="back_home")
    else:
        builder.button(
            text="Тариф PRO 🤌",
            callback_data="open_subscription",
            style="success",
        )
        builder.button(text="🏠 Главная", callback_data="back_home")

    builder.adjust(1, 1)
    return builder.as_markup()
