from decimal import Decimal
import asyncio

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
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
from services.subscription_service import activate_extra_device_for_user, activate_paid_for_user
from services.vpn_service import VPNService, VPNServiceError
from utils.buttons import RENEW_EN, RENEW_RU, SUBSCRIPTION_EN, SUBSCRIPTION_RU

router = Router()


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

        from bot.handlers.start import render_home_screen

        await render_home_screen(callback)
        await safe_callback_answer(callback, "Done" if lang == "en" else "Готово")
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
