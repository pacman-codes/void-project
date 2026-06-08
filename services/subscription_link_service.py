from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from sqlalchemy import select

from db.database import async_session_maker
from db.models import User, UserSubscriptionLink, VPNAccess

try:
    from services.server_registry import load_server_nodes
except Exception:
    load_server_nodes = None


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


def build_public_v2rayn_json_url(token: str) -> str:
    base_url = os.getenv("SUBSCRIPTION_PUBLIC_BASE_URL", "http://127.0.0.1:8088")
    return f"{base_url.rstrip('/')}/v2rayn/{token}"


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




def _node_value(node: object, names: tuple[str, ...]) -> object | None:
    for name in names:
        if isinstance(node, dict) and name in node:
            value = node.get(name)
        else:
            value = getattr(node, name, None)

        if value not in (None, ""):
            return value

    return None


def _registry_public_host_port(
    row: VPNAccess,
    by_code: dict[str, object],
) -> tuple[str | None, int | None]:
    server_name = (row.server_name or "").strip()
    node = by_code.get(server_name)

    if node is None:
        return None, None

    host = _node_value(
        node,
        (
            "public_host",
            "subscription_host",
            "host",
            "domain",
            "address",
            "server_host",
        ),
    )

    port_value = _node_value(
        node,
        (
            "public_port",
            "vless_port",
            "port",
        ),
    )

    port = None
    if port_value not in (None, ""):
        try:
            port = int(port_value)
        except Exception:
            port = None

    if host is None:
        return None, port

    return str(host), port


def _normalize_config_endpoint_by_registry(
    config_url: str,
    row: VPNAccess,
    by_code: dict[str, object],
) -> str:
    config_url = (config_url or "").strip()

    if not config_url:
        return config_url

    # Only VLESS links should be host-normalized by registry.
    # HY2 links carry their own port/SNI and must stay as generated.
    if not config_url.startswith("vless://"):
        return config_url

    host, port = _registry_public_host_port(row, by_code)

    if not host:
        return config_url

    try:
        parts = urlsplit(config_url)
    except Exception:
        return config_url

    if not parts.scheme or not parts.netloc:
        return config_url

    username = parts.username or ""
    password = parts.password

    auth = username
    if password:
        auth = f"{username}:{password}"

    if port is None:
        port = parts.port

    netloc = f"{auth}@{host}" if auth else host
    if port:
        netloc = f"{netloc}:{port}"

    query_items = dict(parse_qsl(parts.query, keep_blank_values=True))

    node = by_code.get((row.server_name or "").strip())

    # Do not override pbk/sni/sid/spx/fp from the panel-generated config_url.
    # Those values must match the real inbound. Registry is used here only for
    # public host/port normalization and for adding flow if it is missing.
    if node is not None and not query_items.get("flow"):
        flow = _node_value(node, ("flow",))
        if flow:
            query_items["flow"] = str(flow)

    return urlunsplit(
        (
            parts.scheme,
            netloc,
            parts.path,
            urlencode(query_items, doseq=False, safe="/"),
            parts.fragment,
        )
    )


def _with_fragment(config_url: str, fragment: str) -> str:
    if not config_url.startswith(("vless://", "hysteria2://", "hy2://")):
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
    if load_server_nodes is None:
        return {}, {}

    try:
        # Load all registry nodes for subscription display/normalization.
        # Disabled nodes are not provisioned automatically elsewhere, but active
        # manual/test rows should still use their registry display_name.
        nodes = load_server_nodes()
    except Exception:
        return {}, {}

    by_code = {node.code: node for node in nodes}
    by_endpoint = {node.endpoint: node for node in nodes}

    return by_code, by_endpoint


def _server_sort_key(row: VPNAccess, by_code: dict[str, object], by_endpoint: dict[str, object]) -> tuple:
    config_url = (row.config_url or "").strip()
    scheme = ""

    try:
        scheme = urlsplit(config_url).scheme.lower()
    except Exception:
        scheme = ""

    # Subscription order:
    # 1. VLESS nodes first
    # 2. reserve/experimental non-VLESS nodes after
    protocol_order = 0 if scheme == "vless" else 1

    server_name = row.server_name or ""
    endpoint = _endpoint_from_config_url(row.config_url)

    node = by_code.get(server_name) or by_endpoint.get(endpoint)

    if node is not None:
        return (
            protocol_order,
            -int(getattr(node, "priority", 0)),
            str(getattr(node, "code", "")),
            row.id,
        )

    return (protocol_order, 0, server_name, row.id)


