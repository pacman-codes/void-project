from decimal import Decimal
import asyncio

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from bot.keyboards.user import (
    get_extra_device_offer_keyboard,
    get_tariff_inline_keyboard,
)
from db.database import async_session_maker
from db.models import User, VPNAccess
from services.access_service import get_access_status
from services.legal_service import accept_terms_for_user, get_terms_status
from services.payment_service import (
    LAUNCH_OFFER_LIMIT,
    PaymentServiceError,
    clear_user_payment_state,
    create_redirect_payment,
    get_launch_offer_used_count,
    get_plan_amount,
    get_user_payment_state,
    is_launch_offer_available,
    sync_payment_status,
)
from services.subscription_service import activate_extra_device_for_user, activate_paid_for_user
from services.user_service import get_user
from services.vpn_service import VPNService, VPNServiceError
from utils.buttons import RENEW_EN, RENEW_RU, SUBSCRIPTION_EN, SUBSCRIPTION_RU

router = Router()

from config.links import OFFER_URL, PRIVACY_URL, RULES_URL
DEFAULT_TRAFFIC_LIMIT_MB = 3072


async def safe_edit_text(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = "HTML",
    disable_web_page_preview: bool | None = None,
) -> bool:
    try:
        await message.edit_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
        return True
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return False
        raise


async def safe_callback_answer(
    callback: CallbackQuery,
    text: str | None = None,
    show_alert: bool = False,
) -> None:
    if text:
        text = str(text).strip()
        if len(text) > 180:
            text = text[:180].rstrip() + "..."

    try:
        await callback.answer(text=text, show_alert=show_alert)
    except TelegramBadRequest as e:
        if "query is too old" in str(e) or "query ID is invalid" in str(e):
            return
        if "MESSAGE_TOO_LONG" in str(e):
            try:
                await callback.answer(
                    text="Ошибка. Откройте «Не работает»." if show_alert else None,
                    show_alert=show_alert,
                )
                return
            except TelegramBadRequest:
                return
        raise


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
            "• from 2 devices\n"
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
        "• от 2 устройств\n"
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


def format_price(amount: Decimal) -> str:
    return f"{int(amount)} ₽"


def build_tariffs_text(lang: str, use_launch_offer: bool, used_count: int) -> str:
    month_price = format_price(get_plan_amount("plan_1m", use_launch_offer))
    half_year_price = format_price(get_plan_amount("plan_6m", use_launch_offer))
    year_price = format_price(get_plan_amount("plan_12m", use_launch_offer))

    if use_launch_offer:
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


def build_tariffs_keyboard(lang: str, source: str = "subscription") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    back_callback = "back_home" if source == "renew" else "back_to_subscription"

    if lang == "en":
        builder.button(text="💳 1 month", callback_data="plan_1m")
        builder.button(text="🔥 6 months", callback_data="plan_6m")
        builder.button(text="🚀 12 months", callback_data="plan_12m")
        builder.button(text="Back", callback_data=back_callback)
    else:
        builder.button(text="💳 1 месяц", callback_data="plan_1m")
        builder.button(text="🔥 6 месяцев", callback_data="plan_6m")
        builder.button(text="🚀 12 месяцев", callback_data="plan_12m")
        builder.button(text="Назад", callback_data=back_callback)

    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def get_plan_meta(plan_code: str, lang: str, use_launch_offer: bool) -> tuple[str, str, Decimal]:
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


def build_payment_text(plan_code: str, lang: str, use_launch_offer: bool) -> str:
    title, price, _amount = get_plan_meta(plan_code, lang, use_launch_offer)

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


def build_pending_payment_text(plan_code: str, lang: str, payment_id: str, use_launch_offer: bool) -> str:
    title, price, _amount = get_plan_meta(plan_code, lang, use_launch_offer)

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


def get_duration_days(plan_code: str) -> int:
    duration_map = {
        "plan_1m": 30,
        "plan_6m": 180,
        "plan_12m": 365,
    }
    return duration_map.get(plan_code, 30)


async def get_lang(user_id: int) -> str:
    user = await get_user(user_id)
    if user and user.language:
        return user.language
    return "ru"


async def user_has_any_access(user_id: int) -> tuple[bool, str | None]:
    access = await get_access_status(user_id)
    return access.get("has_access", False), access.get("access_type")


