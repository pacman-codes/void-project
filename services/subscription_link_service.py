from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timedelta
from urllib.parse import quote, urlsplit, urlunsplit

from sqlalchemy import select

from db.database import async_session_maker
from db.models import User, UserSubscriptionLink, VPNAccess

try:
    from services.server_registry import load_enabled_server_nodes
except Exception:
    load_enabled_server_nodes = None


RAW_KEY_GRACE_DAYS = 5
DEFAULT_FREE_TRAFFIC_LIMIT_MB = 3072


class SubscriptionLinkError(Exception):
    pass


def _now() -> datetime:
    return datetime.utcnow()


def _make_token() -> str:
    return secrets.token_urlsafe(32)


def _user_has_active_access(user: User) -> bool:
    if user.access_type == "free":
        traffic_used = max(int(user.traffic_used or 0), 0)
        traffic_limit = int(user.traffic_limit or DEFAULT_FREE_TRAFFIC_LIMIT_MB)
        return bool(user.is_active) and traffic_used < traffic_limit

    if user.access_type == "paid":
        return bool(user.subscription_expiry and user.subscription_expiry > _now())

    return False


def build_public_subscription_url(token: str) -> str:
    base_url = os.getenv("SUBSCRIPTION_PUBLIC_BASE_URL", "http://127.0.0.1:8088")
    return f"{base_url.rstrip('/')}/sub/{token}"


def build_public_happ_import_url(token: str) -> str:
    base_url = os.getenv("SUBSCRIPTION_PUBLIC_BASE_URL", "http://127.0.0.1:8088").rstrip("/")
    return f"{base_url}/happ/{token}"


async def get_or_create_subscription_link(telegram_id: int) -> UserSubscriptionLink:
    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()

        if user is None:
            raise SubscriptionLinkError("Пользователь не найден")

        link_result = await session.execute(
            select(UserSubscriptionLink).where(
                UserSubscriptionLink.user_id == user.id,
                UserSubscriptionLink.is_active.is_(True),
            )
        )
        link = link_result.scalar_one_or_none()

        if link is not None:
            return link

        for _ in range(5):
            token = _make_token()
            existing_result = await session.execute(
                select(UserSubscriptionLink).where(UserSubscriptionLink.token == token)
            )
            if existing_result.scalar_one_or_none() is None:
                link = UserSubscriptionLink(
                    user_id=user.id,
                    token=token,
                    is_active=True,
                    created_at=_now(),
                )
                session.add(link)
                await session.commit()
                await session.refresh(link)
                return link

        raise SubscriptionLinkError("Не удалось создать уникальную ссылку подписки")


def _build_subscription_profile_name(user: User) -> str:
    username = getattr(user, "username", None)
    telegram_id = getattr(user, "telegram_id", None)

    if username:
        raw = str(username).strip().lstrip("@")
    elif telegram_id:
        raw = f"id{telegram_id}"
    else:
        raw = "user"

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-_.")
    if not safe:
        safe = "user"

    return f"void-{safe}"


def _with_fragment(config_url: str, fragment: str) -> str:
    if not config_url.startswith("vless://"):
        return config_url

    parts = urlsplit(config_url)
    return urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        parts.query,
        quote(fragment, safe="-_."),
    ))


def _endpoint_from_config_url(config_url: str | None) -> str:
    if not config_url:
        return ""

    try:
        parts = urlsplit(config_url)
    except Exception:
        return ""

    if not parts.hostname or not parts.port:
        return ""

    return f"{parts.hostname}:{parts.port}"


def _load_registry_maps() -> tuple[dict[str, object], dict[str, object]]:
    if load_enabled_server_nodes is None:
        return {}, {}

    try:
        nodes = load_enabled_server_nodes()
    except Exception:
        return {}, {}

    by_code = {node.code: node for node in nodes}
    by_endpoint = {node.endpoint: node for node in nodes}

    return by_code, by_endpoint


