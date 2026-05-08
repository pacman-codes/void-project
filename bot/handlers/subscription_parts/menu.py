from decimal import Decimal
import asyncio
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from bot.keyboards.user import (
    get_extra_device_offer_keyboard,
    get_tariff_inline_keyboard,
)
from bot.handlers.subscription_parts.common import (
    get_lang,
    safe_callback_answer,
    safe_edit_text,
)
from bot.handlers.subscription_parts.access import (
    activate_free_for_user,
    get_duration_days,
    get_offer_state,
    get_partner_offer_state,
    user_has_any_access,
)
from bot.handlers.subscription_parts.texts import (
    build_extra_device_offer_text,
    build_extra_device_pending_text,
    build_legal_text,
    build_payment_text,
    build_pending_payment_text,
    build_regenerate_all_confirm_text,
    build_regenerate_device_confirm_text,
    build_subscription_text,
    build_tariffs_text,
    get_plan_meta,
)
from bot.handlers.subscription_parts.keyboards import (
    build_legal_keyboard,
    build_open_payment_url_keyboard,
    build_payment_keyboard_local,
    build_regenerate_all_confirm_keyboard,
    build_regenerate_device_confirm_keyboard,
    build_tariffs_keyboard,
    build_devices_keyboard,
)
from db.database import async_session_maker
from db.models import User, VPNAccess
from services.legal_service import accept_terms_for_user, get_terms_status
from services.payment_service import (
    PaymentServiceError,
    clear_user_payment_state,
    create_redirect_payment,
    get_user_payment_state,
    is_launch_offer_available,
    sync_payment_status,
)
from services.access_service import get_access_status
from services.subscription_service import activate_extra_device_for_user, activate_paid_for_user
from services.subscription_link_service import (
    SubscriptionLinkError,
    build_public_happ_import_url,
    build_public_subscription_url,
    get_or_create_subscription_link,
)
from services.vpn_service import VPNService, VPNServiceError
from utils.buttons import RENEW_EN, RENEW_RU, SUBSCRIPTION_EN, SUBSCRIPTION_RU

router = Router()


def format_subscription_expiry(value, lang: str) -> str:
    if value is None:
        return "not set" if lang == "en" else "не указана"

    if isinstance(value, datetime):
        dt = value + timedelta(hours=3)
        if lang == "en":
            return dt.strftime("%d %b %Y, %H:%M (MSK)")
        return dt.strftime("%d.%m.%Y %H:%M (МСК)")

    return str(value)


async def get_subscription_screen_state(
    telegram_id: int,
) -> tuple[str | None, object | None]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User.access_type, User.subscription_expiry)
            .where(User.telegram_id == telegram_id)
        )
        row = result.first()

    if not row:
        return None, None

    return row[0], row[1]


def build_subscription_link_text(
    lang: str,
    access_type: str | None,
    subscription_url: str,
    expiry=None,
) -> str:
    is_free = access_type == "free"

    if lang == "en":
        tariff_text = "Free access" if is_free else "Full access"
        expiry_block = ""
        if not is_free and expiry is not None:
            expiry_block = f"\nActive until: <b>{format_subscription_expiry(expiry, lang)}</b>\n"

        return (
            f"🚀 <b>You selected: {tariff_text}</b>{expiry_block}\n"
            "\n"
            "1. Download the <b>Happ</b> app.\n"
            "2. Tap the button <b>“Add configuration to Happ”</b> below.\n"
            "3. In Happ, tap the big connect button ✅\n"
            "\n"
            "If the button does not work, use this subscription link:\n"
            f"<code>{subscription_url}</code>"
        )

    tariff_text = "Бесплатный доступ" if is_free else "Полный доступ"
    expiry_block = ""
    if not is_free and expiry is not None:
        expiry_block = f"\nДействует до: <b>{format_subscription_expiry(expiry, lang)}</b>\n"

    return (
        f"🚀 <b>Вы выбрали тариф: {tariff_text}</b>{expiry_block}\n"
        "\n"
        "1. Скачайте приложение <b>Happ</b>.\n"
        "2. Нажмите кнопку <b>«Добавить конфигурацию в Happ»</b> ниже.\n"
        "3. В приложении Happ нажмите большую кнопку подключения ✅\n"
        "\n"
        "Если кнопка не сработает, используйте эту подписочную ссылку:\n"
        f"<code>{subscription_url}</code>"
    )


def build_subscription_link_keyboard(lang: str, happ_url: str) -> InlineKeyboardMarkup:
    happ_text = (
        "🔗 Add configuration to Happ"
        if lang == "en"
        else "🔗 Добавить конфигурацию в Happ"
    )
    home_text = "🏠 Home" if lang == "en" else "🏠 На главную"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=happ_text, url=happ_url)],
            [InlineKeyboardButton(text=home_text, callback_data="back_home")],
        ]
    )


