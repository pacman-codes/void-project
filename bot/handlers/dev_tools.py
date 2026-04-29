from datetime import datetime, timedelta, UTC
from uuid import uuid4

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import delete, select

from db.database import async_session_maker
from db.models import User, VPNAccess

router = Router()

ADMIN_ID = 1600207976


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def make_fake_config(telegram_id: int, device_number: int, client_uuid: str) -> str:
    return (
        f"vless://{client_uuid}@dev.local:443"
        f"?type=tcp&security=reality&pbk=DEV_PUBLIC_KEY"
        f"&fp=chrome&sni=dev.local&sid=dev{device_number}&headerType=none"
        f"#user_{telegram_id}_{device_number}"
    )


async def get_or_create_user(telegram_id: int, username: str | None) -> User:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
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
            await session.commit()
            await session.refresh(user)
            return user

        if user.username != username:
            user.username = username
            await session.commit()
            await session.refresh(user)

        return user


async def load_user_and_accesses(telegram_id: int) -> tuple[User | None, list[VPNAccess]]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return None, []

        result = await session.execute(
            select(VPNAccess)
            .where(VPNAccess.user_id == user.id)
            .order_by(VPNAccess.device_number.asc(), VPNAccess.id.asc())
        )
        accesses = list(result.scalars().all())
        return user, accesses


def build_user_dump(user: User | None, accesses: list[VPNAccess]) -> str:
    if user is None:
        return "User not found"

    lines = [
        f"telegram_id={user.telegram_id}",
        f"username={user.username}",
        f"access_type={user.access_type}",
        f"is_active={user.is_active}",
        f"subscription_expiry={user.subscription_expiry}",
        f"traffic_used={user.traffic_used}",
        f"traffic_limit={user.traffic_limit}",
        f"device_limit={user.device_limit}",
        f"used_devices={user.used_devices}",
        f"vpn_accesses_count={len(accesses)}",
    ]

    for access in accesses:
        lines.extend(
            [
                "---",
                f"device_number={access.device_number}",
                f"device_name={access.device_name}",
                f"is_active={access.is_active}",
                f"config_url={access.config_url}",
            ]
        )

    return "\n".join(lines)


async def ensure_fake_key(telegram_id: int, username: str | None, device_number: int, device_name: str) -> str:
    user = await get_or_create_user(telegram_id, username)

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        user = result.scalar_one()

        existing_result = await session.execute(
            select(VPNAccess).where(
                VPNAccess.user_id == user.id,
                VPNAccess.device_number == device_number,
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing is not None:
            return existing.config_url or "config_url not found"

        device_limit = int(user.device_limit or 1)
        if device_number > device_limit:
            raise ValueError(
                f"Device limit exceeded: device_number={device_number}, device_limit={device_limit}"
            )

        client_uuid = str(uuid4())
        config_url = make_fake_config(telegram_id, device_number, client_uuid)

        access = VPNAccess(
            user_id=user.id,
            server_name="dev",
            external_id=f"user_{telegram_id}_{device_number}",
            client_uuid=client_uuid,
            config_url=config_url,
            is_active=True,
            device_number=device_number,
            device_name=device_name,
        )
        session.add(access)

        user.used_devices = max(user.used_devices or 0, device_number)

        if user.access_type == "free" and user.device_limit < 1:
            user.device_limit = 1

        if user.access_type == "paid" and user.device_limit < 2:
            user.device_limit = 2

        await session.commit()
        return config_url


@router.message(Command("reset_profile"))
async def reset_profile(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if user is not None:
            await session.execute(delete(VPNAccess).where(VPNAccess.user_id == user.id))
            await session.delete(user)
            await session.commit()

    await message.answer("OK: reset")


@router.message(Command("dev_free"))
async def dev_free(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    user = await get_or_create_user(message.from_user.id, message.from_user.username)

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        user = result.scalar_one()

        user.access_type = "free"
        user.is_active = True
        user.subscription_expiry = None
        user.traffic_limit = 3072
        user.traffic_used = 0
        user.device_limit = 1
        user.used_devices = 0
        user.terms_accepted = True
        user.terms_accepted_at = user.terms_accepted_at or datetime.now(UTC).replace(tzinfo=None)

        await session.execute(delete(VPNAccess).where(VPNAccess.user_id == user.id))
        await session.commit()

    await message.answer("OK: FREE")


@router.message(Command("dev_paid"))
async def dev_paid(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    user = await get_or_create_user(message.from_user.id, message.from_user.username)

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        user = result.scalar_one()

        user.access_type = "paid"
        user.is_active = True
        user.subscription_expiry = (datetime.now(UTC) + timedelta(days=30)).replace(tzinfo=None)
        user.traffic_limit = 3072
        user.traffic_used = 0
        user.device_limit = 2
        user.used_devices = 0
        user.terms_accepted = True
        user.terms_accepted_at = user.terms_accepted_at or datetime.now(UTC).replace(tzinfo=None)

        await session.execute(delete(VPNAccess).where(VPNAccess.user_id == user.id))
        await session.commit()

    await message.answer("OK: PAID (30 days)")


@router.message(Command("dev_key"))
async def dev_key(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    try:
        config_url = await ensure_fake_key(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            device_number=1,
            device_name="DEV Device 1",
        )
        await message.answer(f"OK KEY 1:\n<code>{config_url}</code>", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"ERROR: {e}")


@router.message(Command("dev_key_2"))
async def dev_key_2(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    try:
        config_url = await ensure_fake_key(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            device_number=2,
            device_name="DEV Device 2",
        )
        await message.answer(f"OK KEY 2:\n<code>{config_url}</code>", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"ERROR: {e}")


@router.message(Command("dev_key_clear"))
async def dev_key_clear(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            await message.answer("User not found")
            return

        await session.execute(delete(VPNAccess).where(VPNAccess.user_id == user.id))
        user.used_devices = 0
        await session.commit()

    await message.answer("OK: keys cleared")


@router.message(Command("dev_user"))
async def dev_user(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    user, accesses = await load_user_and_accesses(message.from_user.id)
    await message.answer(build_user_dump(user, accesses))


@router.message(Command("dev_show_db"))
async def dev_show_db(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    user, accesses = await load_user_and_accesses(message.from_user.id)
    if user is None:
        await message.answer("User not found")
        return

    lines = [
        f"id={user.id}",
        f"telegram_id={user.telegram_id}",
        f"username={user.username}",
        f"access_type={user.access_type}",
        f"is_active={user.is_active}",
        f"device_limit={user.device_limit}",
        f"used_devices={user.used_devices}",
        f"vpn_accesses_count={len(accesses)}",
    ]
    await message.answer("\n".join(lines))


@router.message(Command("dev_smoke"))
async def dev_smoke(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    user, accesses = await load_user_and_accesses(message.from_user.id)

    lines = ["SMOKE CHECK OK"]

    if user is None:
        lines.append("user=missing")
    else:
        lines.append(f"user.access_type={user.access_type}")
        lines.append(f"user.is_active={user.is_active}")
        lines.append(f"user.device_limit={user.device_limit}")
        lines.append(f"user.used_devices={user.used_devices}")

    lines.append(f"vpn_accesses_count={len(accesses)}")
    await message.answer("\n".join(lines))
