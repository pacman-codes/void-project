import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import select

from bot.handlers.start import build_home_text_and_keyboard
from config.config import settings
from db.database import async_session_maker
from db.models import User
from services.payment_service import clear_user_payment_state, register_launch_offer_redemption
from services.subscription_service import activate_extra_device_for_user, activate_paid_for_user

logger = logging.getLogger(__name__)


def get_duration_days(plan_code: str) -> int:
    duration_map = {
        "plan_1m": 30,
        "plan_6m": 180,
        "plan_12m": 365,
    }
    return duration_map.get(plan_code, 30)


async def send_home_screen_to_user(telegram_id: int) -> None:
    text, keyboard, _lang = await build_home_text_and_keyboard(telegram_id)

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=text,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
        logger.info("Sent home screen to user %s after webhook", telegram_id)
    finally:
        await bot.session.close()


async def process_yookassa_notification(payload: dict) -> tuple[int, str]:
    event = payload.get("event")
    obj = payload.get("object") or {}

    payment_id = obj.get("id")
    status = obj.get("status")

    if not payment_id:
        return 400, "payment_id is missing"

    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.payment_id == payment_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return 200, "ignored"

        telegram_id = user.telegram_id
        payment_status = user.payment_status
        payment_kind = user.payment_kind
        payment_plan_code = user.payment_plan_code
        payment_devices_to_add = user.payment_devices_to_add or 0

    if payment_status != "pending":
        return 200, "already processed"

    if event == "payment.succeeded" or status == "succeeded":
        if payment_kind == "plan":
            success, message = await activate_paid_for_user(
                telegram_id,
                get_duration_days(payment_plan_code or "plan_1m"),
            )
            if not success:
                return 500, message

            if payment_plan_code in {"plan_1m", "plan_6m", "plan_12m"}:
                await register_launch_offer_redemption(
                    telegram_id=telegram_id,
                    payment_id=payment_id,
                    plan_code=payment_plan_code,
                )

            await clear_user_payment_state(telegram_id)

            try:
                await send_home_screen_to_user(telegram_id)
            except Exception as e:
                logger.exception("Failed to send paid home screen to user %s: %s", telegram_id, e)
                return 200, "plan activated but push failed"

            return 200, "plan activated"

        if payment_kind == "extra_device":
            success, message = await activate_extra_device_for_user(
                telegram_id,
                devices_to_add=payment_devices_to_add if payment_devices_to_add > 0 else 1,
            )
            if not success:
                return 500, message

            await clear_user_payment_state(telegram_id)

            try:
                await send_home_screen_to_user(telegram_id)
            except Exception as e:
                logger.exception("Failed to send updated home screen to user %s: %s", telegram_id, e)
                return 200, "extra device activated but push failed"

            return 200, "extra device activated"

        return 200, "ignored"

    if event == "payment.canceled" or status == "canceled":
        await clear_user_payment_state(telegram_id)
        return 200, "payment canceled"

    return 200, "event ignored"
