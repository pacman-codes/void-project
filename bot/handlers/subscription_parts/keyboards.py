from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import VPNAccess


def build_legal_keyboard(lang: str, action: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if lang == "en":
        builder.button(text="I agree", callback_data=f"legal_accept:{action}", style="success")
        builder.button(text="Back", callback_data="back_from_legal")
    else:
        builder.button(text="Я согласен", callback_data=f"legal_accept:{action}", style="success")
        builder.button(text="Назад", callback_data="back_from_legal")

    builder.adjust(1, 1)
    return builder.as_markup()


def build_tariffs_keyboard(lang: str, source: str = "subscription") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    back_callback = "back_home" if source == "renew" else "back_to_subscription"

    if lang == "en":
        builder.button(text="💳 1 month", callback_data="plan_1m")
        builder.button(text="🔥 6 months", callback_data="plan_6m")
        builder.button(text="🚀 12 months", callback_data="plan_12m", style="success")
        builder.button(text="Back", callback_data=back_callback)
    else:
        builder.button(text="💳 1 месяц", callback_data="plan_1m")
        builder.button(text="🔥 6 месяцев", callback_data="plan_6m")
        builder.button(text="🚀 12 месяцев", callback_data="plan_12m", style="success")
        builder.button(text="Назад", callback_data=back_callback)

    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def build_open_payment_url_keyboard(lang: str, payment_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if lang == "en":
        builder.button(text="Go to payment", url=payment_url, style="success")
        builder.button(text="Home", callback_data="back_home")
    else:
        builder.button(text="Перейти к оплате", url=payment_url, style="success")
        builder.button(text="Главная", callback_data="back_home")

    builder.adjust(1, 1)
    return builder.as_markup()


def build_devices_keyboard(
    lang: str,
    access_type: str | None,
    accesses: list[VPNAccess] | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if access_type == "paid":
        builder.button(
            text="🔑 Add device" if lang == "en" else "🔑 Добавить устройство",
            callback_data="open_extra_device_offer",
            style="primary",
        )
    else:
        builder.button(
            text="PRO plan 🤌" if lang == "en" else "Тариф PRO 🤌",
            callback_data="open_subscription",
            style="success",
        )

    builder.button(
        text="🏠 Home" if lang == "en" else "🏠 Главная",
        callback_data="back_home",
    )

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def build_regenerate_device_confirm_keyboard(lang: str, device_number: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Yes, refresh" if lang == "en" else "✅ Да, обновить",
        callback_data=f"confirm_regenerate_device:{device_number}",
        style="danger",
    )
    builder.button(
        text="⬅️ Back" if lang == "en" else "⬅️ Назад",
        callback_data="open_add_device",
    )

    builder.adjust(1, 1)
    return builder.as_markup()


def build_regenerate_all_confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Yes, refresh all" if lang == "en" else "✅ Да, обновить все",
        callback_data="confirm_regenerate_all_keys",
        style="danger",
    )
    builder.button(
        text="⬅️ Back" if lang == "en" else "⬅️ Назад",
        callback_data="open_add_device",
    )

    builder.adjust(1, 1)
    return builder.as_markup()


def build_payment_keyboard_local(lang: str, plan_code: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if lang == "en":
        builder.button(text="Pay", callback_data=f"pay_{plan_code}", style="success")
        builder.button(text="Back to plans", callback_data="open_renew")
    else:
        builder.button(text="Оплатить", callback_data=f"pay_{plan_code}", style="success")
        builder.button(text="К тарифам", callback_data="open_renew")

    builder.adjust(1, 1)
    return builder.as_markup()