async def get_offer_state() -> tuple[bool, int]:
    used_count = await get_launch_offer_used_count()
    return used_count < LAUNCH_OFFER_LIMIT, used_count


async def activate_free_for_user(user_id: int) -> tuple[bool, str]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return False, "Пользователь не найден."

        user.access_type = "free"
        user.is_active = True

        if user.traffic_limit is None:
            user.traffic_limit = DEFAULT_TRAFFIC_LIMIT_MB

        if user.traffic_used is None:
            user.traffic_used = 0

        if user.device_limit is None or user.device_limit <= 0:
            user.device_limit = 1

        if user.used_devices is None or user.used_devices < 0:
            user.used_devices = 0

        await session.commit()

    try:
        service = VPNService()
        await service.ensure_vpn_access_record(
            telegram_id=user_id,
            device_number=1,
            device_name="Устройство 1",
        )
    except VPNServiceError:
        return False, "Не удалось создать ключ. Попробуйте ещё раз позже."
    except Exception:
        return False, "Не удалось создать ключ. Попробуйте ещё раз позже."

    return True, "ok"


async def send_subscription_screen(target: Message | CallbackQuery) -> None:
    lang = await get_lang(target.from_user.id)
    text = build_subscription_text(lang)
    keyboard = get_tariff_inline_keyboard(lang)

    if isinstance(target, Message):
        await target.answer(text=text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await safe_edit_text(target.message, text=text, reply_markup=keyboard, parse_mode="HTML")


async def ensure_terms_then_continue(callback: CallbackQuery, action: str) -> bool:
    terms_accepted = await get_terms_status(callback.from_user.id)

    if terms_accepted:
        return True

    lang = await get_lang(callback.from_user.id)

    await safe_edit_text(
        callback.message,
        text=build_legal_text(lang),
        reply_markup=build_legal_keyboard(lang, action),
        disable_web_page_preview=True,
        parse_mode="HTML",
    )
    await safe_callback_answer(callback)
    return False


@router.message(F.text.in_({SUBSCRIPTION_RU, SUBSCRIPTION_EN}))
async def subscription_menu(message: Message) -> None:
    has_access, access_type = await user_has_any_access(message.from_user.id)

    if has_access:
        if access_type == "free":
            lang = await get_lang(message.from_user.id)
            use_launch_offer, used_count = await get_offer_state()
            await message.answer(
                text=build_tariffs_text(lang, use_launch_offer, used_count),
                reply_markup=build_tariffs_keyboard(lang, source="renew"),
                parse_mode="HTML",
            )
            return

        from bot.handlers.start import render_home_screen
        await render_home_screen(message)
        return

    await send_subscription_screen(message)


@router.message(F.text.in_({RENEW_RU, RENEW_EN}))
async def renew_menu(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    use_launch_offer, used_count = await get_offer_state()
    await message.answer(
        text=build_tariffs_text(lang, use_launch_offer, used_count),
        reply_markup=build_tariffs_keyboard(lang, source="renew"),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "open_subscription")
async def open_subscription(callback: CallbackQuery) -> None:
    has_access, access_type = await user_has_any_access(callback.from_user.id)

    if has_access:
        if access_type == "free":
            lang = await get_lang(callback.from_user.id)
            use_launch_offer, used_count = await get_offer_state()
            await safe_edit_text(
                callback.message,
                text=build_tariffs_text(lang, use_launch_offer, used_count),
                reply_markup=build_tariffs_keyboard(lang, source="renew"),
                parse_mode="HTML",
            )
            await safe_callback_answer(callback)
            return

        from bot.handlers.start import render_home_screen
        await render_home_screen(callback)
        await safe_callback_answer(callback)
        return

    await send_subscription_screen(callback)
    await safe_callback_answer(callback)


@router.callback_query(F.data == "open_renew")
async def open_renew(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)
    use_launch_offer, used_count = await get_offer_state()
    await safe_edit_text(
        callback.message,
        text=build_tariffs_text(lang, use_launch_offer, used_count),
        reply_markup=build_tariffs_keyboard(lang, source="renew"),
        parse_mode="HTML",
    )
    await safe_callback_answer(callback)


@router.callback_query(F.data == "back_to_subscription")
async def back_to_subscription(callback: CallbackQuery) -> None:
    has_access, access_type = await user_has_any_access(callback.from_user.id)

    if has_access:
        if access_type == "free":
            lang = await get_lang(callback.from_user.id)
            use_launch_offer, used_count = await get_offer_state()
            await safe_edit_text(
                callback.message,
                text=build_tariffs_text(lang, use_launch_offer, used_count),
                reply_markup=build_tariffs_keyboard(lang, source="renew"),
                parse_mode="HTML",
            )
            await safe_callback_answer(callback)
            return

        from bot.handlers.start import render_home_screen
        await render_home_screen(callback)
        await safe_callback_answer(callback)
        return

    await send_subscription_screen(callback)
    await safe_callback_answer(callback)


@router.callback_query(F.data == "back_from_legal")
async def back_from_legal(callback: CallbackQuery) -> None:
    has_access, access_type = await user_has_any_access(callback.from_user.id)

    if has_access:
        if access_type == "free":
            lang = await get_lang(callback.from_user.id)
            use_launch_offer, used_count = await get_offer_state()
            await safe_edit_text(
                callback.message,
                text=build_tariffs_text(lang, use_launch_offer, used_count),
                reply_markup=build_tariffs_keyboard(lang, source="renew"),
                parse_mode="HTML",
            )
            await safe_callback_answer(callback)
            return

        from bot.handlers.start import render_home_screen
        await render_home_screen(callback)
        await safe_callback_answer(callback)
        return

    await send_subscription_screen(callback)
    await safe_callback_answer(callback)


@router.callback_query(F.data == "subscription_free")
async def subscription_free(callback: CallbackQuery) -> None:
    can_continue = await ensure_terms_then_continue(callback, "free")
    if not can_continue:
        return

    success, result_text = await activate_free_for_user(callback.from_user.id)
    if not success:
        await safe_callback_answer(callback, result_text, show_alert=True)
        return

    from bot.handlers.start import render_home_screen

    await render_home_screen(callback)
    lang = await get_lang(callback.from_user.id)
    await safe_callback_answer(callback, "Done" if lang == "en" else "Готово")


@router.callback_query(F.data == "subscription_paid")
async def subscription_paid(callback: CallbackQuery) -> None:
    can_continue = await ensure_terms_then_continue(callback, "paid")
    if not can_continue:
        return

    lang = await get_lang(callback.from_user.id)
    use_launch_offer, used_count = await get_offer_state()

    await safe_edit_text(
        callback.message,
        text=build_tariffs_text(lang, use_launch_offer, used_count),
        reply_markup=build_tariffs_keyboard(lang, source="subscription"),
        parse_mode="HTML",
    )
    await safe_callback_answer(callback)





def build_devices_text(
    lang: str,
    access_type: str | None,
    device_limit: int,
    used_devices: int,
    accesses: list[VPNAccess],
) -> str:
    if access_type == "paid":
        if lang == "en":
            header = "🔑 <b>Devices</b>\n\n"
            if accesses:
                items = []
                for access in accesses:
                    title = access.device_name or f"Device {access.device_number}"
                    key = access.config_url or "Key not found"
                    items.append(
                        f"<b>{title}</b>\n"
                        f"<code>{key}</code>"
                    )
                return header + "\n\n".join(items)
            return header + "No keys yet."

        header = "🔑 <b>Устройства</b>\n\n"
        if accesses:
            items = []
            for access in accesses:
                title = access.device_name or f"Устройство {access.device_number}"
                key = access.config_url or "Ключ не найден"
                items.append(
                    f"<b>{title}</b>\n"
                    f"<code>{key}</code>"
                )
            return header + "\n\n".join(items)
        return header + "Пока ключей нет."

    free_key = accesses[0].config_url if accesses else None

    if lang == "en":
        key_block = (
            f"\n🔑 <b>Your key</b>\n<code>{free_key}</code>\n\n"
            if free_key
            else "\n🔑 <b>Your key</b>\nKey not found yet.\n\n"
        )
        return (
            "🔑 <b>Devices</b>\n\n"
            "Your free access includes <b>1 device</b>.\n"
            "This is enough for a quick start.\n"
            f"{key_block}"
            "💎 Full access gives you:\n"
            "• more devices\n"
            "• maximum speed\n"
            "• unlimited usage"
        )

    key_block = (
        f"\n🔑 <b>Ваш ключ</b>\n<code>{free_key}</code>\n\n"
        if free_key
        else "\n🔑 <b>Ваш ключ</b>\nКлюч пока не найден.\n\n"
    )
    return (
        "🔑 <b>Устройства</b>\n\n"
        "В бесплатном доступе доступно <b>1 устройство</b>.\n"
        "Этого хватает для быстрого старта.\n"
        f"{key_block}"
        "💎 Полный доступ даёт:\n"
        "• больше устройств\n"
        "• максимальную скорость\n"
        "• использование без ограничений"
    )

def build_devices_keyboard(lang: str, access_type: str | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if access_type == "paid":
        if lang == "en":
            builder.button(text="🔑 Add device", callback_data="open_extra_device_offer", style="primary")
            builder.button(text="🏠 Home", callback_data="back_home")
        else:
            builder.button(text="🔑 Добавить устройство", callback_data="open_extra_device_offer", style="primary")
            builder.button(text="🏠 Главная", callback_data="back_home")
        builder.adjust(1, 1)
        return builder.as_markup()

    if lang == "en":
        builder.button(text="💎 Get full access", callback_data="open_subscription", style="success")
        builder.button(text="🏠 Home", callback_data="back_home")
    else:
        builder.button(text="💎 Получить полный доступ", callback_data="open_subscription", style="success")
        builder.button(text="🏠 Главная", callback_data="back_home")

    builder.adjust(1, 1)
    return builder.as_markup()


@router.callback_query(F.data == "open_add_device")
async def open_add_device(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)

    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = user_result.scalar_one_or_none()

    if user is None:
        await safe_callback_answer(
            callback,
            "User not found" if lang == "en" else "Пользователь не найден",
            show_alert=True,
        )
        return

    if user.access_type == "paid":
        vpn_service = VPNService()
        try:
            await vpn_service.ensure_vpn_access_record(
                telegram_id=callback.from_user.id,
                device_number=1,
                device_name="Устройство 1",
            )
            await vpn_service.ensure_vpn_access_record(
                telegram_id=callback.from_user.id,
                device_number=2,
                device_name="Устройство 2",
            )
        except VPNServiceError as e:
            await safe_callback_answer(
                callback,
                str(e),
                show_alert=True,
            )
            return
        except Exception:
            await safe_callback_answer(
                callback,
                "Не удалось получить ключи. Попробуйте ещё раз позже."
                if lang != "en"
                else "Could not load keys. Please try again later.",
                show_alert=True,
            )
            return

    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = user_result.scalar_one_or_none()

        accesses_result = await session.execute(
            select(VPNAccess)
            .where(VPNAccess.user_id == user.id, VPNAccess.is_active.is_(True))
            .order_by(VPNAccess.device_number.asc(), VPNAccess.id.asc())
        )
        accesses = list(accesses_result.scalars().all())

    text = build_devices_text(
        lang=lang,
        access_type=user.access_type,
        device_limit=user.device_limit or 1,
        used_devices=user.used_devices or 0,
        accesses=accesses,
    )

    await safe_edit_text(
        callback.message,
        text=text,
        reply_markup=build_devices_keyboard(lang, user.access_type),
        parse_mode="HTML",
    )
    await safe_callback_answer(callback)

@router.callback_query(F.data == "open_extra_device_offer")
async def open_extra_device_offer(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)
    payment_state = await get_user_payment_state(callback.from_user.id)

    if (
        payment_state.get("payment_status") == "pending"
        and payment_state.get("payment_kind") == "extra_device"
        and payment_state.get("payment_id")
        and payment_state.get("payment_confirmation_url")
    ):
        await safe_edit_text(
            callback.message,
            text=build_extra_device_pending_text(lang, payment_state["payment_id"]),
            reply_markup=build_open_payment_url_keyboard(
                lang,
                payment_state["payment_confirmation_url"],
            ),
            parse_mode="HTML",
        )
        await safe_callback_answer(callback)
        return

    await safe_edit_text(
        callback.message,
        text=build_extra_device_offer_text(lang),
        reply_markup=get_extra_device_offer_keyboard(lang),
        parse_mode="HTML",
    )
    await safe_callback_answer(callback)


@router.callback_query(F.data.startswith("legal_accept:"))
async def legal_accept(callback: CallbackQuery) -> None:
    action = callback.data.split(":", 1)[1]
    lang = await get_lang(callback.from_user.id)

    success, result_text = await accept_terms_for_user(callback.from_user.id)
    if not success:
        await safe_callback_answer(callback, result_text, show_alert=True)
        return

    if action == "free":
        free_success, free_result = await activate_free_for_user(callback.from_user.id)
        if not free_success:
            await safe_callback_answer(callback, free_result, show_alert=True)
            return

        from bot.handlers.start import render_home_screen

        await render_home_screen(callback)
        await safe_callback_answer(callback, "Done" if lang == "en" else "Готово")
        return

    use_launch_offer, used_count = await get_offer_state()
    await safe_edit_text(
        callback.message,
        text=build_tariffs_text(lang, use_launch_offer, used_count),
        reply_markup=build_tariffs_keyboard(lang, source="subscription"),
        parse_mode="HTML",
    )
    await safe_callback_answer(callback, "Done" if lang == "en" else "Готово")


@router.callback_query(F.data.in_({"plan_1m", "plan_6m", "plan_12m"}))
async def choose_plan(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)
    payment_state = await get_user_payment_state(callback.from_user.id)
    use_launch_offer = await is_launch_offer_available()

    if (
        payment_state.get("payment_status") == "pending"
        and payment_state.get("payment_kind") == "plan"
        and payment_state.get("payment_plan_code") == callback.data
        and payment_state.get("payment_id")
        and payment_state.get("payment_confirmation_url")
    ):
        await safe_edit_text(
            callback.message,
            text=build_pending_payment_text(
                callback.data,
                lang,
                payment_state["payment_id"],
                use_launch_offer,
            ),
            reply_markup=build_open_payment_url_keyboard(
                lang,
                payment_state["payment_confirmation_url"],
            ),
            parse_mode="HTML",
        )
        await safe_callback_answer(callback)
        return

    await safe_edit_text(
        callback.message,
        text=build_payment_text(callback.data, lang, use_launch_offer),
        reply_markup=build_payment_keyboard_local(lang, callback.data),
        parse_mode="HTML",
    )
    await safe_callback_answer(callback)


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


@router.callback_query(F.data.startswith("pay_plan_"))
async def create_pending_payment(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)
    plan_code = callback.data.replace("pay_", "", 1)
    use_launch_offer = await is_launch_offer_available()
    title, _price, amount = get_plan_meta(plan_code, lang, use_launch_offer)

    try:
        result = await create_redirect_payment(
            user_id=callback.from_user.id,
            amount_rub=amount,
            description=title,
            kind="plan",
            plan_code=plan_code,
            devices_to_add=0,
        )
    except PaymentServiceError as e:
        await safe_callback_answer(callback, str(e), show_alert=True)
        return

    await safe_edit_text(
        callback.message,
        text=build_pending_payment_text(plan_code, lang, result["payment_id"], use_launch_offer),
        reply_markup=build_open_payment_url_keyboard(
            lang,
            result["payment_confirmation_url"],
        ),
        parse_mode="HTML",
    )
    await safe_callback_answer(callback, "Payment created" if lang == "en" else "Платёж создан")


@router.callback_query(F.data == "extra_device_pay")
async def extra_device_pay(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)

    try:
        result = await create_redirect_payment(
            user_id=callback.from_user.id,
            amount_rub=Decimal("79.00"),
            description="Additional device" if lang == "en" else "Дополнительное устройство",
            kind="extra_device",
            plan_code=None,
            devices_to_add=1,
        )
    except PaymentServiceError as e:
        await safe_callback_answer(callback, str(e), show_alert=True)
        return

    await safe_edit_text(
        callback.message,
        text=build_extra_device_pending_text(lang, result["payment_id"]),
        reply_markup=build_open_payment_url_keyboard(
            lang,
            result["payment_confirmation_url"],
        ),
        parse_mode="HTML",
    )
    await safe_callback_answer(callback, "Payment created" if lang == "en" else "Платёж создан")


@router.callback_query(F.data.startswith("payment_check_"))
async def payment_check(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)
    payment_state = None
    plan_code = callback.data.replace("payment_check_", "", 1)

    await asyncio.sleep(2)

    for _ in range(3):
        try:
            payment_state = await sync_payment_status(callback.from_user.id)
        except PaymentServiceError as e:
            await safe_callback_answer(callback, str(e), show_alert=True)
            return

        if payment_state["payment_status"] == "succeeded":
            checked_plan_code = payment_state["payment_plan_code"] or plan_code
            duration_days = get_duration_days(checked_plan_code)

            success, result_text = await activate_paid_for_user(
                callback.from_user.id,
                duration_days,
            )
            if not success:
                await safe_callback_answer(callback, result_text, show_alert=True)
                return

            await clear_user_payment_state(callback.from_user.id)

            from bot.handlers.start import render_home_screen

            await render_home_screen(callback)
            await safe_callback_answer(callback, "Payment confirmed" if lang == "en" else "Оплата подтверждена")
            return

        if payment_state["payment_status"] == "canceled":
            await clear_user_payment_state(callback.from_user.id)
            await safe_edit_text(
                callback.message,
                text="❌ <b>Payment canceled</b>\n\nYou can try again."
                if lang == "en"
                else "❌ <b>Платёж отменён</b>\n\nВы можете попробовать снова.",
                reply_markup=build_payment_keyboard_local(lang, plan_code),
                parse_mode="HTML",
            )
            await safe_callback_answer(
                callback,
                "Payment canceled" if lang == "en" else "Платёж отменён",
                show_alert=True,
            )
            return

        await asyncio.sleep(2)

    if payment_state is None:
        await safe_callback_answer(
            callback,
            "Failed to check payment, please try again"
            if lang == "en"
            else "Не удалось проверить платёж, попробуйте ещё раз",
            show_alert=True,
        )
        return

    use_launch_offer = await is_launch_offer_available()
    await safe_edit_text(
        callback.message,
        text=build_pending_payment_text(plan_code, lang, payment_state["payment_id"], use_launch_offer),
        reply_markup=build_open_payment_url_keyboard(
            lang,
            payment_state["payment_confirmation_url"],
        ),
        parse_mode="HTML",
    )
    await safe_callback_answer(
        callback,
        "Payment is still processing, try again in a few seconds"
        if lang == "en"
        else "Платёж ещё обрабатывается, попробуйте через пару секунд",
        show_alert=True,
    )


@router.callback_query(F.data == "extra_device_check")
async def extra_device_check(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)

    try:
        payment_state = await sync_payment_status(callback.from_user.id)
    except PaymentServiceError as e:
        await safe_callback_answer(callback, str(e), show_alert=True)
        return

    if payment_state["payment_status"] == "succeeded":
        success, result_text = await activate_extra_device_for_user(
            callback.from_user.id,
            devices_to_add=int(payment_state.get("payment_devices_to_add") or 1),
        )
        if not success:
            await safe_callback_answer(callback, result_text, show_alert=True)
            return

        await clear_user_payment_state(callback.from_user.id)

        from bot.handlers.start import render_home_screen

        await render_home_screen(callback)
        await safe_callback_answer(
            callback,
            "Device added" if lang == "en" else "Устройство добавлено",
        )
        return

    if payment_state["payment_status"] == "canceled":
        await clear_user_payment_state(callback.from_user.id)
        await safe_edit_text(
            callback.message,
            text="❌ <b>Payment canceled</b>\n\nYou can try again."
            if lang == "en"
            else "❌ <b>Платёж отменён</b>\n\nВы можете попробовать снова.",
            reply_markup=get_extra_device_offer_keyboard(lang),
            parse_mode="HTML",
        )
        await safe_callback_answer(
            callback,
            "Payment canceled" if lang == "en" else "Платёж отменён",
            show_alert=True,
        )
        return

    await safe_edit_text(
        callback.message,
        text=build_extra_device_pending_text(lang, payment_state["payment_id"]),
        reply_markup=build_open_payment_url_keyboard(
            lang,
            payment_state["payment_confirmation_url"],
        ),
        parse_mode="HTML",
    )
    await safe_callback_answer(
        callback,
        "Still pending" if lang == "en" else "Пока pending",
        show_alert=True,
    )
