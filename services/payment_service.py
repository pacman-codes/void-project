import uuid
from decimal import Decimal, ROUND_HALF_UP

import httpx
from sqlalchemy import select, text

from config.config import settings
from db.database import async_session_maker
from db.models import User

YOOKASSA_API_URL = "https://api.yookassa.ru/v3/payments"

LAUNCH_OFFER_LIMIT = 10
NORMAL_PLAN_PRICES = {
    "plan_1m": Decimal("249.00"),
    "plan_6m": Decimal("1270.00"),
    "plan_12m": Decimal("1940.00"),
}
LAUNCH_PLAN_PRICES = {
    "plan_1m": Decimal("100.00"),
    "plan_6m": Decimal("600.00"),
    "plan_12m": Decimal("1200.00"),
}


class PaymentServiceError(Exception):
    """Ошибка работы с платежами."""


def _format_amount(value_rub: Decimal | int | float | str) -> str:
    amount = Decimal(str(value_rub)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return str(amount)


def _check_yookassa_config() -> None:
    if not settings.yookassa_shop_id:
        raise PaymentServiceError("YOOKASSA_SHOP_ID is empty")
    if not settings.yookassa_secret_key:
        raise PaymentServiceError("YOOKASSA_SECRET_KEY is empty")
    if not settings.yookassa_return_url:
        raise PaymentServiceError("YOOKASSA_RETURN_URL is empty")


def get_plan_amount(plan_code: str, use_launch_offer: bool) -> Decimal:
    if use_launch_offer:
        return LAUNCH_PLAN_PRICES.get(plan_code, NORMAL_PLAN_PRICES["plan_1m"])
    return NORMAL_PLAN_PRICES.get(plan_code, NORMAL_PLAN_PRICES["plan_1m"])


async def get_launch_offer_used_count() -> int:
    async with async_session_maker() as session:
        result = await session.execute(
            text("SELECT COUNT(*) FROM launch_offer_redemptions")
        )
        return int(result.scalar() or 0)


async def is_launch_offer_available() -> bool:
    used_count = await get_launch_offer_used_count()
    return used_count < LAUNCH_OFFER_LIMIT


async def register_launch_offer_redemption(
    *,
    telegram_id: int,
    payment_id: str,
    plan_code: str,
) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            text(
                """
                INSERT INTO launch_offer_redemptions (telegram_id, payment_id, plan_code)
                SELECT :telegram_id, :payment_id, :plan_code
                WHERE (
                    SELECT COUNT(*) FROM launch_offer_redemptions
                ) < :launch_offer_limit
                ON CONFLICT (payment_id) DO NOTHING
                RETURNING id
                """
            ),
            {
                "telegram_id": telegram_id,
                "payment_id": payment_id,
                "plan_code": plan_code,
                "launch_offer_limit": LAUNCH_OFFER_LIMIT,
            },
        )
        inserted = result.scalar_one_or_none() is not None
        await session.commit()
        return inserted


async def get_user_payment_state(user_id: int) -> dict:
    async with async_session_maker() as session:
        result = await session.execute(
            select(
                User.payment_status,
                User.payment_id,
                User.payment_kind,
                User.payment_plan_code,
                User.payment_devices_to_add,
                User.payment_confirmation_url,
            ).where(User.telegram_id == user_id)
        )
        row = result.one_or_none()

        if row is None:
            return {
                "payment_status": None,
                "payment_id": None,
                "payment_kind": None,
                "payment_plan_code": None,
                "payment_devices_to_add": 0,
                "payment_confirmation_url": None,
            }

        return {
            "payment_status": row[0],
            "payment_id": row[1],
            "payment_kind": row[2],
            "payment_plan_code": row[3],
            "payment_devices_to_add": row[4] or 0,
            "payment_confirmation_url": row[5],
        }


async def clear_user_payment_state(user_id: int) -> None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return

        user.payment_status = None
        user.payment_id = None
        user.payment_kind = None
        user.payment_plan_code = None
        user.payment_devices_to_add = 0
        user.payment_confirmation_url = None

        await session.commit()


