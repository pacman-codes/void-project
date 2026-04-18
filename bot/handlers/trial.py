from aiogram import F, Router
from aiogram.types import Message

from services.trial_service import activate_trial_for_user

router = Router()


@router.message(F.text.contains("Пробный"))
async def start_trial(message: Message) -> None:
    success, text = await activate_trial_for_user(message.from_user.id)

    if not success:
        await message.answer(text)
        return

    await message.answer(
        "🚀 <b>Пробный период активирован</b>\n\n"
        "Вы получили бесплатный доступ на 3 дня ✨"
    )
