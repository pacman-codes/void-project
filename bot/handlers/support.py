from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.keyboards.user import get_support_inline_keyboard
from config.support import SUPPORT_USERNAME
from services.access_service import get_access_status
from services.user_service import get_user
from services.vpn_service import VPNService
from utils.buttons import SUPPORT_EN, SUPPORT_RU

router = Router()


def build_support_text(lang: str) -> str:
    if lang == "en":
        return (
            "💬 <b>Not working?</b>\n\n"
            "Try refreshing your key first. If it still does not work,\n"
            f"write here: {SUPPORT_USERNAME}"
        )

    return (
        "💬 <b>Не работает?</b>\n\n"
        "Сначала попробуйте обновить ключ. Если проблема останется,\n"
        f"напишите сюда: {SUPPORT_USERNAME}"
    )


def build_regenerated_key_text(lang: str, config_url: str) -> str:
    if lang == "en":
        return (
            "✅ <b>Key refreshed</b>\n\n"
            "Old key in the bot was replaced with a new one.\n"
            "Import this key into your app:\n\n"
            f"<code>{config_url}</code>"
        )

    return (
        "✅ <b>Ключ обновлен</b>\n\n"
        "Старый ключ в боте заменен на новый.\n"
        "Импортируйте этот ключ в приложение:\n\n"
        f"<code>{config_url}</code>"
    )


def build_regenerate_error_text(lang: str) -> str:
    if lang == "en":
        return (
            "⚠️ <b>Could not refresh the key</b>\n\n"
            "Try again later or contact support."
        )

    return (
        "⚠️ <b>Не удалось обновить ключ</b>\n\n"
        "Попробуйте позже или напишите в поддержку."
    )


async def get_lang(user_id: int) -> str:
    user = await get_user(user_id)
    if user and user.language:
        return user.language
    return "ru"


@router.message(F.text.in_({SUPPORT_RU, SUPPORT_EN}))
async def support_handler(message: Message) -> None:
    if message.from_user is None:
        return

    lang = await get_lang(message.from_user.id)
    access = await get_access_status(message.from_user.id)

    await message.answer(
        build_support_text(lang),
        reply_markup=get_support_inline_keyboard(lang, access.get("access_type")),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "open_support")
async def open_support(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)
    access = await get_access_status(callback.from_user.id)

    await callback.message.edit_text(
        build_support_text(lang),
        reply_markup=get_support_inline_keyboard(lang, access.get("access_type")),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "regenerate_key")
async def regenerate_key(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)
    access = await get_access_status(callback.from_user.id)

    access_type = access.get("access_type")
    if access_type not in {"free", "paid"}:
        await callback.answer(
            "Access is not active" if lang == "en" else "Доступ не активен",
            show_alert=True,
        )
        return

    try:
        result = await VPNService().regenerate_vpn_access_record(
            telegram_id=callback.from_user.id,
            device_number=1,
            device_name="Устройство 1",
        )
    except Exception:
        await callback.message.edit_text(
            build_regenerate_error_text(lang),
            reply_markup=get_support_inline_keyboard(lang, access_type),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        build_regenerated_key_text(lang, result["config_url"]),
        reply_markup=get_support_inline_keyboard(lang, access_type),
        parse_mode="HTML",
    )
    await callback.answer("Готово" if lang != "en" else "Done")