async def create_redirect_payment(
    *,
    user_id: int,
    amount_rub: Decimal | int | float | str,
    description: str,
    kind: str,
    plan_code: str | None = None,
    devices_to_add: int = 0,
) -> dict:
    _check_yookassa_config()

    current_state = await get_user_payment_state(user_id)
    if (
        current_state["payment_status"] == "pending"
        and current_state["payment_id"]
        and current_state["payment_confirmation_url"]
        and current_state["payment_kind"] == kind
        and current_state["payment_plan_code"] == plan_code
        and int(current_state["payment_devices_to_add"] or 0) == int(devices_to_add or 0)
    ):
        return {
            "payment_id": current_state["payment_id"],
            "payment_status": current_state["payment_status"],
            "payment_confirmation_url": current_state["payment_confirmation_url"],
            "reused": True,
        }

    idempotence_key = str(uuid.uuid4())

    payload = {
        "amount": {
            "value": _format_amount(amount_rub),
            "currency": "RUB",
        },
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": settings.yookassa_return_url,
        },
        "description": description,
        "metadata": {
            "telegram_id": str(user_id),
            "kind": kind,
            "plan_code": plan_code or "",
            "devices_to_add": str(devices_to_add or 0),
        },
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            YOOKASSA_API_URL,
            json=payload,
            headers={
                "Idempotence-Key": idempotence_key,
                "Content-Type": "application/json",
            },
            auth=(settings.yookassa_shop_id, settings.yookassa_secret_key),
        )

    if response.status_code in {401, 403}:
        raise PaymentServiceError("Ошибка авторизации ЮKassa. Проверь shop_id и secret_key.")

    if response.status_code not in {200, 201}:
        raise PaymentServiceError(f"ЮKassa вернула ошибку: HTTP {response.status_code}")

    data = response.json()
    payment_id = data.get("id")
    status = data.get("status")
    confirmation_url = (data.get("confirmation") or {}).get("confirmation_url")

    if not payment_id:
        raise PaymentServiceError("ЮKassa не вернула payment_id")

    if not confirmation_url:
        raise PaymentServiceError("ЮKassa не вернула confirmation_url")

    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            raise PaymentServiceError("Пользователь не найден")

        user.payment_status = status
        user.payment_id = payment_id
        user.payment_kind = kind
        user.payment_plan_code = plan_code
        user.payment_devices_to_add = devices_to_add or 0
        user.payment_confirmation_url = confirmation_url

        await session.commit()

    return {
        "payment_id": payment_id,
        "payment_status": status,
        "payment_confirmation_url": confirmation_url,
        "reused": False,
    }


async def sync_payment_status(user_id: int) -> dict:
    _check_yookassa_config()

    current_state = await get_user_payment_state(user_id)
    payment_id = current_state.get("payment_id")

    if not payment_id:
        raise PaymentServiceError("Платёж не найден")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{YOOKASSA_API_URL}/{payment_id}",
            auth=(settings.yookassa_shop_id, settings.yookassa_secret_key),
        )

    if response.status_code in {401, 403}:
        raise PaymentServiceError("Ошибка авторизации ЮKassa. Проверь shop_id и secret_key.")

    if response.status_code != 200:
        raise PaymentServiceError(f"ЮKassa вернула ошибку: HTTP {response.status_code}")

    data = response.json()
    status = data.get("status")
    confirmation_url = (data.get("confirmation") or {}).get("confirmation_url")

    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            raise PaymentServiceError("Пользователь не найден")

        user.payment_status = status
        if confirmation_url:
            user.payment_confirmation_url = confirmation_url

        await session.commit()

    return {
        "payment_id": payment_id,
        "payment_status": status,
        "payment_kind": current_state.get("payment_kind"),
        "payment_plan_code": current_state.get("payment_plan_code"),
        "payment_devices_to_add": current_state.get("payment_devices_to_add", 0),
        "payment_confirmation_url": confirmation_url or current_state.get("payment_confirmation_url"),
        "raw": data,
    }
