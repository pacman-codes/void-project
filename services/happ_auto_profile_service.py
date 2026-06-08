from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit

from db.models import User, VPNAccess
from services.subscription_link_service import (
    SubscriptionLinkError,
    _build_subscription_profile_name,
    _build_vless_outbound,
    _direct_rules_for_rows,
    _load_subscription_context,
    _normalize_config_endpoint_by_registry,
    _server_display_name,
)


HAPP_AUTO_ENV_PATH = os.getenv("VOID_HAPP_AUTO_ENV_PATH", "/etc/void/happ_auto_profile.env")


def build_public_happ_auto_url(token: str) -> str:
    base_url = os.getenv("SUBSCRIPTION_PUBLIC_BASE_URL", "http://127.0.0.1:8088").rstrip("/")
    return f"{base_url}/happ-auto/{token}"


def _read_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}

    try:
        with open(path, "r", encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()

                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")

                if key:
                    values[key] = value
    except FileNotFoundError:
        return {}
    except PermissionError as exc:
        raise SubscriptionLinkError(f"Нет доступа к {path}") from exc

    return values


def _settings() -> dict[str, str]:
    file_values = _read_env_file(HAPP_AUTO_ENV_PATH)
    merged = dict(file_values)

    for key, value in os.environ.items():
        if key.startswith("VOID_HAPP_AUTO_") or key.startswith("VOID_CDN_XHTTP_"):
            merged[key] = value

    return merged


def _setting(name: str, default: str = "") -> str:
    return _settings().get(name, default).strip()


def _required_setting(name: str) -> str:
    value = _setting(name)

    if not value:
        raise SubscriptionLinkError(f"Не задан {name} для Auto профиля")

    if value.startswith("PASTE_") or value.endswith("_HERE"):
        raise SubscriptionLinkError(f"Не заполнен {name} в {HAPP_AUTO_ENV_PATH}")

    return value


def _allowed_telegram_ids() -> set[int]:
    raw = _setting("VOID_HAPP_AUTO_ALLOWED_TELEGRAM_IDS")

    allowed: set[int] = set()
    for part in raw.split(","):
        part = part.strip()

        if not part:
            continue

        try:
            allowed.add(int(part))
        except ValueError:
            continue

    return allowed


def _ensure_auto_allowed(user: User) -> None:
    allowed = _allowed_telegram_ids()

    if not allowed:
        raise SubscriptionLinkError("Auto профиль пока никому не разрешён")

    telegram_id = int(getattr(user, "telegram_id", 0) or 0)

    if telegram_id not in allowed:
        raise SubscriptionLinkError("Auto профиль не включён для этого пользователя")


def _safe_tag(value: str, fallback: str) -> str:
    raw = (value or fallback).strip().lower()
    raw = re.sub(r"[^a-z0-9_.-]+", "-", raw)
    raw = raw.strip("-_.")
    return raw or fallback


def _vless_rows(rows: list[VPNAccess]) -> list[VPNAccess]:
    result: list[VPNAccess] = []

    for row in rows:
        config_url = (row.config_url or "").strip()

        try:
            scheme = urlsplit(config_url).scheme.lower()
        except Exception:
            scheme = ""

        if scheme == "vless":
            result.append(row)

    return result


def _build_normal_vless_outbounds(
    rows: list[VPNAccess],
    by_code: dict[str, object],
    by_endpoint: dict[str, object],
) -> tuple[list[dict], list[VPNAccess]]:
    outbounds: list[dict] = []
    used_rows: list[VPNAccess] = []

    for index, row in enumerate(_vless_rows(rows), start=1):
        config_url = _normalize_config_endpoint_by_registry(
            config_url=(row.config_url or "").strip(),
            row=row,
            by_code=by_code,
        )

        if not config_url:
            continue

        outbound = _build_vless_outbound(config_url)
        display_name = _server_display_name(row, by_code, by_endpoint)
        outbound["tag"] = f"normal-{index}-{_safe_tag(display_name, f'node-{index}')}"

        outbounds.append(outbound)
        used_rows.append(row)

    if not outbounds:
        raise SubscriptionLinkError("Для Auto профиля не найдено VLESS-нoд")

    return outbounds, used_rows


def _build_cdn_xhttp_outbound() -> dict:
    address = _required_setting("VOID_CDN_XHTTP_ADDRESS")
    uuid = _required_setting("VOID_CDN_XHTTP_UUID")
    path = _required_setting("VOID_CDN_XHTTP_PATH")

    port = int(_setting("VOID_CDN_XHTTP_PORT", "443"))
    sni = _setting("VOID_CDN_XHTTP_SNI", address)
    host = _setting("VOID_CDN_XHTTP_HOST", sni)
    mode = _setting("VOID_CDN_XHTTP_MODE", "packet-up")

    xhttp_settings = {
        "host": host,
        "path": path,
        "mode": mode,
        "xPaddingBytes": _setting("VOID_CDN_XHTTP_PADDING_BYTES", "1-4"),
        "xPaddingObfsMode": _setting("VOID_CDN_XHTTP_PADDING_OBFS", "true").lower() in {"1", "true", "yes", "on"},
        "xPaddingMethod": _setting("VOID_CDN_XHTTP_PADDING_METHOD", "tokenish"),
        "xPaddingPlacement": _setting("VOID_CDN_XHTTP_PADDING_PLACEMENT", "header"),
        "xPaddingHeader": _setting("VOID_CDN_XHTTP_PADDING_HEADER", "X-Cache"),
        "xPaddingKey": _setting("VOID_CDN_XHTTP_PADDING_KEY", "_dc"),
    }

    user = {
        "id": uuid,
        "email": "cdn@void.local",
        "security": "auto",
        "encryption": "none",
    }

    flow = _setting("VOID_CDN_XHTTP_FLOW")
    if flow:
        user["flow"] = flow

    return {
        "tag": "cdn-selectel-xhttp",
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": address,
                    "port": port,
                    "users": [user],
                }
            ]
        },
        "streamSettings": {
            "network": "xhttp",
            "security": "tls",
            "tlsSettings": {
                "serverName": sni,
                "allowInsecure": False,
                "alpn": [
                    _setting("VOID_CDN_XHTTP_ALPN", "h2"),
                ],
            },
            "xhttpSettings": xhttp_settings,
        },
        "mux": {
            "enabled": False,
            "concurrency": -1,
        },
    }