def _server_display_name(row: VPNAccess, by_code: dict[str, object], by_endpoint: dict[str, object]) -> str:
    server_name = row.server_name or ""
    endpoint = _endpoint_from_config_url(row.config_url)

    config_url = (row.config_url or "").strip()
    try:
        scheme = urlsplit(config_url).scheme.lower()
    except Exception:
        scheme = ""

    if scheme in {"hysteria2", "hy2"}:
        if endpoint == "gepg.voidmod.space:8443":
            return "🧬 Резерв"
        if endpoint == "nlpg-vl.voidmod.space:443":
            return "🧪 Резерв"

    node = by_code.get(server_name) or by_endpoint.get(endpoint)

    if node is not None:
        display_name = str(getattr(node, "display_name", "")).strip()
        if display_name:
            return display_name

    if server_name == "cdn_selectel_xhttp":
        device_name = (getattr(row, "device_name", None) or "").strip()
        if device_name:
            return device_name

    if server_name and server_name != "main":
        return server_name.replace("_", "-")

    if endpoint:
        return endpoint

    return f"node-{row.id}"


def _dedupe_rows_by_server(rows: list[VPNAccess], by_code: dict[str, object], by_endpoint: dict[str, object]) -> list[VPNAccess]:
    selected: list[VPNAccess] = []
    seen: set[str] = set()
    allowed_prefixes = ("vless://", "hysteria2://", "hy2://")

    for row in sorted(rows, key=lambda item: _server_sort_key(item, by_code, by_endpoint)):
        config_url = (row.config_url or "").strip()

        if not config_url.startswith(allowed_prefixes):
            continue

        scheme = urlsplit(config_url).scheme.lower()
        endpoint = _endpoint_from_config_url(config_url)
        server_name = row.server_name or ""

        node = by_code.get(server_name) or by_endpoint.get(endpoint)

        if scheme == "vless":
            if node is not None:
                key = f"registry:{getattr(node, 'code', '')}"
            elif server_name:
                key = f"server:{server_name}"
            elif endpoint:
                key = f"endpoint:{endpoint}"
            else:
                key = f"access:{row.id}"
        else:
            # Experimental/non-VLESS rows must not collide with the normal VLESS node
            # that uses the same server_name/endpoint.
            key = f"{scheme}:access:{row.id}"

        if key in seen:
            continue

        seen.add(key)
        selected.append(row)

    return selected


LEGACY_SUBSCRIPTION_SERVER_NAMES = {"main", "dev", "migration-8449"}
VLESS_TECHNICAL_DEVICE_MIN = 100
HY2_TECHNICAL_DEVICE_MIN = 9000


def _access_device_number(row: VPNAccess) -> int:
    try:
        return int(row.device_number or 0)
    except Exception:
        return 0


def _access_url_scheme(row: VPNAccess) -> str:
    config_url = (row.config_url or "").strip()

    if not config_url:
        return ""

    try:
        return (urlsplit(config_url).scheme or "").lower()
    except Exception:
        return ""


def _node_enabled(node: object) -> bool:
    if isinstance(node, dict):
        return bool(node.get("enabled", False))

    return bool(getattr(node, "enabled", False))


def _node_protocol(node: object) -> str:
    if isinstance(node, dict):
        return str(node.get("protocol", "") or "").strip().lower()

    return str(getattr(node, "protocol", "") or "").strip().lower()


