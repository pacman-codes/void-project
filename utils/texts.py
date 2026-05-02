texts = {
    "ru": {
        "not_found": "Пользователь не найден",
        "error": "Произошла ошибка. Попробуйте позже.",
        "access_paid": "Активен 👑",
        "access_free": "Бесплатный ⚡",
        "access_type_free": "Бесплатный",
        "access_type_paid": "Платный",
        "access_type_none": "Отсутствует",
        "no_access": "У вас нет доступа.",
        "access_ready": "Подключение готово ✅\n\n{config}",
        "buy": "Подписка успешно активирована ✅",
    },
    "en": {
        "not_found": "User not found",
        "error": "An error occurred. Please try again later.",
        "access_paid": "Active 👑",
        "access_free": "Free ⚡",
        "access_type_free": "Free",
        "access_type_paid": "Paid",
        "access_type_none": "None",
        "no_access": "You don't have access.",
        "access_ready": "Connection is ready ✅\n\n{config}",
        "buy": "Subscription activated successfully ✅",
    },
}


def get_text(lang: str, key: str, default: str | None = None) -> str:
    lang = lang if lang in texts else "ru"
    value = texts.get(lang, {}).get(key)

    if value is not None:
        return value

    if default is not None:
        return default

    return key


def get_access_denied_text(lang: str, reason: str | None = None) -> str:
    if lang == "en":
        if reason == "traffic_limit":
            return "Traffic limit has been reached. Upgrade to full access to continue."
        if reason == "expired":
            return "Access has expired. Renew access to continue."
        if reason == "device_limit":
            return "Device limit has been reached."
        if reason == "no_access":
            return "Access is not active. Choose a plan to continue."
        return "Access is not available."

    if reason == "traffic_limit":
        return "Лимит трафика исчерпан. Перейдите на полный доступ, чтобы продолжить."
    if reason == "expired":
        return "Доступ истёк. Продлите доступ, чтобы продолжить."
    if reason == "device_limit":
        return "Лимит устройств исчерпан."
    if reason == "no_access":
        return "Доступ не активен. Выберите тариф, чтобы продолжить."
    return "Доступ недоступен."
