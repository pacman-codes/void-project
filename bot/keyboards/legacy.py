"""Legacy compatibility exports for old bot.keyboards.user imports.

New code should use focused keyboard modules instead.
"""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

CHANNEL_HANDLE = "@voidOroProject"
CHANNEL_URL = "https://t.me/voidOroProject"
SUPPORT_URL = "https://t.me/voidModeSupport"

HAPP_DOWNLOAD_URLS = {
    "ios": "https://apps.apple.com/app/happ-proxy-utility/id6504287215",
    "android": "https://play.google.com/store/apps/details?id=com.happproxy",
    "windows": "https://github.com/Happ-proxy/happ-desktop/releases",
    "macos": "https://github.com/Happ-proxy/happ-desktop/releases",
}


def get_payment_keyboard(payment_url: str, lang: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if lang == "en":
        builder.button(text="Go to payment", url=payment_url)
        builder.button(text="Home", callback_data="back_home")
    else:
        builder.button(text="Перейти к оплате", url=payment_url)
        builder.button(text="Главная", callback_data="back_home")

    builder.adjust(1, 1)
    return builder.as_markup()
