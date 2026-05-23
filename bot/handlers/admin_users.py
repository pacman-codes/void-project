from __future__ import annotations

import html
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import text

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


@router.message(Command("adminUsers"))
async def admin_users_handler(message: Message) -> None:
    if not is_admin(message):
        return

    args = parse_admin_args(message)
    access_filter = None
    limit = 50

    if args:
        if args[0] in {"paid", "free", "none"}:
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

    where_sql = ""
    params = {"limit": limit}

    if access_filter == "paid":
        where_sql = "WHERE u.access_type = 'paid'"
    elif access_filter == "free":
        where_sql = "WHERE u.access_type = 'free'"
    elif access_filter == "none":
        where_sql = "WHERE u.access_type IS NULL OR u.access_type = ''"

    async with async_session_maker() as session:
        stats_result = await session.execute(text("""
            SELECT
                COUNT(*) AS total_users,
                COUNT(*) FILTER (WHERE access_type = 'paid') AS total_paid,
                COUNT(*) FILTER (WHERE access_type = 'free') AS total_free,
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

        users_result = await session.execute(text(f"""
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
        """), params)
        users = users_result.mappings().all()

    now = datetime.utcnow()

    lines = [
        "👥 Admin users",
        f"candidates: {len(users)}",
        "",
        f"total: {stats['total_users'] or 0}",
        f"paid: {stats['total_paid'] or 0}",
        f"free: {stats['total_free'] or 0}",
        f"none: {stats['total_none'] or 0}",
        "",
        "💰 paid_plans:",
    ]

    if paid_plans:
        for row in paid_plans:
            label = plan_label(row["plan_code"])
            lines.append(f"• {html.escape(label)}: {row['users_count']}")
    else:
        lines.append("• none: 0")

    lines.append("")

    for user in users:
        telegram_id = user["telegram_id"]
        username = user["username"]
        access_type = user["access_type"]
        subscription_expiry = user["subscription_expiry"]
        user_plan_code = user["plan_code"]

        if username:
            profile = f'<a href="https://t.me/{html.escape(username)}">@{html.escape(username)}</a>'
        else:
            profile = f'<a href="tg://user?id={telegram_id}">@-</a>'

        tail = access_type or "none"

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

            tail = f"{tail}/{plan_label(user_plan_code)}"

        elif access_type == "free":
            tail = "free/start"
        else:
            tail = "none/start"

        lines.append(f"• {telegram_id} {profile} {html.escape(tail)}")

    output = "\n".join(lines)

    for i in range(0, len(output), 3500):
        await message.answer(
            output[i:i + 3500],
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