def _server_sort_key(row: VPNAccess, by_code: dict[str, object], by_endpoint: dict[str, object]) -> tuple:
    server_name = row.server_name or ""
    endpoint = _endpoint_from_config_url(row.config_url)

    node = by_code.get(server_name) or by_endpoint.get(endpoint)

    if node is not None:
        return (-int(getattr(node, "priority", 0)), str(getattr(node, "code", "")), row.id)

    return (0, server_name, row.id)


def _server_display_name(row: VPNAccess, by_code: dict[str, object], by_endpoint: dict[str, object]) -> str:
    server_name = row.server_name or ""
    endpoint = _endpoint_from_config_url(row.config_url)

    node = by_code.get(server_name) or by_endpoint.get(endpoint)

    if node is not None:
        display_name = str(getattr(node, "display_name", "")).strip()
        if display_name:
            return display_name

    if server_name and server_name != "main":
        return server_name.replace("_", "-")

    if endpoint:
        return endpoint

    return f"node-{row.id}"


def _dedupe_rows_by_server(rows: list[VPNAccess], by_code: dict[str, object], by_endpoint: dict[str, object]) -> list[VPNAccess]:
    selected: list[VPNAccess] = []
    seen: set[str] = set()

    for row in sorted(rows, key=lambda item: _server_sort_key(item, by_code, by_endpoint)):
        config_url = (row.config_url or "").strip()

        if not config_url.startswith("vless://"):
            continue

        endpoint = _endpoint_from_config_url(config_url)
        server_name = row.server_name or ""

        node = by_code.get(server_name) or by_endpoint.get(endpoint)

        if node is not None:
            key = f"registry:{getattr(node, 'code', '')}"
        elif server_name:
            key = f"server:{server_name}"
        elif endpoint:
            key = f"endpoint:{endpoint}"
        else:
            key = f"access:{row.id}"

        if key in seen:
            continue

        seen.add(key)
        selected.append(row)

    return selected


async def build_subscription_by_token(token: str) -> str:
    async with async_session_maker() as session:
        link_result = await session.execute(
            select(UserSubscriptionLink).where(
                UserSubscriptionLink.token == token,
                UserSubscriptionLink.is_active.is_(True),
            )
        )
        link = link_result.scalar_one_or_none()

        if link is None:
            raise SubscriptionLinkError("Подключение не найдено или отключено")

        user_result = await session.execute(
            select(User).where(User.id == link.user_id)
        )
        user = user_result.scalar_one_or_none()

        if user is None:
            raise SubscriptionLinkError("Пользователь не найден")

        if not _user_has_active_access(user):
            raise SubscriptionLinkError("Доступ не активен")

        access_result = await session.execute(
            select(VPNAccess)
            .where(
                VPNAccess.user_id == user.id,
                VPNAccess.is_active.is_(True),
                VPNAccess.config_url.is_not(None),
            )
            .order_by(VPNAccess.id.asc())
        )
        rows = list(access_result.scalars().all())

        by_code, by_endpoint = _load_registry_maps()
        selected_rows = _dedupe_rows_by_server(rows, by_code, by_endpoint)

        config_urls = [
            _with_fragment(
                config_url=(row.config_url or "").strip(),
                fragment=_server_display_name(row, by_code, by_endpoint),
            )
            for row in selected_rows
        ]

        if not config_urls:
            raise SubscriptionLinkError("Активные ключи не найдены")

        now = _now()
        link.last_used_at = now

        if link.migrated_at is None:
            link.migrated_at = now
            link.raw_disable_after = now + timedelta(days=RAW_KEY_GRACE_DAYS)

        await session.commit()

        profile_name = _build_subscription_profile_name(user)

        header_lines = [
            f"#profile-title: {profile_name}",
            "#subscription-auto-update-enable: 1",
            "#subscription-auto-update-open-enable: 1",
            "#subscription-autoconnect: 1",
            "#subscription-autoconnect-type: lowestdelay",
            "#subscription-ping-onopen-enabled: 1",
            "#subscriptions-expand-now: 1",
            "#ping-result: icon",
        ]

        return "\n".join(header_lines + config_urls) + "\n"
