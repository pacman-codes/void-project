from __future__ import annotations

import html
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.admin_tools import is_admin, parse_admin_args
from db.database import async_session_maker

router = Router()


def plan_label(plan_code: str | None) -> str:
    if not plan_code:
        return "unknown"

    labels = {
        "plan_1m": "1m_249",
        "plan_6m": "6m_discount",
        "plan_12m": "12m_year",
    }

    return labels.get(plan_code, plan_code)


def parse_admin_users_args(message: Message) -> tuple[str | None, int]:
    args = parse_admin_args(message)
    access_filter = None
    limit = 50

    if args:
        if args[0] in {"paid", "free", "none", "trial"}:
            access_filter = args[0]

            if len(args) > 1:
                try:
                    limit = max(1, min(int(args[1]), 300))
                except ValueError:
                    pass
        else:
            try:
                limit = max(1, min(int(args[0]), 300))
            except ValueError:
                pass

    return access_filter, limit


def build_profile_link(telegram_id: int, username: str | None) -> str:
    if username:
        safe_username = html.escape(username)
        return f'<a href="https://t.me/{safe_username}">@{safe_username}</a>'

    return f'<a href="tg://user?id={telegram_id}">@-</a>'


def build_user_tail(
    *,
    telegram_id: int,
    access_type: str | None,
    terms_accepted: bool,
    is_active: bool,
    subscription_expiry: datetime | None,
    plan_code: str | None,
    now: datetime,
) -> str:
    if telegram_id < 1000000:
        if access_type == "trial":
            return "trial_legacy/start"
        return "none_test_like/start"

    if access_type == "paid":
        if subscription_expiry:
            delta = subscription_expiry - now

            if delta.total_seconds() <= 0:
                tail = "paid_expired"
            elif delta.days > 0:
                tail = f"paid_expiring/{delta.days}d"
            else:
                hours = max(1, int(delta.total_seconds() // 3600))
                tail = f"paid_expiring/{hours}h"
        else:
            tail = "paid_no_expiry"

        return f"{tail}/{plan_label(plan_code)}"

    if access_type == "free":
        if is_active:
            return "free/start"
        if terms_accepted:
            return "free_inactive_terms/start"
        return "free_inactive_no_terms/start"

    if access_type == "trial":
        return "trial_legacy/start"

    if terms_accepted:
        return "none_terms_no_access/start"

    return "none_no_terms/start"


async def build_admin_users_report(
    session: AsyncSession,
    *,
    access_filter: str | None,
    limit: int,
) -> str:
    where_sql = ""

    if access_filter == "paid":
        where_sql = "WHERE u.access_type = 'paid'"
    elif access_filter == "free":
        where_sql = "WHERE u.access_type = 'free'"
    elif access_filter == "none":
        where_sql = "WHERE u.access_type IS NULL OR u.access_type = ''"
    elif access_filter == "trial":
        where_sql = "WHERE u.access_type = 'trial'"

    stats_result = await session.execute(text("""
        SELECT
            COUNT(*) AS total_users,
            COUNT(*) FILTER (WHERE access_type = 'paid') AS total_paid,
            COUNT(*) FILTER (WHERE access_type = 'free') AS total_free,
            COUNT(*) FILTER (WHERE access_type = 'trial') AS total_trial,
            COUNT(*) FILTER (WHERE access_type IS NULL OR access_type = '') AS total_none
        FROM users;
    """))
    stats = stats_result.mappings().one()

    paid_plans_result = await session.execute(text("""
        WITH latest_paid_plan AS (
            SELECT DISTINCT ON (target_telegram_id)
                target_telegram_id,
                COALESCE(
                    NULLIF(details_json::jsonb ->> 'payment_plan_code', ''),
                    NULLIF(details_json::jsonb ->> 'plan_code', '')
                ) AS plan_code
            FROM user_events
            WHERE target_telegram_id IS NOT NULL
              AND details_json IS NOT NULL
              AND details_json <> ''
              AND details_json LIKE '{%'
              AND (
                event_type IN (
                    'payment_created',
                    'payment_succeeded',
                    'subscription_paid_activated'
                )
                OR details_json ILIKE '%plan_code%'
                OR details_json ILIKE '%payment_plan_code%'
              )
            ORDER BY target_telegram_id, created_at DESC
        )
        SELECT
            COALESCE(
                NULLIF(u.payment_plan_code, ''),
                latest_paid_plan.plan_code,
                'unknown'
            ) AS plan_code,
            COUNT(*) AS users_count
        FROM users u
        LEFT JOIN latest_paid_plan
            ON latest_paid_plan.target_telegram_id = u.telegram_id
        WHERE u.access_type = 'paid'
        GROUP BY 1
        ORDER BY users_count DESC, plan_code ASC;
    """))
    paid_plans = paid_plans_result.mappings().all()

    users_sql = f"""
        WITH latest_paid_plan AS (
            SELECT DISTINCT ON (target_telegram_id)
                target_telegram_id,
                COALESCE(
                    NULLIF(details_json::jsonb ->> 'payment_plan_code', ''),
                    NULLIF(details_json::jsonb ->> 'plan_code', '')
                ) AS plan_code
            FROM user_events
            WHERE target_telegram_id IS NOT NULL
              AND details_json IS NOT NULL
              AND details_json <> ''
              AND details_json LIKE '{{%'
              AND (
                event_type IN (
                    'payment_created',
                    'payment_succeeded',
                    'subscription_paid_activated'
                )
                OR details_json ILIKE '%plan_code%'
                OR details_json ILIKE '%payment_plan_code%'
              )
            ORDER BY target_telegram_id, created_at DESC
        )
        SELECT
            u.id,
            u.telegram_id,
            u.username,
            u.access_type,
            COALESCE(u.terms_accepted, false) AS terms_accepted,
            COALESCE(u.is_active, false) AS is_active,
            u.subscription_expiry,
            COALESCE(
                NULLIF(u.payment_plan_code, ''),
                latest_paid_plan.plan_code,
                'unknown'
            ) AS plan_code
        FROM users u
        LEFT JOIN latest_paid_plan
            ON latest_paid_plan.target_telegram_id = u.telegram_id
        {where_sql}
        ORDER BY u.id DESC
        LIMIT :limit;
    """

    users_result = await session.execute(text(users_sql), {"limit": limit})
    users = users_result.mappings().all()

    now = datetime.utcnow()

    lines = [
        "👥 Admin users",
        f"candidates: {len(users)}",
        "",
        f"total: {stats['total_users'] or 0}",
        f"paid: {stats['total_paid'] or 0}",
        f"free: {stats['total_free'] or 0}",
        f"trial: {stats['total_trial'] or 0}",
        f"none: {stats['total_none'] or 0}",
        "",
        "💰 paid_plans:",
    ]

    if paid_plans:
        for row in paid_plans:
            lines.append(f"• {html.escape(plan_label(row['plan_code']))}: {row['users_count']}")
    else:
        lines.append("• none: 0")

    lines.append("")

    for user in users:
        telegram_id = int(user["telegram_id"])
        username = user["username"]
        access_type = user["access_type"]
        terms_accepted = bool(user["terms_accepted"])
        is_active = bool(user["is_active"])
        subscription_expiry = user["subscription_expiry"]
        user_plan_code = user["plan_code"]

        profile = build_profile_link(telegram_id, username)

        tail = build_user_tail(
            telegram_id=telegram_id,
            access_type=access_type,
            terms_accepted=terms_accepted,
            is_active=is_active,
            subscription_expiry=subscription_expiry,
            plan_code=user_plan_code,
            now=now,
        )

        lines.append(f"• {telegram_id} {profile} {html.escape(tail)}")

    return "\n".join(lines)


async def send_report_chunks(message: Message, report: str) -> None:
    lines = report.split("\n")
    chunks: list[str] = []
    current = ""

    for line in lines:
        next_line = line if not current else current + "\n" + line

        if len(next_line) > 3400:
            if current:
                chunks.append(current)
            current = line
        else:
            current = next_line

    if current:
        chunks.append(current)

    for chunk in chunks:
        await message.answer(
            chunk,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


@router.message(Command("adminUsers"))
async def admin_users_handler(message: Message) -> None:
    if not is_admin(message):
        return

    access_filter, limit = parse_admin_users_args(message)

    async with async_session_maker() as session:
        report = await build_admin_users_report(
            session,
            access_filter=access_filter,
            limit=limit,
        )

    await send_report_chunks(message, report)