def _build_auto_config(
    user: User,
    rows: list[VPNAccess],
    by_code: dict[str, object],
    by_endpoint: dict[str, object],
) -> dict:
    normal_outbounds, used_vless_rows = _build_normal_vless_outbounds(rows, by_code, by_endpoint)
    cdn_outbound = _build_cdn_xhttp_outbound()
    direct_rules = _direct_rules_for_rows(used_vless_rows)

    profile_name = _build_subscription_profile_name(user)

    return {
        "remarks": f"{profile_name}-auto-test",
        "log": {
            "loglevel": "warning",
        },
        "dns": {
            "servers": [
                "1.1.1.1",
                "8.8.8.8",
            ],
            "tag": "dns-module",
        },
        "observatory": {
            "subjectSelector": [
                "normal-",
            ],
            "probeUrl": _setting("VOID_HAPP_AUTO_PROBE_URL", "https://www.gstatic.com/generate_204"),
            "probeInterval": _setting("VOID_HAPP_AUTO_PROBE_INTERVAL", "30s"),
            "enableConcurrency": True,
        },
        "inbounds": [
            {
                "tag": "tun",
                "protocol": "tun",
                "sniffing": {
                    "enabled": True,
                    "destOverride": [
                        "http",
                        "tls",
                        "quic",
                    ],
                    "routeOnly": False,
                },
                "settings": {
                    "name": _setting("VOID_AUTO_TUN_NAME", "utun11"),
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
            }
        ],
        "outbounds": [
            *normal_outbounds,
            cdn_outbound,
            {
                "tag": "direct",
                "protocol": "freedom",
                "settings": {
                    "domainStrategy": "UseIPv4",
                },
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
                    "network": "tcp,udp",
                    "balancerTag": "void-auto",
                },
            ],
            "balancers": [
                {
                    "tag": "void-auto",
                    "selector": [
                        "normal-",
                    ],
                    "fallbackTag": "cdn-selectel-xhttp",
                    "strategy": {
                        "type": "leastPing",
                    },
                }
            ],
        },
    }


def _safe_outbound_status(outbound: dict) -> dict:
    tag = str(outbound.get("tag") or "")
    protocol = str(outbound.get("protocol") or "")

    result: dict = {
        "tag": tag,
        "protocol": protocol,
    }

    vnext = (((outbound.get("settings") or {}).get("vnext") or []) + [{}])[0]
    if vnext:
        result["address"] = vnext.get("address")
        result["port"] = vnext.get("port")

    stream = outbound.get("streamSettings") or {}
    if stream:
        result["network"] = stream.get("network")
        result["security"] = stream.get("security")

    if tag == "cdn-selectel-xhttp":
        result["role"] = "fallback_only"
        result["note"] = "CDN включается только если normal-ноды недоступны по observatory/balancer. UUID/path скрыты."
    elif tag.startswith("normal-"):
        result["role"] = "normal_candidate"

    return result


