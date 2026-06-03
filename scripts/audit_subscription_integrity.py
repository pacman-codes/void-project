#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from db.database import async_session_maker
from db.models import User, UserSubscriptionLink, VPNAccess
from services.server_registry import load_server_nodes


LEGACY_SERVER_NAMES = {"main", "dev", "migration-8449"}
VLESS_TECHNICAL_DEVICE_MIN = 100
HY2_TECHNICAL_DEVICE_MIN = 9000


@dataclass(frozen=True)
class RegistryState:
    all_codes: set[str]
    enabled_codes: set[str]
    enabled_vless_codes: set[str]
    disabled_codes: set[str]


def _scheme(config_url: str | None) -> str:
    value = (config_url or "").strip().lower()
    if "://" not in value:
        return ""
    return value.split("://", 1)[0]


def _device_number(access: VPNAccess) -> int:
    try:
        return int(access.device_number or 0)
    except Exception:
        return 0


def _is_hy2(access: VPNAccess) -> bool:
    return _scheme(access.config_url) in {"hysteria2", "hy2"}


def _is_vless(access: VPNAccess) -> bool:
    return _scheme(access.config_url) == "vless"


def _is_vless_technical(access: VPNAccess, registry: RegistryState) -> bool:
    device = _device_number(access)
    server_name = (access.server_name or "").strip()
    return (
        _is_vless(access)
        and server_name in registry.enabled_vless_codes
        and VLESS_TECHNICAL_DEVICE_MIN <= device < HY2_TECHNICAL_DEVICE_MIN
    )


def _is_hy2_technical(access: VPNAccess, registry: RegistryState) -> bool:
    device = _device_number(access)
    server_name = (access.server_name or "").strip()
    return (
        _is_hy2(access)
        and server_name in registry.enabled_vless_codes
        and device >= HY2_TECHNICAL_DEVICE_MIN
    )


def _print_section(title: str) -> None:
    print()
    print("=" * 90)
    print(title)
    print("=" * 90)


def _format_access(access: VPNAccess, user: User) -> str:
    return (
        f"tg={user.telegram_id} "
        f"access_id={access.id} "
        f"server={access.server_name} "
        f"device={access.device_number} "
        f"name={access.device_name!r} "
        f"external_id={access.external_id!r} "
        f"scheme={_scheme(access.config_url)}"
    )


async def load_registry() -> RegistryState:
    nodes = load_server_nodes()
    all_codes = {node.code for node in nodes}
    enabled_codes = {node.code for node in nodes if node.enabled}
    enabled_vless_codes = {
        node.code
        for node in nodes
        if node.enabled and (node.protocol or "").lower() == "vless"
    }
    disabled_codes = {node.code for node in nodes if not node.enabled}

    return RegistryState(
        all_codes=all_codes,
        enabled_codes=enabled_codes,
        enabled_vless_codes=enabled_vless_codes,
        disabled_codes=disabled_codes,
    )


async def load_data():
    async with async_session_maker() as session:
        users_result = await session.execute(select(User))
        users = list(users_result.scalars().all())

        access_result = await session.execute(select(VPNAccess))
        accesses = list(access_result.scalars().all())

        links_result = await session.execute(
            select(UserSubscriptionLink).where(UserSubscriptionLink.is_active.is_(True))
        )
        active_links = list(links_result.scalars().all())

    users_by_id = {user.id: user for user in users}
    active_link_user_ids = {link.user_id for link in active_links}

    return users, users_by_id, accesses, active_link_user_ids


