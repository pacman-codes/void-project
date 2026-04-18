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
            text="➕ Add device" if lang == "en" else "➕ Добавить устройство",
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
        text="🌐 Language" if lang == "en" else "🌐 Язык",
        callback_data="open_language",
    )
    builder.adjust(1, 2, 1)
    return builder.as_markup()


def get_post_payment_inline_keyboard(
    lang: str | None = None,
    access_type: str | None = None,
) -> InlineKeyboardMarkup:
    return get_active_home_inline_keyboard(lang, access_type)


def get_account_inline_keyboard(
    lang: str | None = None,
    access_type: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text=get_primary_cta_text(lang, access_type),
        callback_data="open_renew" if _is_paid(access_type) else "open_subscription",
        style="success",
    )

    if _is_paid(access_type):
        builder.button(
            text="➕ Add device" if lang == "en" else "➕ Добавить устройство",
            callback_data="open_add_device",
            style="primary",
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
        builder.adjust(1, 1, 2, 1)
    else:
        builder.adjust(1, 2, 1)

    return builder.as_markup()


def get_instruction_inline_keyboard(
    lang: str | None = None,
    access_type: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text=get_primary_cta_text(lang, access_type),
        callback_data="open_renew" if _is_paid(access_type) else "open_subscription",
        style="success",
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
    builder.button(
        text="🏠 Home" if lang == "en" else "🏠 Главная",
        callback_data="back_home",
    )

    builder.adjust(1, 2, 1)
    return builder.as_markup()


def get_support_inline_keyboard(
    lang: str | None = None,
    access_type: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text=get_primary_cta_text(lang, access_type),
        callback_data="open_renew" if _is_paid(access_type) else "open_subscription",
        style="success",
    )

    if _is_paid(access_type):
        builder.button(
            text="➕ Add device" if lang == "en" else "➕ Добавить устройство",
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
        text="🏠 Home" if lang == "en" else "🏠 Главная",
        callback_data="back_home",
    )

    if _is_paid(access_type):
        builder.adjust(1, 1, 2, 1)
    else:
        builder.adjust(1, 2, 1)

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
            text="➕ Add device" if lang == "en" else "➕ Добавить устройство",
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
                text="➕ Add one more device — 79 ₽/month",
                callback_data="open_extra_device_offer",
                style="success",
            )
            builder.button(text="🏠 Home", callback_data="back_home")
        else:
            builder.button(
                text="➕ Добавить ещё одно устройство — 79 ₽/мес",
                callback_data="open_extra_device_offer",
                style="success",
            )
            builder.button(text="🏠 Главная", callback_data="back_home")
        builder.adjust(1, 1)
        return builder.as_markup()

    if lang == "en":
        builder.button(
            text="💎 Get full access",
            callback_data="open_subscription",
            style="success",
        )
        builder.button(text="🏠 Home", callback_data="back_home")
    else:
        builder.button(
            text="💎 Получить полный доступ",
            callback_data="open_subscription",
            style="success",
        )
        builder.button(text="🏠 Главная", callback_data="back_home")

    builder.adjust(1, 1)
    return builder.as_markup()


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


def get_active_main_menu_keyboard(lang: str | None = None) -> ReplyKeyboardRemove:
    return get_remove_keyboard()


def get_main_keyboard(lang: str | None = None) -> ReplyKeyboardRemove:
    return get_remove_keyboard()