def _is_subscription_output_row_allowed(
    row: VPNAccess,
    by_code: dict[str, object],
) -> bool:
    """Allow only production subscription technical rows.

    This intentionally blocks legacy real-device rows even if they were migrated
    from server_name='main' to a registry server like germany_1.

    Allowed:
    - VLESS registry technical rows: device_number 100..8999
    - HY2 backup technical rows: device_number >= 9000

    Blocked:
    - legacy main/dev/migration rows
    - old device slots 1/2
    - disabled/test/unknown registry nodes
    - unsupported URL schemes
    """
    server_name = (row.server_name or "").strip()
    config_url = (row.config_url or "").strip()
    device_name = (getattr(row, "device_name", None) or "").strip()

    # Manual whitelist/mobile CDN row. Keep this narrow on purpose:
    # do not allow arbitrary unknown rows into normal subscriptions.
    if (
        server_name == "cdn_selectel_xhttp"
        and device_name == "мобилка"
        and config_url.startswith(("vless://", "hysteria2://", "hy2://"))
    ):
        return True

    if not server_name or server_name in LEGACY_SUBSCRIPTION_SERVER_NAMES:
        return False

    node = by_code.get(server_name)
    if node is None:
        return False

    if not _node_enabled(node):
        return False

    if _node_protocol(node) != "vless":
        return False

    scheme = _access_url_scheme(row)
    device_number = _access_device_number(row)

    if scheme == "vless":
        return VLESS_TECHNICAL_DEVICE_MIN <= device_number < HY2_TECHNICAL_DEVICE_MIN

    if scheme in {"hysteria2", "hy2"}:
        return device_number >= HY2_TECHNICAL_DEVICE_MIN

    return False


async def _load_subscription_context(token: str) -> tuple[User, list[VPNAccess], dict[str, object], dict[str, object]]:
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

        # Strict production subscription filter.
        # Do not fall back to legacy rows: dirty historical DB rows must not
        # leak into client subscription profiles.
        rows = [
            row
            for row in rows
            if _is_subscription_output_row_allowed(row, by_code)
        ]

        selected_rows = _dedupe_rows_by_server(rows, by_code, by_endpoint)

        if not selected_rows:
            raise SubscriptionLinkError("Активные ключи не найдены")

        now = _now()
        link.last_used_at = now

        if link.migrated_at is None:
            link.migrated_at = now
            link.raw_disable_after = now + timedelta(days=RAW_KEY_GRACE_DAYS)

        await session.commit()

        return user, selected_rows, by_code, by_endpoint


async def build_subscription_by_token(token: str) -> str:
    user, selected_rows, by_code, by_endpoint = await _load_subscription_context(token)

    config_urls = [
        _with_fragment(
            config_url=_normalize_config_endpoint_by_registry(
                config_url=(row.config_url or "").strip(),
                row=row,
                by_code=by_code,
            ),
            fragment=_server_display_name(row, by_code, by_endpoint),
        )
        for row in selected_rows
    ]

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


def _parse_vless_url(config_url: str) -> tuple:
    parts = urlsplit(config_url)
    query = dict(parse_qsl(parts.query))

    if parts.scheme != "vless" or not parts.username or not parts.hostname or not parts.port:
        raise SubscriptionLinkError("Некорректная ссылка подключения")

    return parts, query


def _direct_rules_for_rows(rows: list[VPNAccess]) -> list[dict]:
    ip_values: list[str] = []
    domain_values: list[str] = []

    for row in rows:
        config_url = (row.config_url or "").strip()

        try:
            parts, _ = _parse_vless_url(config_url)
        except SubscriptionLinkError:
            continue

        host = parts.hostname

        if not host:
            continue

        try:
            ip_obj = ipaddress.ip_address(host)
        except ValueError:
            domain_values.append(f"full:{host}")
            continue

        if ip_obj.version == 4:
            ip_values.append(f"{host}/32")
        else:
            ip_values.append(f"{host}/128")

    rules: list[dict] = []

    if ip_values:
        rules.append({
            "type": "field",
            "ip": sorted(set(ip_values)),
            "outboundTag": "direct",
        })

    if domain_values:
        rules.append({
            "type": "field",
            "domain": sorted(set(domain_values)),
            "outboundTag": "direct",
        })

    return rules


