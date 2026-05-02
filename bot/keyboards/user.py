"""Compatibility exports for user keyboards.

Keep this file small. New keyboard code should go into focused modules:
- bot/keyboards/common.py
- bot/keyboards/home.py
- bot/keyboards/tariffs.py
- bot/keyboards/account.py
- bot/keyboards/instruction.py
- bot/keyboards/support.py
- bot/keyboards/access.py
- bot/keyboards/devices.py
"""


from bot.keyboards.legacy import (
    CHANNEL_HANDLE,
    CHANNEL_URL,
    HAPP_DOWNLOAD_URLS,
    SUPPORT_URL,
    get_payment_keyboard,
)
from bot.keyboards.access import (
    get_access_inline_keyboard,
    get_after_regenerate_key_keyboard,
    get_confirm_regenerate_key_keyboard,
    get_device_limit_reached_keyboard,
)
from bot.keyboards.account import get_account_inline_keyboard
from bot.keyboards.common import (
    get_active_main_menu_keyboard,
    get_language_inline_keyboard,
    get_language_keyboard,
    get_main_keyboard,
    get_remove_keyboard,
)
from bot.keyboards.devices import (
    get_extra_device_offer_keyboard,
    get_extra_device_pending_keyboard,
)
from bot.keyboards.home import (
    get_active_home_inline_keyboard,
    get_post_payment_inline_keyboard,
    get_primary_cta_text,
    get_start_inline_keyboard,
    get_welcome_text,
)
from bot.keyboards.instruction import (
    get_instruction_inline_keyboard,
    get_instruction_platform_inline_keyboard,
)
from bot.keyboards.support import get_support_inline_keyboard
from bot.keyboards.tariffs import get_tariff_inline_keyboard

__all__ = [
    "get_payment_keyboard",
    "SUPPORT_URL",
    "HAPP_DOWNLOAD_URLS",
    "CHANNEL_HANDLE",
    "CHANNEL_URL",
    "get_access_inline_keyboard",
    "get_active_home_inline_keyboard",
    "get_active_main_menu_keyboard",
    "get_after_regenerate_key_keyboard",
    "get_account_inline_keyboard",
    "get_confirm_regenerate_key_keyboard",
    "get_device_limit_reached_keyboard",
    "get_extra_device_offer_keyboard",
    "get_extra_device_pending_keyboard",
    "get_instruction_inline_keyboard",
    "get_instruction_platform_inline_keyboard",
    "get_language_inline_keyboard",
    "get_language_keyboard",
    "get_main_keyboard",
    "get_post_payment_inline_keyboard",
    "get_primary_cta_text",
    "get_remove_keyboard",
    "get_start_inline_keyboard",
    "get_support_inline_keyboard",
    "get_tariff_inline_keyboard",
    "get_welcome_text",
]
