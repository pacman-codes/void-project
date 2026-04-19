#!/usr/bin/env python3
import os
import sys
import asyncio
from datetime import datetime, timedelta, UTC
from uuid import uuid4

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db.models import User, VPNAccess  # noqa: E402


def usage() -> None:
    print("Usage:")
    print("  python scripts/dev_user.py show <telegram_id>")
    print("  python scripts/dev_user.py free <telegram_id>")
    print("  python scripts/dev_user.py paid <telegram_id> [days]")
    print("  python scripts/dev_user.py reset <telegram_id>")
    print("  python scripts/dev_user.py key-show <telegram_id>")
    print("  python scripts/dev_user.py key-create <telegram_id> [device_number]")
    print("  python scripts/dev_user.py key-clear <telegram_id>")


def get_sessionmaker() -> async_sessionmaker:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    engine = create_async_engine(database_url)
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_user(session, telegram_id: int) -> User | None:
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def get_user_accesses(session, user_id: int) -> list[VPNAccess]:
    result = await session.execute(
        select(VPNAccess)
        .where(VPNAccess.user_id == user_id)
        .order_by(VPNAccess.device_number.asc(), VPNAccess.id.asc())
    )
    return list(result.scalars().all())


def print_user(user: User | None) -> None:
    if user is None:
        print("User not found")
        return

    print(f"id={user.id}")
    print(f"telegram_id={user.telegram_id}")
    print(f"username={user.username}")
    print(f"language={user.language}")
    print(f"is_active={user.is_active}")
    print(f"access_type={user.access_type}")
    print(f"subscription_expiry={user.subscription_expiry}")
    print(f"traffic_used={user.traffic_used}")
    print(f"traffic_limit={user.traffic_limit}")
    print(f"device_limit={user.device_limit}")
    print(f"used_devices={user.used_devices}")
    print(f"terms_accepted={user.terms_accepted}")
    print(f"payment_status={user.payment_status}")
    print(f"payment_id={user.payment_id}")
    print(f"payment_kind={user.payment_kind}")
    print(f"payment_plan_code={user.payment_plan_code}")


def print_accesses(accesses: list[VPNAccess]) -> None:
    print(f"vpn_accesses_count={len(accesses)}")
    for access in accesses:
        print("---")
        print(f"vpn_access.id={access.id}")
        print(f"device_number={access.device_number}")
        print(f"device_name={access.device_name}")
        print(f"is_active={access.is_active}")
        print(f"server_name={access.server_name}")
        print(f"external_id={access.external_id}")
        print(f"client_uuid={access.client_uuid}")
        print(f"config_url={access.config_url}")


async def cmd_show(sessionmaker, telegram_id: int) -> None:
    async with sessionmaker() as session:
        user = await get_user(session, telegram_id)
        print_user(user)

        if user is None:
            return

        accesses = await get_user_accesses(session, user.id)
        print_accesses(accesses)