def _build_vless_outbound(config_url: str) -> dict:
    parts, query = _parse_vless_url(config_url)

    user = {
        "id": parts.username,
        "email": "t@t.tt",
        "security": "auto",
        "encryption": query.get("encryption", "none"),
    }

    if query.get("flow"):
        user["flow"] = query["flow"]

    network = query.get("type", "tcp")
    if network == "tcp":
        network = "raw"

    security = query.get("security", "reality")

    stream_settings: dict = {
        "network": network,
        "security": security,
    }

    if security == "reality":
        stream_settings["realitySettings"] = {
            "serverName": query.get("sni", ""),
            "fingerprint": query.get("fp", "firefox"),
            "show": False,
            "publicKey": query.get("pbk", ""),
            "shortId": query.get("sid", ""),
            "spiderX": query.get("spx", "/"),
            "mldsa65Verify": "",
        }
    elif security == "tls":
        stream_settings["tlsSettings"] = {
            "serverName": query.get("sni", parts.hostname or ""),
            "allowInsecure": False,
        }

    return {
        "tag": "proxy",
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": parts.hostname,
                    "port": parts.port,
                    "users": [user],
                }
            ]
        },
        "streamSettings": stream_settings,
        "mux": {
            "enabled": False,
            "concurrency": -1,
        },
    }


def _build_v2rayn_json_config(rows: list[VPNAccess]) -> dict:
    first_config_url = (rows[0].config_url or "").strip()
    proxy_outbound = _build_vless_outbound(first_config_url)
    direct_rules = _direct_rules_for_rows(rows)

    return {
        "log": {
            "loglevel": "warning",
        },
        "dns": {
            "hosts": {
                "dns.google": [
                    "8.8.8.8",
                    "8.8.4.4",
                    "2001:4860:4860::8888",
                    "2001:4860:4860::8844",
                ],
                "one.one.one.one": [
                    "1.1.1.1",
                    "1.0.0.1",
                    "2606:4700:4700::1111",
                    "2606:4700:4700::1001",
                ],
            },
            "servers": [
                "8.8.8.8",
                "1.1.1.1",
            ],
            "tag": "dns-module",
        },
        "inbounds": [
            {
                "tag": "socks",
                "port": 10808,
                "listen": "127.0.0.1",
                "protocol": "mixed",
                "sniffing": {
                    "enabled": True,
                    "destOverride": [
                        "http",
                        "tls",
                    ],
                    "routeOnly": False,
                },
                "settings": {
                    "auth": "noauth",
                    "udp": True,
                    "allowTransparent": False,
                },
            },
            {
                "tag": "tun",
                "protocol": "tun",
                "sniffing": {
                    "enabled": True,
                    "destOverride": [
                        "http",
                        "tls",
                    ],
                    "routeOnly": False,
                },
                "settings": {
                    "name": "xray_tun",
                    "MTU": 1500,
                    "gateway": [
                        "172.18.0.1/30",
                    ],
                    "autoSystemRoutingTable": [
                        "0.0.0.0/0",
                        "::/0",
                    ],
                    "autoOutboundsInterface": "auto",
                },
            },
        ],
        "outbounds": [
            proxy_outbound,
            {
                "tag": "direct",
                "protocol": "freedom",
            },
            {
                "tag": "block",
                "protocol": "blackhole",
            },
            {
                "tag": "dns",
                "protocol": "dns",
            },
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {
                    "type": "field",
                    "inboundTag": [
                        "api",
                    ],
                    "outboundTag": "api",
                },
                {
                    "port": "135,137-139,5353",
                    "network": "udp",
                    "outboundTag": "block",
                },
                {
                    "outboundTag": "block",
                    "ip": [
                        "224.0.0.0/3",
                        "ff00::/8",
                    ],
                },
                *direct_rules,
                {
                    "port": "53",
                    "inboundTag": [
                        "tun",
                    ],
                    "outboundTag": "dns",
                },
                {
                    "type": "field",
                    "outboundTag": "direct",
                    "ip": [
                        "geoip:private",
                    ],
                },
                {
                    "type": "field",
                    "outboundTag": "direct",
                    "domain": [
                        "geosite:private",
                    ],
                },
                {
                    "type": "field",
                    "port": "0-65535",
                    "outboundTag": "proxy",
                },
            ],
        },
    }


async def build_v2rayn_json_by_token(token: str) -> str:
    _, selected_rows, _, _ = await _load_subscription_context(token)
    config = _build_v2rayn_json_config(selected_rows)
    return json.dumps(config, ensure_ascii=False, indent=2) + "\n"
