from aiogram import types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

async def show_main_menu(message: types.Message):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("Мой аккаунт"))
    keyboard.add(KeyboardButton("Подключение"))
    keyboard.add(KeyboardButton("Настройки"))

    await message.answer("Добро пожаловать в ваш личный кабинет!", reply_markup=keyboard)
