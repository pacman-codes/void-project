from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.keyboards.user import get_instruction_inline_keyboard
from services.access_service import get_access_status
from services.user_service import get_user
from utils.buttons import INSTRUCTION_EN, INSTRUCTION_RU

router = Router()


def build_instruction_text(lang: str) -> str:
    if lang == "en":
        return (
            "📘 <b>Instruction</b>\n\n"
            "1. Install the application on your device.\n"
            "2. Copy your access key from the bot.\n"
            "3. Open the application.\n"
            "4. Tap <b>Add / Import</b>.\n"
            "5. Paste the key and connect."
        )

    return (
        "📘 <b>Инструкция</b>\n\n"
        "1. Установите приложение на устройство.\n"
        "2. Скопируйте ключ доступа в боте.\n"
        "3. Откройте приложение.\n"
        "4. Нажмите <b>Добавить / Импорт</b>.\n"
        "5. Вставьте ключ и подключитесь."
    )


async def get_lang(user_id: int) -> str:
    user = await get_user(user_id)
    if user and user.language:
        return user.language
    return "ru"


@router.message(F.text.in_([INSTRUCTION_RU, INSTRUCTION_EN]))
async def instruction_handler(message: Message) -> None:
    if message.from_user is None:
        return

    lang = await get_lang(message.from_user.id)
    access = await get_access_status(message.from_user.id)

    await message.answer(
        build_instruction_text(lang),
        reply_markup=get_instruction_inline_keyboard(lang, access.get("access_type")),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "open_instruction")
async def open_instruction(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)
    access = await get_access_status(callback.from_user.id)

    await callback.message.edit_text(
        build_instruction_text(lang),
        reply_markup=get_instruction_inline_keyboard(lang, access.get("access_type")),
        parse_mode="HTML",
    )
    await callback.answer()
