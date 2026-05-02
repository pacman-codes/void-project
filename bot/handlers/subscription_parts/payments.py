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


@router.callback_query(F.data.in_({"plan_1m", "plan_6m", "plan_12m"}))
async def choose_plan(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)
    payment_state = await get_user_payment_state(callback.from_user.id)
    from config.feature_flags import ENABLE_LAUNCH_OFFER

    use_launch_offer = ENABLE_LAUNCH_OFFER and await is_launch_offer_available()
    use_partner_offer = await get_partner_offer_state(callback.from_user.id)

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
                use_partner_offer,
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
        text=build_payment_text(callback.data, lang, use_launch_offer, use_partner_offer),
        reply_markup=build_payment_keyboard_local(lang, callback.data),
        parse_mode="HTML",
    )
    await safe_callback_answer(callback)


@router.callback_query(F.data.startswith("pay_plan_"))
async def create_pending_payment(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)
    plan_code = callback.data.replace("pay_", "", 1)
    use_launch_offer = await is_launch_offer_available()
    use_partner_offer = await get_partner_offer_state(callback.from_user.id)
    title, _price, amount = get_plan_meta(plan_code, lang, use_launch_offer, use_partner_offer)

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
        text=build_pending_payment_text(
            plan_code,
            lang,
            result["payment_id"],
            use_launch_offer,
            use_partner_offer,
        ),
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
    use_partner_offer = await get_partner_offer_state(callback.from_user.id)
    await safe_edit_text(
        callback.message,
        text=build_pending_payment_text(
            plan_code,
            lang,
            payment_state["payment_id"],
            use_launch_offer,
            use_partner_offer,
        ),
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
