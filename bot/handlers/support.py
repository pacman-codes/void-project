from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.keyboards.user import get_support_inline_keyboard
from services.access_service import get_access_status
from services.user_service import get_user
from utils.buttons import SUPPORT_EN, SUPPORT_RU

router = Router()

from config.support import SUPPORT_USERNAME


def build_support_text(lang: str) -> str:
    if lang == "en":
        return (
            "💬 <b>Support</b>\n\n"
            "If something does not work or you need help,\n"
            f"write here: {SUPPORT_USERNAME}"
        )

    return (
        "💬 <b>Поддержка</b>\n\n"
        "Если что-то не работает или нужна помощь,\n"
        f"напишите сюда: {SUPPORT_USERNAME}"
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