def eligible_users(users: list[User], active_link_user_ids: set[int]) -> list[User]:
    result: list[User] = []

    for user in users:
        if user.id not in active_link_user_ids:
            continue
        if not user.is_active:
            continue
        if not user.telegram_id or int(user.telegram_id) <= 100000:
            continue

        if user.access_type == "paid":
            # Keep broad here: audit should not silently drop paid users with NULL expiry.
            result.append(user)
            continue

        if user.access_type == "free":
            used = int(user.traffic_used or 0)
            limit = int(user.traffic_limit or 3072)
            if used < limit:
                result.append(user)

    return result


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=80)
    args = parser.parse_args()

    registry = await load_registry()
    users, users_by_id, accesses, active_link_user_ids = await load_data()

    active_accesses = [a for a in accesses if a.is_active]
    active_by_user: dict[int, list[VPNAccess]] = defaultdict(list)
    for access in active_accesses:
        active_by_user[access.user_id].append(access)

    eligible = eligible_users(users, active_link_user_ids)
    eligible_by_id = {user.id: user for user in eligible}

    _print_section("REGISTRY")
    print("all_codes:", sorted(registry.all_codes))
    print("enabled_codes:", sorted(registry.enabled_codes))
    print("enabled_vless_codes:", sorted(registry.enabled_vless_codes))
    print("disabled_codes:", sorted(registry.disabled_codes))

    _print_section("ACTIVE ROW COUNTS BY SERVER/DEVICE")
    counts: dict[tuple[str, int], int] = defaultdict(int)
    for access in active_accesses:
        counts[((access.server_name or "-"), _device_number(access))] += 1

    for (server_name, device), count in sorted(counts.items()):
        print(f"{server_name:16} device={device:<5} active={count}")

    checks: list[tuple[str, list[str]]] = []

    legacy_rows: list[str] = []
    disabled_rows: list[str] = []
    unknown_rows: list[str] = []
    old_device_rows: list[str] = []
    unsupported_rows: list[str] = []

    for access in active_accesses:
        user = users_by_id.get(access.user_id)
        if user is None:
            continue

        server_name = (access.server_name or "").strip()
        device = _device_number(access)
        scheme = _scheme(access.config_url)

        if server_name in LEGACY_SERVER_NAMES:
            legacy_rows.append(_format_access(access, user))

        if server_name in registry.disabled_codes:
            disabled_rows.append(_format_access(access, user))

        if server_name and server_name not in registry.all_codes and server_name not in LEGACY_SERVER_NAMES:
            unknown_rows.append(_format_access(access, user))

        if device in {1, 2}:
            old_device_rows.append(_format_access(access, user))

        if scheme and scheme not in {"vless", "hysteria2", "hy2"}:
            unsupported_rows.append(_format_access(access, user))

    checks.append(("ACTIVE LEGACY SERVER ROWS", legacy_rows))
    checks.append(("ACTIVE DISABLED REGISTRY SERVER ROWS", disabled_rows))
    checks.append(("ACTIVE UNKNOWN SERVER ROWS", unknown_rows))
    checks.append(("ACTIVE OLD DEVICE SLOT ROWS", old_device_rows))
    checks.append(("ACTIVE UNSUPPORTED SCHEME ROWS", unsupported_rows))

    duplicate_technical_rows: list[str] = []
    for user_id, rows in active_by_user.items():
        user = users_by_id.get(user_id)
        if user is None:
            continue

        grouped: dict[tuple[str, int], list[VPNAccess]] = defaultdict(list)
        for access in rows:
            if _is_vless_technical(access, registry) or _is_hy2_technical(access, registry):
                grouped[((access.server_name or ""), _device_number(access))].append(access)

        for (server_name, device), group in grouped.items():
            if len(group) > 1:
                ids = [str(item.id) for item in group]
                duplicate_technical_rows.append(
                    f"tg={user.telegram_id} server={server_name} device={device} row_ids={','.join(ids)}"
                )

    checks.append(("DUPLICATE ACTIVE TECHNICAL ROWS", duplicate_technical_rows))

    missing_vless: list[str] = []
    missing_hy2: list[str] = []

    for user in eligible:
        rows = active_by_user.get(user.id, [])

        for server_code in sorted(registry.enabled_vless_codes):
            has_vless = any(
                (access.server_name or "").strip() == server_code
                and _is_vless_technical(access, registry)
                for access in rows
            )
            if not has_vless:
                missing_vless.append(f"tg={user.telegram_id} missing_vless={server_code}")

            has_hy2 = any(
                (access.server_name or "").strip() == server_code
                and _is_hy2_technical(access, registry)
                for access in rows
            )
            if not has_hy2:
                missing_hy2.append(f"tg={user.telegram_id} missing_hy2={server_code}")

    checks.append(("ELIGIBLE USERS MISSING ENABLED VLESS TECHNICAL ROWS", missing_vless))
    checks.append(("ELIGIBLE USERS MISSING HY2 BACKUP ROWS", missing_hy2))

    _print_section("SUMMARY")
    total_issues = 0
    for title, items in checks:
        total_issues += len(items)
        print(f"{title}: {len(items)}")

    _print_section("DETAILS")
    for title, items in checks:
        print()
        print(f"--- {title}: {len(items)} ---")
        for item in items[: args.limit]:
            print(item)
        if len(items) > args.limit:
            print(f"... truncated: {len(items) - args.limit} more")

    _print_section("RESULT")
    if total_issues:
        print(f"AUDIT FOUND ISSUES: {total_issues}")
    else:
        print("AUDIT OK")


if __name__ == "__main__":
    asyncio.run(main())
