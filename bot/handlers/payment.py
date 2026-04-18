from aiogram import Router, F
from aiogram.types import CallbackQuery

from services.payment_service import create_payment
from services.user_service import get_user
from bot.keyboards.user import get_payment_keyboard

router = Router()


@router.callback_query(F.data == "start_payment")
async def start_payment(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = user.language if user else "ru"

    success, payment_id = await create_payment(callback.from_user.id)

    if not success:
        await callback.answer("Ошибка", show_alert=True)
        return

    text = (
        "💳 <b>Оплата</b>\n\n"
        "Нажмите кнопку ниже для оплаты.\n\n"
        f"ID платежа: {payment_id}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_payment_keyboard(lang),
        parse_mode="HTML"
    )

    await callback.answer()