async def ensure_user(session, telegram_id: int) -> User:
    user = await get_user(session, telegram_id)
    if user is not None:
        return user

    user = User(
        telegram_id=telegram_id,
        language="ru",
        is_active=False,
        access_type=None,
        traffic_used=0,
        traffic_limit=3072,
        device_limit=1,
        used_devices=0,
        terms_accepted=True,
        terms_accepted_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(user)
    await session.flush()
    return user


async def cmd_free(sessionmaker, telegram_id: int) -> None:
    async with sessionmaker() as session:
        user = await ensure_user(session, telegram_id)

        user.is_active = True
        user.access_type = "free"
        user.subscription_expiry = None
        user.traffic_limit = 3072
        user.traffic_used = 0
        user.device_limit = 1
        user.used_devices = 0
        user.terms_accepted = True
        user.terms_accepted_at = user.terms_accepted_at or datetime.now(UTC).replace(tzinfo=None)

        user.payment_status = None
        user.payment_id = None
        user.payment_kind = None
        user.payment_plan_code = None
        user.payment_devices_to_add = 0
        user.payment_confirmation_url = None
        user.payment_promo_code = None

        await session.execute(
            delete(VPNAccess).where(VPNAccess.user_id == user.id)
        )

        await session.commit()
        print(f"OK: user {telegram_id} -> free")


async def cmd_paid(sessionmaker, telegram_id: int, days: int) -> None:
    async with sessionmaker() as session:
        user = await ensure_user(session, telegram_id)

        user.is_active = True
        user.access_type = "paid"
        user.subscription_expiry = (datetime.now(UTC) + timedelta(days=days)).replace(tzinfo=None)
        user.traffic_limit = 3072
        user.traffic_used = 0
        user.device_limit = 2
        user.used_devices = 0
        user.terms_accepted = True
        user.terms_accepted_at = user.terms_accepted_at or datetime.now(UTC).replace(tzinfo=None)

        user.payment_status = None
        user.payment_id = None
        user.payment_kind = None
        user.payment_plan_code = None
        user.payment_devices_to_add = 0
        user.payment_confirmation_url = None
        user.payment_promo_code = None

        await session.execute(
            delete(VPNAccess).where(VPNAccess.user_id == user.id)
        )

        await session.commit()
        print(f"OK: user {telegram_id} -> paid ({days} days)")


async def cmd_reset(sessionmaker, telegram_id: int) -> None:
    async with sessionmaker() as session:
        user = await get_user(session, telegram_id)
        if user is None:
            print("User not found")
            return

        await session.execute(
            delete(VPNAccess).where(VPNAccess.user_id == user.id)
        )
        await session.delete(user)
        await session.commit()
        print(f"OK: user {telegram_id} reset")


def make_fake_config(telegram_id: int, device_number: int, client_uuid: str) -> str:
    return (
        f"vless://{client_uuid}@dev.local:443"
        f"?type=tcp&security=reality&pbk=DEV_PUBLIC_KEY"
        f"&fp=chrome&sni=dev.local&sid=dev{device_number}&headerType=none"
        f"#user_{telegram_id}_{device_number}"
    )


async def cmd_key_show(sessionmaker, telegram_id: int) -> None:
    async with sessionmaker() as session:
        user = await get_user(session, telegram_id)
        if user is None:
            print("User not found")
            return

        accesses = await get_user_accesses(session, user.id)
        print_accesses(accesses)


async def cmd_key_clear(sessionmaker, telegram_id: int) -> None:
    async with sessionmaker() as session:
        user = await get_user(session, telegram_id)
        if user is None:
            print("User not found")
            return

        await session.execute(
            delete(VPNAccess).where(VPNAccess.user_id == user.id)
        )
        user.used_devices = 0
        await session.commit()
        print(f"OK: cleared keys for user {telegram_id}")


async def cmd_key_create(sessionmaker, telegram_id: int, device_number: int) -> None:
    async with sessionmaker() as session:
        user = await ensure_user(session, telegram_id)

        existing_result = await session.execute(
            select(VPNAccess).where(
                VPNAccess.user_id == user.id,
                VPNAccess.device_number == device_number,
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            print(f"ERROR: device_number {device_number} already exists for user {telegram_id}")
            return

        client_uuid = str(uuid4())
        access = VPNAccess(
            user_id=user.id,
            server_name="dev",
            external_id=f"user_{telegram_id}_{device_number}",
            client_uuid=client_uuid,
            config_url=make_fake_config(telegram_id, device_number, client_uuid),
            is_active=True,
            device_number=device_number,
            device_name=f"Устройство {device_number}",
        )
        session.add(access)

        user.used_devices = max(user.used_devices or 0, device_number)

        if user.access_type == "free" and user.device_limit < 1:
            user.device_limit = 1

        if user.access_type == "paid" and user.device_limit < 2:
            user.device_limit = 2

        await session.commit()
        print(f"OK: created key for user {telegram_id}, device {device_number}")


async def main() -> None:
    if len(sys.argv) < 3:
        usage()
        raise SystemExit(1)

    command = sys.argv[1]
    telegram_id = int(sys.argv[2])
    sessionmaker = get_sessionmaker()

    if command == "show":
        await cmd_show(sessionmaker, telegram_id)
        return

    if command == "free":
        await cmd_free(sessionmaker, telegram_id)
        return

    if command == "paid":
        days = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        await cmd_paid(sessionmaker, telegram_id, days)
        return

    if command == "reset":
        await cmd_reset(sessionmaker, telegram_id)
        return

    if command == "key-show":
        await cmd_key_show(sessionmaker, telegram_id)
        return

    if command == "key-create":
        device_number = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        await cmd_key_create(sessionmaker, telegram_id, device_number)
        return

    if command == "key-clear":
        await cmd_key_clear(sessionmaker, telegram_id)
        return

    usage()
    raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
