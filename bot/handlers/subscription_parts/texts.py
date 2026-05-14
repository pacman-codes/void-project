from decimal import Decimal

from config.links import OFFER_URL, PRIVACY_URL, RULES_URL
from config.pricing import (
    PARTNER_OFFER_PRICE_1M_RUB,
    PARTNER_OFFER_PRICE_6M_RUB,
)
from services.payment_service import (
    LAUNCH_OFFER_LIMIT,
    get_plan_amount,
)


def build_subscription_text(lang: str) -> str:
    if lang == "en":
        return (
            "💼 <b>Choose access</b>\n\n"
            "🎁 <b>Free</b>\n"
            "For basic use\n"
            "• 1 device\n"
            "• up to 3 GB / month\n\n"
            "💎 <b>Full access</b>\n"
            "For comfortable daily use\n"
            "• high speed\n"
            "• up to 7 devices available\n"
            "• no limits\n\n"
            "💡 Setup takes less than a minute"
        )

    return (
        "💼 <b>Выберите доступ</b>\n\n"
        "🎁 <b>Бесплатный</b>\n"
        "Для базового использования\n"
        "• 1 устройство\n"
        "• до 3 ГБ / месяц\n\n"
        "💎 <b>Полный доступ</b>\n"
        "Для комфортной работы\n"
        "• высокая скорость\n"
        "• до 7 устройств доступно\n"
        "• без ограничений\n\n"
        "💡 Подключение занимает меньше минуты"
    )


def build_legal_text(lang: str) -> str:
    if lang == "en":
        return (
            "📄 <b>Please review the terms before continuing:</b>\n\n"
            f'<a href="{OFFER_URL}">Offer</a>\n'
            f'<a href="{PRIVACY_URL}">Privacy Policy</a>\n'
            f'<a href="{RULES_URL}">Rules of Use</a>\n\n'
            "By pressing “I agree”, you confirm that you have read and accept these terms."
        )

    return (
        "📄 <b>Перед продолжением ознакомьтесь с условиями:</b>\n\n"
        f'<a href="{OFFER_URL}">Оферта</a>\n'
        f'<a href="{PRIVACY_URL}">Политика конфиденциальности</a>\n'
        f'<a href="{RULES_URL}">Правила использования</a>\n\n'
        "Нажимая кнопку «Я согласен», Вы подтверждаете, что ознакомились и принимаете указанные условия."
    )


def format_price(amount: Decimal) -> str:
    return f"{int(amount)} ₽"


def build_tariffs_text(
    lang: str,
    use_launch_offer: bool,
    used_count: int,
    use_partner_offer: bool = False,
) -> str:
    month_price = (
        format_price(Decimal(str(PARTNER_OFFER_PRICE_1M_RUB)))
        if use_partner_offer
        else format_price(get_plan_amount("plan_1m", use_launch_offer))
    )
    half_year_price = (
        format_price(Decimal(str(PARTNER_OFFER_PRICE_6M_RUB)))
        if use_partner_offer
        else format_price(get_plan_amount("plan_6m", use_launch_offer))
    )
    year_price = format_price(get_plan_amount("plan_12m", use_launch_offer))

    if use_partner_offer:
        if lang == "en":
            promo_block = (
                "✨ <b>Special offer</b>\n"
                "Available only for your first paid purchase\n\n"
            )
        else:
            promo_block = (
                "✨ <b>Специальное предложение</b>\n"
                "Доступно только для первой paid-оплаты\n\n"
            )
    elif use_launch_offer:
        left_slots = max(LAUNCH_OFFER_LIMIT - used_count, 0)
        if lang == "en":
            promo_block = (
                "🔥 <b>Launch offer</b>\n"
                f"First {LAUNCH_OFFER_LIMIT} paid purchases — 100 ₽ / month\n"
                f"Slots left: <b>{left_slots}</b>\n\n"
            )
        else:
            promo_block = (
                "🔥 <b>Стартовая акция</b>\n"
                f"Первые {LAUNCH_OFFER_LIMIT} paid-подписок — 100 ₽ / месяц\n"
                f"Осталось мест: <b>{left_slots}</b>\n\n"
            )
    else:
        promo_block = ""

    if lang == "en":
        return (
            "💎 <b>Full access plans</b>\n\n"
            f"{promo_block}"
            "Choose the most suitable plan:\n\n"
            f"💳 <b>1 month</b> — {month_price}\n"
            "For a quick start\n\n"
            f"🔥 <b>6 months</b> — {half_year_price}\n"
            "For a more confident use\n\n"
            f"🚀 <b>12 months</b> — {year_price}\n"
            "Best long-term price"
        )

    return (
        "💎 <b>Тарифы полного доступа</b>\n\n"
        f"{promo_block}"
        "Выберите подходящий вариант:\n\n"
        f"💳 <b>1 месяц</b> — {month_price}\n"
        "Для быстрого старта\n\n"
        f"🔥 <b>6 месяцев</b> — {half_year_price}\n"
        "Для уверенного использования\n\n"
        f"🚀 <b>12 месяцев</b> — {year_price}\n"
        "Самая выгодная цена на длинный срок"
    )