async def ensure_access_before_subscription_link(telegram_id: int) -> tuple[bool, str]:
    access = await get_access_status(telegram_id)
    access_type = access.get("access_type")

    if not access.get("has_access"):
        return False, "Доступ не активен"

    try:
        service = VPNService()

        if access_type == "free":
            await service.ensure_vpn_access_record(
                telegram_id=telegram_id,
                device_number=1,
                device_name="Устройство 1",
            )
            return True, "OK"

        if access_type == "paid":
            await service.ensure_vpn_access_record(
                telegram_id=telegram_id,
                device_number=1,
                device_name="Устройство 1",
            )
            await service.ensure_vpn_access_record(
                telegram_id=telegram_id,
                device_number=2,
                device_name="Устройство 2",
            )
            return True, "OK"

        return False, "Доступ не активен"

    except VPNServiceError as exc:
        return False, str(exc)
    except Exception:
        return False, "Не удалось подготовить подписочную ссылку"

async def send_subscription_link_screen(target: Message | CallbackQuery) -> None:
    lang = await get_lang(target.from_user.id)

    ok, message = await ensure_access_before_subscription_link(target.from_user.id)
    if not ok:
        if isinstance(target, Message):
            await target.answer(message)
        else:
            await safe_callback_answer(target, message, show_alert=True)
        return

    try:
        link = await get_or_create_subscription_link(target.from_user.id)
    except SubscriptionLinkError as exc:
        if isinstance(target, Message):
            await target.answer(str(exc))
        else:
            await safe_callback_answer(target, str(exc), show_alert=True)
        return

    subscription_url = build_public_subscription_url(link.token)
    happ_url = build_public_happ_import_url(link.token)
    access_type, expiry = await get_subscription_screen_state(target.from_user.id)

    text = build_subscription_link_text(
        lang=lang,
        access_type=access_type,
        subscription_url=subscription_url,
        expiry=expiry,
    )
    keyboard = build_subscription_link_keyboard(lang, happ_url)

    if isinstance(target, Message):
        await target.answer(text=text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await safe_edit_text(
            target.message,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        await safe_callback_answer(target)


async def send_subscription_screen(target: Message | CallbackQuery) -> None:
    lang = await get_lang(target.from_user.id)
    text = build_subscription_text(lang)
    keyboard = get_tariff_inline_keyboard(lang)

    if isinstance(target, Message):
        await target.answer(text=text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await safe_edit_text(target.message, text=text, reply_markup=keyboard, parse_mode="HTML")


@router.message(Command("sub"))
async def subscription_link_command(message: Message) -> None:
    await send_subscription_link_screen(message)


@router.callback_query(F.data == "open_subscription_link")
async def open_subscription_link(callback: CallbackQuery) -> None:
    await send_subscription_link_screen(callback)


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
            use_partner_offer = await get_partner_offer_state(message.from_user.id)
            await message.answer(
                text=build_tariffs_text(lang, use_launch_offer, used_count, use_partner_offer),
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
    use_partner_offer = await get_partner_offer_state(message.from_user.id)
    await message.answer(
        text=build_tariffs_text(lang, use_launch_offer, used_count, use_partner_offer),
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
            use_partner_offer = await get_partner_offer_state(callback.from_user.id)
            await safe_edit_text(
                callback.message,
                text=build_tariffs_text(lang, use_launch_offer, used_count, use_partner_offer),
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
    use_partner_offer = await get_partner_offer_state(callback.from_user.id)
    await safe_edit_text(
        callback.message,
        text=build_tariffs_text(lang, use_launch_offer, used_count, use_partner_offer),
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
            use_partner_offer = await get_partner_offer_state(callback.from_user.id)
            await safe_edit_text(
                callback.message,
                text=build_tariffs_text(lang, use_launch_offer, used_count, use_partner_offer),
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
            use_partner_offer = await get_partner_offer_state(callback.from_user.id)
            await safe_edit_text(
                callback.message,
                text=build_tariffs_text(lang, use_launch_offer, used_count, use_partner_offer),
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

    await send_subscription_link_screen(callback)


@router.callback_query(F.data == "subscription_paid")
async def subscription_paid(callback: CallbackQuery) -> None:
    can_continue = await ensure_terms_then_continue(callback, "paid")
    if not can_continue:
        return

    lang = await get_lang(callback.from_user.id)
    use_launch_offer, used_count = await get_offer_state()
    use_partner_offer = await get_partner_offer_state(callback.from_user.id)

    await safe_edit_text(
        callback.message,
        text=build_tariffs_text(lang, use_launch_offer, used_count, use_partner_offer),
        reply_markup=build_tariffs_keyboard(lang, source="subscription"),
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

        await send_subscription_link_screen(callback)
        return

    use_launch_offer, used_count = await get_offer_state()
    use_partner_offer = await get_partner_offer_state(callback.from_user.id)
    await safe_edit_text(
        callback.message,
        text=build_tariffs_text(lang, use_launch_offer, used_count, use_partner_offer),
        reply_markup=build_tariffs_keyboard(lang, source="subscription"),
        parse_mode="HTML",
    )
    await safe_callback_answer(callback, "Done" if lang == "en" else "Готово")
