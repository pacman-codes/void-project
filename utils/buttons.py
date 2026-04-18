MAIN_MENU_RU = "🏠 Главное меню"
MAIN_MENU_EN = "🏠 Main menu"

MY_ACCOUNT_RU = "👤 Мой аккаунт"
MY_ACCOUNT_EN = "👤 My account"

SUBSCRIPTION_RU = "💳 Подписка"
SUBSCRIPTION_EN = "💳 Subscription"

RENEW_RU = "💳 Продлить доступ"
RENEW_EN = "💳 Renew access"

TRIAL_RU = "🎁 Пробный период"
TRIAL_EN = "🎁 Trial"

GET_VPN_RU = "🔐 Получить доступ"
GET_VPN_EN = "🔐 Get access"

INSTRUCTION_RU = "📘 Инструкция"
INSTRUCTION_EN = "📘 Instruction"

SUPPORT_RU = "💬 Поддержка"
SUPPORT_EN = "💬 Support"

LANGUAGE_RU = "🌐 Язык"
LANGUAGE_EN = "🌐 Language"


BUTTONS = {
    "ru": {
        "main_menu": MAIN_MENU_RU,
        "my_account": MY_ACCOUNT_RU,
        "subscription": SUBSCRIPTION_RU,
        "renew": RENEW_RU,
        "trial": TRIAL_RU,
        "get_vpn": GET_VPN_RU,
        "instruction": INSTRUCTION_RU,
        "support": SUPPORT_RU,
        "language": LANGUAGE_RU,
    },
    "en": {
        "main_menu": MAIN_MENU_EN,
        "my_account": MY_ACCOUNT_EN,
        "subscription": SUBSCRIPTION_EN,
        "renew": RENEW_EN,
        "trial": TRIAL_EN,
        "get_vpn": GET_VPN_EN,
        "instruction": INSTRUCTION_EN,
        "support": SUPPORT_EN,
        "language": LANGUAGE_EN,
    },
}


def is_button(text: str | None, *button_keys: str) -> bool:
    if not text:
        return False

    for language_buttons in BUTTONS.values():
        for button_key in button_keys:
            button_text = language_buttons.get(button_key)
            if button_text == text:
                return True

    return False


def get_button_text(language: str, key: str) -> str:
    normalized_language = "en" if language == "en" else "ru"
    return BUTTONS.get(normalized_language, BUTTONS["ru"]).get(key, key)
