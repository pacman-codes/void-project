from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, func

from db.database import async_session_maker
from db.models import Referral, User
from services.audit_log_service import log_user_event
from services.vpn_service import VPNService, VPNServiceError


REF_PREFIX = "ref_"


def build_ref_code(telegram_id: int) -> str:
    return f"{REF_PREFIX}{telegram_id}"


def parse_ref_code(start_code: str | None) -> int | None:
    if not start_code:
        return None

    value = start_code.strip()

    if not value.startswith(REF_PREFIX):
        return None

    raw_id = value.removeprefix(REF_PREFIX).strip()

    if not raw_id.isdigit():
        return None

    return int(raw_id)


def get_referral_bonus_days(paid_referral_number: int) -> int:
    if paid_referral_number <= 0:
        return 0
    if paid_referral_number == 1:
        return 7
    if paid_referral_number == 2:
        return 14
    return 30


async def assign_referral_from_start_code(
    referred_telegram_id: int,
    start_code: str | None,
) -> bool:
    referrer_telegram_id = parse_ref_code(start_code)

    if referrer_telegram_id is None:
        return False

    if referrer_telegram_id == referred_telegram_id:
        return False

    async with async_session_maker() as session:
        referrer_result = await session.execute(
            select(User).where(User.telegram_id == referrer_telegram_id)
        )
        referrer = referrer_result.scalar_one_or_none()

        referred_result = await session.execute(
            select(User).where(User.telegram_id == referred_telegram_id)
        )
        referred = referred_result.scalar_one_or_none()

        if referrer is None or referred is None:
            return False

        if referred.first_paid_at is not None:
            return False

        existing_result = await session.execute(
            select(Referral).where(Referral.referred_user_id == referred.id)
        )
        existing = existing_result.scalar_one_or_none()

        if existing is not None:
            return existing.referrer_user_id == referrer.id

        referral = Referral(
            referrer_user_id=referrer.id,
            referred_user_id=referred.id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(referral)
        await session.commit()

    await log_user_event(
        event_type="referral_assigned",
        target_telegram_id=referred_telegram_id,
        actor_telegram_id=referrer_telegram_id,
        source="referral_service",
        status="ok",
        message="Referral assigned from start code",
        details={
            "referrer_telegram_id": referrer_telegram_id,
            "referred_telegram_id": referred_telegram_id,
            "start_code": start_code,
        },
    )

    return True


async def process_paid_referral(
    telegram_id: int,
    payment_id: str | None = None,
) -> dict[str, Any]:
    now = datetime.utcnow()
    referrer_telegram_id: int | None = None
    bonus_days = 0
    paid_referral_number = 0

    async with async_session_maker() as session:
        referred_result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        referred = referred_result.scalar_one_or_none()

        if referred is None:
            return {"status": "referred_not_found", "bonus_days": 0}

        referral_result = await session.execute(
            select(Referral).where(Referral.referred_user_id == referred.id)
        )
        referral = referral_result.scalar_one_or_none()

        if referral is None:
            return {"status": "no_referral", "bonus_days": 0}

        if referral.referred_paid_at is not None:
            return {"status": "already_processed", "bonus_days": referral.bonus_days}

        referrer_result = await session.execute(
            select(User).where(User.id == referral.referrer_user_id)
        )
        referrer = referrer_result.scalar_one_or_none()

        if referrer is None:
            return {"status": "referrer_not_found", "bonus_days": 0}

        paid_count_result = await session.execute(
            select(func.count(Referral.id)).where(
                Referral.referrer_user_id == referrer.id,
                Referral.referred_paid_at.is_not(None),
            )
        )
        already_paid_count = int(paid_count_result.scalar() or 0)
        paid_referral_number = already_paid_count + 1
        bonus_days = get_referral_bonus_days(paid_referral_number)

        base_date = referrer.subscription_expiry
        if base_date is None or base_date < now:
            base_date = now

        referrer.subscription_expiry = base_date + timedelta(days=bonus_days)
        referrer.is_active = True
        referrer.access_type = "paid"

        if referrer.device_limit is None or referrer.device_limit < 2:
            referrer.device_limit = 2

        if referrer.used_devices is None or referrer.used_devices < 0:
            referrer.used_devices = 0

        referral.referred_paid_at = now
        referral.bonus_days = bonus_days
        referral.payment_id = payment_id
        referral.updated_at = now

        referrer_telegram_id = referrer.telegram_id

        await session.commit()

    vpn_status = "not_checked"
    vpn_message = None

    try:
        service = VPNService()
        await service.ensure_vpn_access_record(
            telegram_id=referrer_telegram_id,
            device_number=1,
            device_name="Устройство 1",
        )
        vpn_status = "ok"
    except VPNServiceError as exc:
        vpn_status = "error"
        vpn_message = str(exc)
    except Exception as exc:
        vpn_status = "error"
        vpn_message = str(exc)

    await log_user_event(
        event_type="referral_bonus_applied",
        target_telegram_id=referrer_telegram_id,
        actor_telegram_id=telegram_id,
        source="referral_service",
        status="ok" if vpn_status == "ok" else "partial",
        message=f"Referral bonus applied: +{bonus_days} days",
        details={
            "referred_telegram_id": telegram_id,
            "referrer_telegram_id": referrer_telegram_id,
            "paid_referral_number": paid_referral_number,
            "bonus_days": bonus_days,
            "payment_id": payment_id,
            "vpn_status": vpn_status,
            "vpn_message": vpn_message,
        },
    )

    return {
        "status": "ok",
        "referrer_telegram_id": referrer_telegram_id,
        "referred_telegram_id": telegram_id,
        "paid_referral_number": paid_referral_number,
        "bonus_days": bonus_days,
        "vpn_status": vpn_status,
    }


async def get_referral_summary(telegram_id: int) -> dict[str, Any]:
    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()

        if user is None:
            return {"user_found": False, "telegram_id": telegram_id}

        rows_result = await session.execute(
            select(Referral, User)
            .join(User, User.id == Referral.referred_user_id)
            .where(Referral.referrer_user_id == user.id)
            .order_by(Referral.id.asc())
        )
        rows = rows_result.all()

        paid_count = 0
        total_bonus_days = 0
        referrals = []

        for referral, referred in rows:
            is_paid = referral.referred_paid_at is not None
            if is_paid:
                paid_count += 1
                total_bonus_days += referral.bonus_days or 0

            referrals.append(
                {
                    "referred_telegram_id": referred.telegram_id,
                    "username": referred.username,
                    "first_name": referred.first_name,
                    "is_paid": is_paid,
                    "bonus_days": referral.bonus_days or 0,
                    "created_at": referral.created_at,
                    "referred_paid_at": referral.referred_paid_at,
                }
            )

        return {
            "user_found": True,
            "telegram_id": telegram_id,
            "ref_code": build_ref_code(telegram_id),
            "total_referrals": len(referrals),
            "paid_referrals": paid_count,
            "total_bonus_days": total_bonus_days,
            "referrals": referrals,
        }
