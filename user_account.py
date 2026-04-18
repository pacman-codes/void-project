from aiogram import types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from bot.db import db_session
from bot.models.user import User

async def show_user_account(message: types.Message):
    user_id = message.from_user.id
    user = await db_session.query(User).filter(User.telegram_id == user_id).first()
    
    if not user or not user.is_active:
        await message.answer("Пожалуйста, активируйте пробный период.")
        return

    traffic_used = format_traffic(user.traffic_used)  # Используем вспомогательную функцию для форматирования трафика
    trial_status = "Пробный период использован." if user.trial_used else "Пробный период ещё не использован. Нажмите, чтобы начать."

    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("Подключение"))
    keyboard.add(KeyboardButton("Настройки"))
    
    await message.answer(
        f"🧑‍💻 Ваш аккаунт:\n"
        f"Ссылка на подключение: {user.connection_link}\n"
        f"Трафик: {traffic_used}\n"
        f"{trial_status}",
        reply_markup=keyboard
    )

def format_traffic(traffic):
    """Функция для форматирования трафика, например 13.4 GB"""
    return f"{traffic:.1f} GB"  # Пример форматирования
