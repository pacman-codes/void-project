from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from sqlalchemy import func, select

from db.database import async_session_maker
from db.models import User, UserSubscriptionLink, VPNAccess


def utcnow() -> datetime:
    return datetime.utcnow()


def user_has_active_access(user: User) -> bool:
    if user.access_type == "free":
        return True

    if user.access_type == "paid":
        return bool(user.subscription_expiry and user.subscription_expiry > utcnow())

    return False


async def report() -> None:
    async with async_session_maker() as session:
        users_total = await session.scalar(select(func.count(User.id)))
        active_access_rows = await session.scalar(
            select(func.count(VPNAccess.id)).where(VPNAccess.is_active.is_(True))
        )
        links_total = await session.scalar(select(func.count(UserSubscriptionLink.id)))
        links_active = await session.scalar(
            select(func.count(UserSubscriptionLink.id)).where(
                UserSubscriptionLink.is_active.is_(True)
            )
        )
        links_used = await session.scalar(
            select(func.count(UserSubscriptionLink.id)).where(
                UserSubscriptionLink.last_used_at.is_not(None)
            )
        )
        links_migrated = await session.scalar(
            select(func.count(UserSubscriptionLink.id)).where(
                UserSubscriptionLink.migrated_at.is_not(None)
            )
        )

    print("=== report ===")
    print(f"users_total={users_total or 0}")
    print(f"active_access_rows={active_access_rows or 0}")
    print(f"subscription_links_total={links_total or 0}")
    print(f"subscription_links_active={links_active or 0}")
    print(f"subscription_links_used={links_used or 0}")
    print(f"subscription_links_migrated={links_migrated or 0}")


async def notify_dry_run(limit: int) -> None:
    async with async_session_maker() as session:
        result = await session.execute(select(User).order_by(User.id.asc()).limit(limit))
        users = list(result.scalars().all())

        rows = []

        for user in users:
            if not user_has_active_access(user):
                continue

            access_count = await session.scalar(
                select(func.count(VPNAccess.id)).where(
                    VPNAccess.user_id == user.id,
                    VPNAccess.is_active.is_(True),
                    VPNAccess.config_url.is_not(None),
                )
            )

            if not access_count:
                continue

            link = await session.scalar(
                select(UserSubscriptionLink).where(
                    UserSubscriptionLink.user_id == user.id,
                    UserSubscriptionLink.is_active.is_(True),
                )
            )

            rows.append((user, int(access_count or 0), link))

    print("=== notify dry-run ===")
    print("No messages are sent by this command.")
    print(f"checked_limit={limit}")
    print(f"candidates={len(rows)}")
    print()

    for user, access_count, link in rows:
        print(
            f"telegram_id={user.telegram_id} "
            f"user_id={user.id} "
            f"access_type={user.access_type} "
            f"access_rows={access_count} "
            f"has_link={bool(link)} "
            f"migrated_at={getattr(link, 'migrated_at', None)} "
            f"raw_disable_after={getattr(link, 'raw_disable_after', None)}"
        )


async def disable_raw_dry_run(limit: int) -> None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserSubscriptionLink, User)
            .join(User, User.id == UserSubscriptionLink.user_id)
            .where(
                UserSubscriptionLink.is_active.is_(True),
                UserSubscriptionLink.migrated_at.is_not(None),
                UserSubscriptionLink.raw_disable_after.is_not(None),
                UserSubscriptionLink.raw_disable_after <= utcnow(),
            )
            .order_by(UserSubscriptionLink.raw_disable_after.asc())
            .limit(limit)
        )
        rows = list(result.all())

    print("=== raw disable dry-run ===")
    print("No keys are disabled by this command.")
    print(f"limit={limit}")
    print(f"candidates={len(rows)}")
    print()

    for link, user in rows:
        print(
            f"telegram_id={user.telegram_id} "
            f"user_id={user.id} "
            f"access_type={user.access_type} "
            f"migrated_at={link.migrated_at} "
            f"raw_disable_after={link.raw_disable_after}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["report", "notify-dry-run", "disable-raw-dry-run"],
    )
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()

    if args.command == "report":
        await report()
    elif args.command == "notify-dry-run":
        await notify_dry_run(args.limit)
    elif args.command == "disable-raw-dry-run":
        await disable_raw_dry_run(args.limit)


if __name__ == "__main__":
    asyncio.run(main())
