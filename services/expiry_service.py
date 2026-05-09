from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

from config.runtime import DEV_MODE
from db.database import async_session_maker
from db.models import User, VPNAccess
from services.audit_log_service import log_user_event
from services.vpn_service import VPNService

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.utcnow()


def _mask(value: object | None, keep_start: int = 6, keep_end: int = 4) -> str:
    if value is None:
        return "-"

    raw = str(value)
    if not raw:
        return "-"

    if len(raw) <= keep_start + keep_end + 3:
        return raw

    return f"{raw[:keep_start]}...{raw[-keep_end:]}"


async def collect_expired_paid_users(limit: int = 50) -> list[User]:
    safe_limit = max(1, min(limit, 200))

    async with async_session_maker() as session:
        result = await session.execute(
            select(User)
            .where(
                User.access_type == "paid",
                User.subscription_expiry.is_not(None),
                User.subscription_expiry <= _now(),
            )
            .order_by(User.subscription_expiry.asc(), User.id.asc())
            .limit(safe_limit)
        )
        return list(result.scalars().all())


async def expire_one_paid_user(telegram_id: int, dry_run: bool = False) -> dict[str, Any]:
    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()

        if user is None:
            return {
                "telegram_id": telegram_id,
                "status": "not_found",
                "message": "User not found",
            }

        if user.access_type != "paid":
            return {
                "telegram_id": telegram_id,
                "user_id": user.id,
                "status": "skipped",
                "message": "User is not paid",
                "access_type": user.access_type,
            }

        if not user.subscription_expiry or user.subscription_expiry > _now():
            return {
                "telegram_id": telegram_id,
                "user_id": user.id,
                "status": "skipped",
                "message": "Paid subscription is not expired",
                "subscription_expiry": user.subscription_expiry.isoformat() if user.subscription_expiry else None,
            }

        access_result = await session.execute(
            select(VPNAccess)
            .where(VPNAccess.user_id == user.id)
            .order_by(VPNAccess.device_number.asc(), VPNAccess.id.asc())
        )
        accesses = list(access_result.scalars().all())

        primary_accesses = [access for access in accesses if access.device_number == 1]
        extra_accesses = [access for access in accesses if access.device_number != 1 and access.is_active]

        summary = {
            "telegram_id": telegram_id,
            "user_id": user.id,
            "status": "dry_run" if dry_run else "ok",
            "old_access_type": user.access_type,
            "old_subscription_expiry": user.subscription_expiry.isoformat() if user.subscription_expiry else None,
            "primary_count": len(primary_accesses),
            "extra_active_count": len(extra_accesses),
            "extra_access_ids": [access.id for access in extra_accesses],
            "extra_client_uuids": [_mask(access.client_uuid) for access in extra_accesses],
            "dev_mode": DEV_MODE,
        }

        if dry_run:
            return summary

    service = VPNService()
    deleted: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    for access in extra_accesses:
        label = (
            f"access_id={access.id}, "
            f"device={access.device_number}, "
            f"client_uuid={_mask(access.client_uuid)}"
        )

        if not access.client_uuid:
            skipped.append(label + " — no client_uuid")
            continue

        if DEV_MODE:
            skipped.append(label + " — DEV_MODE, panel delete skipped")
            continue

        try:
            await service._get_panel_client().delete_client(
                inbound_id=service.inbound_id,
                client_id=access.client_uuid,
            )
            deleted.append(label)
        except Exception as exc:
            errors.append(label + f" — {type(exc).__name__}: {exc}")

    if errors:
        await log_user_event(
            event_type="subscription_expiry_failed",
            target_telegram_id=telegram_id,
            source="expiry_service",
            status="error",
            message="Failed to delete extra paid clients from panel",
            details={
                **summary,
                "deleted": deleted,
                "skipped": skipped,
                "errors": errors,
            },
        )
        return {
            **summary,
            "status": "error",
            "message": "Panel delete errors; DB state was not changed",
            "deleted": deleted,
            "skipped": skipped,
            "errors": errors,
        }

    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        db_user = user_result.scalar_one_or_none()

        if db_user is None:
            return {
                **summary,
                "status": "not_found",
                "message": "User disappeared before DB update",
            }

        access_result = await session.execute(
            select(VPNAccess)
            .where(VPNAccess.user_id == db_user.id)
            .order_by(VPNAccess.device_number.asc(), VPNAccess.id.asc())
        )
        db_accesses = list(access_result.scalars().all())

        has_primary = False
        disabled_access_ids: list[int] = []

        for access in db_accesses:
            if access.device_number == 1:
                access.is_active = True
                has_primary = True
            else:
                if access.is_active:
                    disabled_access_ids.append(access.id)
                access.is_active = False

        db_user.access_type = "free"
        db_user.is_active = True
        db_user.subscription_expiry = None
        db_user.device_limit = 1
        db_user.used_devices = 1 if has_primary else 0
        db_user.payment_status = None
        db_user.payment_id = None
        db_user.payment_kind = None
        db_user.payment_plan_code = None
        db_user.payment_devices_to_add = 0
        db_user.payment_confirmation_url = None

        await session.commit()

    await log_user_event(
        event_type="subscription_expired",
        target_telegram_id=telegram_id,
        source="expiry_service",
        status="ok",
        message="Paid subscription expired and user downgraded to free",
        details={
            **summary,
            "deleted": deleted,
            "skipped": skipped,
            "disabled_access_ids": disabled_access_ids,
            "new_access_type": "free",
            "new_device_limit": 1,
            "primary_kept_active": has_primary,
        },
    )

    return {
        **summary,
        "status": "ok",
        "message": "Expired paid user downgraded to free",
        "deleted": deleted,
        "skipped": skipped,
        "disabled_access_ids": disabled_access_ids,
        "new_access_type": "free",
        "new_device_limit": 1,
        "primary_kept_active": has_primary,
    }


async def expire_paid_users_once(limit: int = 50, dry_run: bool = False) -> dict[str, Any]:
    users = await collect_expired_paid_users(limit=limit)

    results: list[dict[str, Any]] = []
    for user in users:
        results.append(await expire_one_paid_user(user.telegram_id, dry_run=dry_run))

    return {
        "checked_at": _now().isoformat(),
        "dry_run": dry_run,
        "found": len(users),
        "processed": len(results),
        "results": results,
    }