def get_plan_meta(
    plan_code: str,
    lang: str,
    use_launch_offer: bool,
    use_partner_offer: bool = False,
) -> tuple[str, str, Decimal]:
    if use_partner_offer and plan_code == "plan_1m":
        amount = Decimal(str(PARTNER_OFFER_PRICE_1M_RUB))
    elif use_partner_offer and plan_code == "plan_6m":
        amount = Decimal(str(PARTNER_OFFER_PRICE_6M_RUB))
    else:
        amount = get_plan_amount(plan_code, use_launch_offer)

    price = format_price(amount)

    if lang == "en":
        plan_map = {
            "plan_1m": ("💳 1 month", price, amount),
            "plan_6m": ("🔥 6 months", price, amount),
            "plan_12m": ("🚀 12 months", price, amount),
        }
        return plan_map[plan_code]

    plan_map = {
        "plan_1m": ("💳 1 месяц", price, amount),
        "plan_6m": ("🔥 6 месяцев", price, amount),
        "plan_12m": ("🚀 12 месяцев", price, amount),
    }
    return plan_map[plan_code]


def build_payment_text(
    plan_code: str,
    lang: str,
    use_launch_offer: bool,
    use_partner_offer: bool = False,
) -> str:
    title, price, _amount = get_plan_meta(plan_code, lang, use_launch_offer, use_partner_offer)

    if lang == "en":
        return (
            "💳 <b>Payment</b>\n\n"
            f"{title} — {price}\n\n"
            "Full access includes:\n"
            "⚡ High speed\n"
            "📱 Multiple devices\n"
            "🌍 Stable operation\n\n"
            "Press the green button below to continue to YooKassa."
        )

    return (
        "💳 <b>Оплата</b>\n\n"
        f"{title} — {price}\n\n"
        "Полный доступ включает:\n"
        "⚡ Высокую скорость\n"
        "📱 Несколько устройств\n"
        "🌍 Стабильную работу\n\n"
        "Нажмите зелёную кнопку ниже, чтобы перейти к оплате в YooKassa."
    )


def build_pending_payment_text(
    plan_code: str,
    lang: str,
    payment_id: str,
    use_launch_offer: bool,
    use_partner_offer: bool = False,
) -> str:
    title, price, _amount = get_plan_meta(plan_code, lang, use_launch_offer, use_partner_offer)

    if lang == "en":
        return (
            "💳 <b>Payment created</b>\n\n"
            f"{title} — {price}\n\n"
            "Status: <b>pending</b>\n\n"
            "Complete the payment on the YooKassa page.\n"
            "After payment, access will be activated automatically.\n\n"
            f"Payment ID:\n<code>{payment_id}</code>"
        )

    return (
        "💳 <b>Платёж создан</b>\n\n"
        f"{title} — {price}\n\n"
        "Статус: <b>pending</b>\n\n"
        "Завершите оплату на странице YooKassa.\n"
        "После оплаты доступ активируется автоматически.\n\n"
        f"ID платежа:\n<code>{payment_id}</code>"
    )


def build_extra_device_offer_text(lang: str) -> str:
    if lang == "en":
        return (
            "📱 <b>Add one more device</b>\n\n"
            "All devices on your current access are already in use.\n\n"
            "Add one more device and continue using the service without limits.\n\n"
            "💳 79 ₽ / month"
        )

    return (
        "📱 <b>Добавьте ещё одно устройство</b>\n\n"
        "Все устройства по текущему доступу уже используются.\n\n"
        "Добавьте ещё одно устройство и продолжайте пользоваться сервисом без ограничений.\n\n"
        "💳 79 ₽ / мес"
    )


def build_extra_device_pending_text(lang: str, payment_id: str) -> str:
    if lang == "en":
        return (
            "📱 <b>Additional device payment</b>\n\n"
            "Status: <b>pending</b>\n\n"
            "Complete the payment on the YooKassa page.\n"
            "After payment, the device limit will be updated automatically.\n\n"
            f"Payment ID:\n<code>{payment_id}</code>"
        )

    return (
        "📱 <b>Оплата дополнительного устройства</b>\n\n"
        "Статус: <b>pending</b>\n\n"
        "Завершите оплату на странице YooKassa.\n"
        "После оплаты лимит устройств обновится автоматически.\n\n"
        f"ID платежа:\n<code>{payment_id}</code>"
    )


def build_regenerate_device_confirm_text(lang: str, device_number: int) -> str:
    if lang == "en":
        return (
            f"⚠️ <b>Refresh device {device_number}?</b>\n\n"
            "The old key for this device will stop working.\n"
            "After refreshing, import the new key into the app again."
        )

    return (
        f"⚠️ <b>Обновить устройство {device_number}?</b>\n\n"
        "Старый ключ этого устройства перестанет работать.\n"
        "После обновления новый ключ нужно будет заново импортировать в приложение."
    )


def build_regenerate_all_confirm_text(lang: str) -> str:
    if lang == "en":
        return (
            "⚠️ <b>Refresh all keys?</b>\n\n"
            "All old keys will stop working.\n"
            "After refreshing, import new keys into all apps again."
        )

    return (
        "⚠️ <b>Обновить все ключи?</b>\n\n"
        "Все старые ключи перестанут работать.\n"
        "После обновления новые ключи нужно будет заново импортировать во все приложения."
    )
