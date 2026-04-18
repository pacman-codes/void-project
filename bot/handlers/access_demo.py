from html import escape
import traceback

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from bot.keyboards.user import (
    get_access_inline_keyboard,
    get_device_limit_reached_keyboard,
)
from db.database import async_session_maker
from db.models import User, VPNAccess
from services.access_service import get_access_status
from services.user_service import get_or_create_user, get_user
from services.vpn_service import VPNService, VPNServiceError

router = Router()


def build_access_message(lang: str, config_url: str, device_number: int) -> str:
    if lang == "en":
        return (
            f"⚡️ <b>Connection for device {device_number}</b>\n\n"
            "❗️ First install the app on your device.\n\n"
            "📘 Open <b>Instruction</b> and install the app.\n\n"
            "After installation:\n\n"
            "1. Tap the key below\n"
            "2. The key will be copied\n"
            "3. Open the app\n"
            "4. Press <b>Add / Import</b>\n"
            "5. Paste the key\n\n"
            "✅ Done\n\n"
            f"<code>{escape(config_url)}</code>"
        )

    return (
        f"⚡️ <b>Подключение для устройства {device_number}</b>\n\n"
        "❗️ Сначала установите приложение на устройство.\n\n"
        "📘 Откройте раздел <b>Инструкция</b> и установите приложение.\n\n"
        "После установки:\n\n"
        "1. Нажмите на ключ ниже\n"
        "2. Ключ скопируется\n"
        "3. Откройте приложение\n"
        "4. Нажмите <b>Добавить / Импорт</b>\n"
        "5. Вставьте ключ\n\n"
        "✅ Готово\n\n"
        f"<code>{escape(config_url)}</code>"
    )


def build_device_limit_text(lang: str, access_type: str | None) -> str:
    if access_type == "paid":
        if lang == "en":
            return (
                "📱 <b>Device limit reached</b>\n\n"
                "All device slots on your current plan are already used.\n\n"
                "You can add one more device on a separate add-on plan."
            )

        return (
            "📱 <b>Лимит устройств исчерпан</b>\n\n"
            "Все слоты устройств по текущему тарифу уже заняты.\n\n"
            "Можно докупить ещё одно устройство отдельной опцией."
        )

    if lang == "en":
        return (
            "📱 <b>Only 1 device is available on the free plan</b>\n\n"
            "To connect more devices, switch to full access."
        )

    return (
        "📱 <b>На бесплатном тарифе доступно только 1 устройство</b>\n\n"
        "Чтобы подключить больше устройств, перейдите на полный доступ."
    )


async def prepare_primary_access(telegram_id: int, username: str | None) -> tuple[str, str, int]:
    await get_or_create_user(telegram_id, username)
    user = await get_user(telegram_id)
    lang = user.language or "ru"

    service = VPNService()
    result = await service.ensure_vpn_access_record(
        telegram_id=telegram_id,
        device_number=1,
        device_name="Устройство 1",
    )
    return lang, result["config_url"], result["device_number"]


@router.callback_query(F.data == "open_access")
async def open_access(callback: CallbackQuery) -> None:
    telegram_id = callback.from_user.id
    username = callback.from_user.username
    access = await get_access_status(telegram_id)

    if not access.get("has_access"):
        user = await get_user(telegram_id)
        lang = user.language if user and user.language else "ru"
        await callback.answer(
            "Сначала выберите тариф."
            if lang == "ru"
            else "Choose a plan first.",
            show_alert=True,
        )
        return

    try:
        lang, config_url, device_number = await prepare_primary_access(telegram_id, username)
    except VPNServiceError as e:
        print(f"[open_access][VPNServiceError] telegram_id={telegram_id}: {e}")
        user = await get_user(telegram_id)
        lang = user.language if user and user.language else "ru"
        await callback.answer(
            f"Не удалось подготовить подключение: {e}"
            if lang == "ru"
            else f"Failed to prepare connection: {e}",
            show_alert=True,
        )
        return
    except Exception as e:
        print(f"[open_access][Exception] telegram_id={telegram_id}: {e}")
        traceback.print_exc()
        user = await get_user(telegram_id)
        lang = user.language if user and user.language else "ru"
        await callback.answer(
            f"Ошибка при подготовке подключения: {e}"
            if lang == "ru"
            else f"Error while preparing connection: {e}",
            show_alert=True,
        )
        return

    await callback.message.edit_text(
        build_access_message(lang, config_url, device_number),
        reply_markup=get_access_inline_keyboard(lang, access.get("access_type")),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "open_add_device")
async def open_add_device(callback: CallbackQuery) -> None:
    telegram_id = callback.from_user.id
    username = callback.from_user.username
    user = await get_or_create_user(telegram_id, username)
    lang = user.language or "ru"

    access = await get_access_status(telegram_id)
    if access.get("access_type") != "paid":
        await callback.message.edit_text(
            build_device_limit_text(lang, access.get("access_type")),
            reply_markup=get_device_limit_reached_keyboard(lang, access.get("access_type")),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    try:
        service = VPNService()
        result = await service.create_next_device_access(
            telegram_id=telegram_id,
            device_name=None,
        )
    except VPNServiceError as e:
        print(f"[open_add_device][VPNServiceError] telegram_id={telegram_id}: {e}")
        error_text = str(e)
        if "Лимит устройств исчерпан" in error_text:
            await callback.message.edit_text(
                build_device_limit_text(lang, access.get("access_type")),
                reply_markup=get_device_limit_reached_keyboard(lang, access.get("access_type")),
                parse_mode="HTML",
            )
            await callback.answer()
            return

        await callback.answer(error_text, show_alert=True)
        return
    except Exception as e:
        print(f"[open_add_device][Exception] telegram_id={telegram_id}: {e}")
        traceback.print_exc()
        await callback.answer(
            f"Не удалось добавить устройство: {e}"
            if lang == "ru"
            else f"Failed to add device: {e}",
            show_alert=True,
        )
        return

    await callback.message.edit_text(
        build_access_message(lang, result["config_url"], result["device_number"]),
        reply_markup=get_access_inline_keyboard(lang, access.get("access_type")),
        parse_mode="HTML",
    )
    await callback.answer(
        f"Устройство {result['device_number']} добавлено"
        if lang == "ru"
        else f"Device {result['device_number']} added"
    )


@router.message(Command("vpnrecord"))
async def vpn_record_command(message: Message) -> None:
    if message.from_user is None:
        return

    telegram_id = message.from_user.id

    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()

        if user is None:
            await message.answer("Пользователь не найден в базе.")
            return

        access_result = await session.execute(
            select(VPNAccess)
            .where(VPNAccess.user_id == user.id)
            .order_by(VPNAccess.device_number.asc())
        )
        accesses = list(access_result.scalars().all())

    if not accesses:
        await message.answer("Записи подключений пока не созданы.")
        return

    blocks = []
    for access in accesses:
        blocks.append(
            "<b>Техническая запись подключения</b>\n\n"
            f"device_number: <code>{access.device_number}</code>\n"
            f"user_id: <code>{access.user_id}</code>\n"
            f"server_name: <code>{escape(str(access.server_name))}</code>\n"
            f"external_id: <code>{escape(str(access.external_id))}</code>\n"
            f"client_uuid: <code>{escape(str(access.client_uuid))}</code>\n"
            f"is_active: <code>{escape(str(access.is_active))}</code>\n\n"
            "config_url:\n"
            f"<code>{escape(str(access.config_url))}</code>"
        )

    await message.answer("\n\n---\n\n".join(blocks), parse_mode="HTML")
