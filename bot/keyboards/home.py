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


def get_welcome_text(lang: str | None = None) -> str:
    if lang == "en":
        return (
            "🚀 <b>Internet accelerator</b>\n\n"
            "Stable and fast connection\n"
            "without extra setup\n\n"
            "⚡ High speed\n"
            "🔒 Privacy\n"
            "🌍 Reliable operation\n\n"
            "📱 Setup in 1 minute\n\n"
            "👇 Start"
        )

    return (
        "🚀 <b>Ускоритель интернета</b>\n\n"
        "Стабильное и быстрое подключение\n"
        "без лишних настроек\n\n"
        "⚡ Высокая скорость\n"
        "🔒 Приватность\n"
        "🌍 Надёжная работа\n\n"
        "📱 Подключение за 1 минуту\n\n"
        "👇 Начните"
    )


def get_start_inline_keyboard(lang: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if lang == "en":
        builder.button(text="🚀 Start", callback_data="open_subscription", style="success")
        builder.button(text="🌐 Language", callback_data="open_language")
    else:
        builder.button(text="🚀 Начать", callback_data="open_subscription", style="success")
        builder.button(text="🌐 Язык", callback_data="open_language")

    builder.adjust(1, 1)
    return builder.as_markup()


def get_primary_cta_text(lang: str | None, access_type: str | None) -> str:
    if _is_paid(access_type):
        return "Renew access" if lang == "en" else "Продлить доступ"
    return "💎 Full access" if lang == "en" else "💎 Полный доступ"


def get_active_home_inline_keyboard(
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
        builder.button(
            text="📘 Instruction" if lang == "en" else "📘 Инструкция",
            callback_data="open_instruction",
        )
        builder.button(
            text="🌐 Language" if lang == "en" else "🌐 Язык",
            callback_data="open_language",
        )
        builder.button(
            text="❌ Not working" if lang == "en" else "❌ Не работает",
            callback_data="open_support",
            style="danger",
        )
        builder.adjust(1, 1, 2, 1)
        return builder.as_markup()

    builder.button(
        text="💎 Get full access" if lang == "en" else "💎 Получить полный доступ",
        callback_data="open_subscription",
        style="success",
    )
    builder.button(
        text="📘 Instruction" if lang == "en" else "📘 Инструкция",
        callback_data="open_instruction",
        style="primary",
    )
    builder.button(
        text="❌ Not working" if lang == "en" else "❌ Не работает",
        callback_data="open_support",
        style="danger",
    )
    builder.button(
        text="🔑 Devices" if lang == "en" else "🔑 Устройства",
        callback_data="open_add_device",
        style="primary",
    )
    builder.button(
        text="🌐 Language" if lang == "en" else "🌐 Язык",
        callback_data="open_language",
        style="primary",
    )
    builder.adjust(1, 2, 2)
    return builder.as_markup()


def get_post_payment_inline_keyboard(
    lang: str | None = None,
    access_type: str | None = None,
) -> InlineKeyboardMarkup:
    return get_active_home_inline_keyboard(lang, access_type)
