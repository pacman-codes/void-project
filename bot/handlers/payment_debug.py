from aiogram import Router, F
from aiogram.types import CallbackQuery

from services.payment_service import mark_payment_paid

router = Router()


@router.callback_query(F.data == "fake_success")
async def fake_success(callback: CallbackQuery):
    await mark_payment_paid(callback.from_user.id)

    await callback.message.edit_text(
        "✅ Оплата прошла успешно!\n\nДоступ активирован."
    )

    await callback.answer()