def _build_auto_status(config: dict) -> dict:
    outbounds = [
        _safe_outbound_status(outbound)
        for outbound in config.get("outbounds", [])
        if str(outbound.get("tag") or "").startswith("normal-")
        or str(outbound.get("tag") or "") == "cdn-selectel-xhttp"
    ]

    routing = config.get("routing") or {}
    balancers = routing.get("balancers") or []

    return {
        "profile": config.get("remarks"),
        "important": "Это показывает, что зашито в профиль. Фактический выбор происходит внутри клиента Happ/Incy, не на сервере подписки.",
        "normal_selection": "leastPing по normal-* outbounds",
        "fallback": "cdn-selectel-xhttp включается только если normal-* недоступны",
        "probe": config.get("observatory"),
        "balancers": balancers,
        "outbounds": outbounds,
    }


def _strip_client_managed_tun(config: dict) -> dict:
    """iOS VPN apps own the system tunnel themselves.

    Do not include Xray tun inbounds in app-imported JSON profiles.
    Otherwise Happ/Incy can fail with:
    - interface name must be utunN
    - operation not permitted
    """
    config = json.loads(json.dumps(config, ensure_ascii=False))

    config.pop("inbounds", None)

    routing = config.get("routing") or {}
    rules = routing.get("rules") or []
    routing["rules"] = [
        rule
        for rule in rules
        if not (
            isinstance(rule, dict)
            and "inboundTag" in rule
        )
    ]

    return config


async def build_auto_json_by_token(token: str) -> str:
    user, selected_rows, by_code, by_endpoint = await _load_subscription_context(token)

    _ensure_auto_allowed(user)

    config = _build_auto_config(
        user=user,
        rows=selected_rows,
        by_code=by_code,
        by_endpoint=by_endpoint,
    )
    config = _strip_client_managed_tun(config)

    return json.dumps(config, ensure_ascii=False, indent=2) + "\n"


async def build_auto_status_by_token(token: str) -> str:
    user, selected_rows, by_code, by_endpoint = await _load_subscription_context(token)

    _ensure_auto_allowed(user)

    config = _build_auto_config(
        user=user,
        rows=selected_rows,
        by_code=by_code,
        by_endpoint=by_endpoint,
    )
    config = _strip_client_managed_tun(config)

    return json.dumps(_build_auto_status(config), ensure_ascii=False, indent=2) + "\n"


async def build_happ_cdn_json_by_token(token: str) -> str:
    user, _, _, _ = await _load_subscription_context(token)

    _ensure_auto_allowed(user)

    profile_name = _build_subscription_profile_name(user)
    cdn_outbound = _build_cdn_xhttp_outbound()

    config = {
        "remarks": f"{profile_name}-cdn-test",
        "log": {
            "loglevel": "warning",
        },
        "dns": {
            "servers": [
                "1.1.1.1",
                "8.8.8.8",
            ],
            "tag": "dns-module",
        },
        "outbounds": [
            cdn_outbound,
            {
                "tag": "direct",
                "protocol": "freedom",
                "settings": {
                    "domainStrategy": "UseIPv4",
                },
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
                    "port": "0-65535",
                    "outboundTag": "cdn-selectel-xhttp",
                },
            ],
        },
    }

    return json.dumps(config, ensure_ascii=False, indent=2) + "\n"


async def build_happ_cdn_min_json_by_token(token: str) -> str:
    user, _, _, _ = await _load_subscription_context(token)

    _ensure_auto_allowed(user)

    address = _required_setting("VOID_CDN_XHTTP_ADDRESS")
    uuid = _required_setting("VOID_CDN_XHTTP_UUID")
    path = _required_setting("VOID_CDN_XHTTP_PATH")
    port = int(_setting("VOID_CDN_XHTTP_PORT", "443"))
    sni = _setting("VOID_CDN_XHTTP_SNI", address)
    host = _setting("VOID_CDN_XHTTP_HOST", sni)

    config = {
        "log": {
            "loglevel": "info",
            "access": "/tmp/xhttp-selectel-selftest/client-access.log",
            "error": "/tmp/xhttp-selectel-selftest/client-error.log",
        },
        "inbounds": [
            {
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "port": 10888,
                "protocol": "socks",
                "settings": {
                    "auth": "noauth",
                    "udp": False,
                },
            }
        ],
        "outbounds": [
            {
                "tag": "xhttp-out",
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": address,
                            "port": port,
                            "users": [
                                {
                                    "id": uuid,
                                    "encryption": "none",
                                }
                            ],
                        }
                    ]
                },
                "streamSettings": {
                    "network": "xhttp",
                    "security": "tls",
                    "tlsSettings": {
                        "serverName": sni,
                        "alpn": [
                            "h2",
                        ],
                        "fingerprint": "chrome",
                    },
                    "xhttpSettings": {
                        "host": host,
                        "path": path,
                        "mode": _setting("VOID_CDN_XHTTP_MODE", "packet-up"),
                        "xPaddingBytes": _setting("VOID_CDN_XHTTP_PADDING_BYTES", "1-4"),
                        "xPaddingObfsMode": _setting("VOID_CDN_XHTTP_PADDING_OBFS", "true").lower() in {"1", "true", "yes", "on"},
                        "xPaddingMethod": _setting("VOID_CDN_XHTTP_PADDING_METHOD", "tokenish"),
                        "xPaddingPlacement": _setting("VOID_CDN_XHTTP_PADDING_PLACEMENT", "header"),
                        "xPaddingHeader": _setting("VOID_CDN_XHTTP_PADDING_HEADER", "X-Cache"),
                        "xPaddingKey": _setting("VOID_CDN_XHTTP_PADDING_KEY", "_dc"),
                    },
                },
                "mux": {
                    "enabled": False,
                    "concurrency": -1,
                },
            },
            {
                "tag": "block",
                "protocol": "blackhole",
            },
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {
                    "type": "field",
                    "network": "udp",
                    "port": "443",
                    "outboundTag": "block",
                }
            ],
        },
    }

    return json.dumps(config, ensure_ascii=False, indent=2) + "\n"




