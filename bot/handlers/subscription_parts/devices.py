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


async def render_devices_screen(callback: CallbackQuery) -> None:
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
        reply_markup=build_devices_keyboard(lang, user.access_type, accesses),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("regenerate_device:"))
async def open_regenerate_device_confirm(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)

    try:
        device_number = int(callback.data.split(":", 1)[1])
    except Exception:
        await safe_callback_answer(
            callback,
            "Invalid device" if lang == "en" else "Некорректное устройство",
            show_alert=True,
        )
        return

    await safe_edit_text(
        callback.message,
        text=build_regenerate_device_confirm_text(lang, device_number),
        reply_markup=build_regenerate_device_confirm_keyboard(lang, device_number),
        parse_mode="HTML",
    )
    await safe_callback_answer(callback)


@router.callback_query(F.data.startswith("confirm_regenerate_device:"))
async def confirm_regenerate_device(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)

    try:
        device_number = int(callback.data.split(":", 1)[1])
    except Exception:
        await safe_callback_answer(
            callback,
            "Invalid device" if lang == "en" else "Некорректное устройство",
            show_alert=True,
        )
        return

    try:
        await VPNService().regenerate_vpn_access_record(
            telegram_id=callback.from_user.id,
            device_number=device_number,
            device_name=f"Устройство {device_number}",
        )
    except Exception:
        await safe_callback_answer(
            callback,
            "Could not refresh key" if lang == "en" else "Не удалось обновить ключ",
            show_alert=True,
        )
        return

    await render_devices_screen(callback)
    await safe_callback_answer(callback, "Done" if lang == "en" else "Готово")


@router.callback_query(F.data == "regenerate_all_keys")
async def open_regenerate_all_confirm(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)

    await safe_edit_text(
        callback.message,
        text=build_regenerate_all_confirm_text(lang),
        reply_markup=build_regenerate_all_confirm_keyboard(lang),
        parse_mode="HTML",
    )
    await safe_callback_answer(callback)


@router.callback_query(F.data == "confirm_regenerate_all_keys")
async def confirm_regenerate_all_keys(callback: CallbackQuery) -> None:
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

        access_result = await session.execute(
            select(VPNAccess.device_number)
            .where(
                VPNAccess.user_id == user.id,
                VPNAccess.is_active.is_(True),
            )
            .order_by(VPNAccess.device_number.asc())
        )
        device_numbers = list(access_result.scalars().all())

    if not device_numbers:
        await safe_callback_answer(
            callback,
            "No keys found" if lang == "en" else "Ключи не найдены",
            show_alert=True,
        )
        return

    service = VPNService()

    try:
        for device_number in device_numbers:
            await service.regenerate_vpn_access_record(
                telegram_id=callback.from_user.id,
                device_number=int(device_number),
                device_name=f"Устройство {device_number}",
            )
    except Exception:
        await safe_callback_answer(
            callback,
            "Could not refresh all keys" if lang == "en" else "Не удалось обновить все ключи",
            show_alert=True,
        )
        return

    await render_devices_screen(callback)
    await safe_callback_answer(callback, "Done" if lang == "en" else "Готово")


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
        async with async_session_maker() as session:
            existing_result = await session.execute(
                select(VPNAccess.device_number).where(
                    VPNAccess.user_id == user.id,
                    VPNAccess.is_active.is_(True),
                )
            )
            existing_device_numbers = set(existing_result.scalars().all())

        vpn_service = VPNService()
        try:
            if 1 not in existing_device_numbers:
                await vpn_service.ensure_vpn_access_record(
                    telegram_id=callback.from_user.id,
                    device_number=1,
                    device_name="Устройство 1",
                )

            if 2 not in existing_device_numbers and (user.device_limit or 1) >= 2:
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

    await render_devices_screen(callback)
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