# Backward-compatible names for subscription_server.py
build_happ_auto_json_by_token = build_auto_json_by_token
build_happ_auto_status_by_token = build_auto_status_by_token

# Experimental Happ auto v2 post-process: Panda/Nofox-like routing.
# Keeps existing builder, but makes the exported /happ-auto profile use
# socks/http inbounds and includes CDN XHTTP in the auto balancer.
_original_build_auto_json_by_token_panda_like = build_auto_json_by_token

async def build_auto_json_by_token(token: str) -> str:
    raw = await _original_build_auto_json_by_token_panda_like(token)
    config = json.loads(raw)

    outbounds = config.get("outbounds", [])

    proxy_tags = []
    for o in outbounds:
        tag = o.get("tag")
        if not tag:
            continue
        if tag.startswith("normal-") or tag == "cdn-selectel-xhttp":
            proxy_tags.append(tag)

    if "cdn-selectel-xhttp" not in proxy_tags:
        proxy_tags.append("cdn-selectel-xhttp")

    config["remarks"] = "VOID Auto Panda-like"

    config["inbounds"] = [
        {
            "listen": "127.0.0.1",
            "port": 10808,
            "protocol": "socks",
            "settings": {
                "auth": "noauth",
                "udp": True
            },
            "sniffing": {
                "enabled": True,
                "destOverride": ["http", "tls", "quic"],
                "routeOnly": False
            },
            "tag": "socks"
        },
        {
            "listen": "127.0.0.1",
            "port": 10809,
            "protocol": "http",
            "settings": {
                "allowTransparent": False
            },
            "sniffing": {
                "enabled": True,
                "destOverride": ["http", "tls", "quic"],
                "routeOnly": False
            },
            "tag": "http"
        }
    ]

    config["dns"] = {
        "queryStrategy": "UseIP",
        "servers": [
            "1.1.1.1",
            "8.8.8.8"
        ]
    }

    config["observatory"] = {
        "subjectSelector": proxy_tags,
        "probeURL": "http://www.gstatic.com/generate_204",
        "probeInterval": "30s",
        "enableConcurrency": True
    }

    config["burstObservatory"] = {
        "subjectSelector": proxy_tags,
        "pingConfig": {
            "destination": "http://www.gstatic.com/generate_204",
            "connectivity": "",
            "interval": "1m",
            "sampling": 1,
            "timeout": "3s"
        }
    }

    config["routing"] = {
        "domainMatcher": "hybrid",
        "domainStrategy": "IPIfNonMatch",
        "balancers": [
            {
                "tag": "void-auto",
                "selector": proxy_tags,
                "fallbackTag": "cdn-selectel-xhttp",
                "strategy": {
                    "type": "leastPing"
                }
            }
        ],
        "rules": [
            {
                "type": "field",
                "protocol": ["bittorrent"],
                "outboundTag": "block"
            },
            {
                "type": "field",
                "domain": [
                    "full:gepg.voidmod.space",
                    "full:nlpg-vl.voidmod.space",
                    "full:s-sel.voidmod.space"
                ],
                "outboundTag": "direct"
            },
            {
                "type": "field",
                "ip": ["geoip:private"],
                "outboundTag": "direct"
            },
            {
                "type": "field",
                "network": "tcp,udp",
                "balancerTag": "void-auto"
            }
        ]
    }

    return json.dumps(config, ensure_ascii=False, indent=2) + "\n"


# Rebind backward-compatible names after experimental override.
build_happ_auto_json_by_token = build_auto_json_by_token
