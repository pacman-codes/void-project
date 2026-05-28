from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SERVER_REGISTRY_PATH = "/etc/void/servers.json"
DEFAULT_SERVER_SECRETS_PATH = "/etc/void/server_secrets.env"


class ServerRegistryError(Exception):
    pass


@dataclass(frozen=True)
class ServerNode:
    code: str
    display_name: str
    provider: str
    provider_note: str
    enabled: bool
    priority: int
    public_host: str
    public_port: int
    panel_origin: str
    panel_path: str
    inbound_id: int
    protocol: str
    network: str
    security: str
    flow: str
    fingerprint: str
    sni: str
    short_id: str
    spider_x: str
    secret_ref: str

    @property
    def endpoint(self) -> str:
        return f"{self.public_host}:{self.public_port}"

    @property
    def direct_cidr(self) -> str:
        if ":" in self.public_host:
            return f"{self.public_host}/128"
        return f"{self.public_host}/32"


@dataclass(frozen=True)
class PanelCredentials:
    username: str
    password: str


def _load_json_file(path: str) -> dict:
    file_path = Path(path)

    if not file_path.exists():
        raise ServerRegistryError(f"Server registry file not found: {path}")

    try:
        data = json.loads(file_path.read_text())
    except json.JSONDecodeError as exc:
        raise ServerRegistryError(f"Invalid JSON in server registry: {path}") from exc

    if not isinstance(data, dict):
        raise ServerRegistryError("Server registry root must be a JSON object")

    return data


def _load_env_file(path: str) -> dict[str, str]:
    file_path = Path(path)

    if not file_path.exists():
        return {}

    values: dict[str, str] = {}

    for raw in file_path.read_text().splitlines():
        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

    return values


def _require_str(item: dict, key: str) -> str:
    value = item.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ServerRegistryError(f"Server field '{key}' is required and must be a non-empty string")

    return value.strip()


def _optional_str(item: dict, key: str, default: str = "") -> str:
    value = item.get(key, default)

    if value is None:
        return default

    if not isinstance(value, str):
        raise ServerRegistryError(f"Server field '{key}' must be a string")

    return value.strip()


def _optional_bool(item: dict, key: str, default: bool = False) -> bool:
    value = item.get(key, default)

    if isinstance(value, bool):
        return value

    raise ServerRegistryError(f"Server field '{key}' must be boolean")


def _optional_int(item: dict, key: str, default: int) -> int:
    value = item.get(key, default)

    if isinstance(value, bool):
        raise ServerRegistryError(f"Server field '{key}' must be integer")

    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ServerRegistryError(f"Server field '{key}' must be integer") from exc


def _normalize_panel_path(path: str) -> str:
    path = path.strip()

    if not path:
        raise ServerRegistryError("panel_path is required")

    if not path.startswith("/"):
        path = f"/{path}"

    return path.rstrip("/")


def _build_server_node(item: dict) -> ServerNode:
    if not isinstance(item, dict):
        raise ServerRegistryError("Each server registry item must be an object")

    code = _require_str(item, "code")

    return ServerNode(
        code=code,
        display_name=_optional_str(item, "display_name", default=code.replace("_", "-")),
        provider=_optional_str(item, "provider", default=""),
        provider_note=_optional_str(item, "provider_note", default=""),
        enabled=_optional_bool(item, "enabled", default=True),
        priority=_optional_int(item, "priority", default=100),
        public_host=_require_str(item, "public_host"),
        public_port=_optional_int(item, "public_port", default=443),
        panel_origin=_require_str(item, "panel_origin").rstrip("/"),
        panel_path=_normalize_panel_path(_require_str(item, "panel_path")),
        inbound_id=_optional_int(item, "inbound_id", default=0),
        protocol=_optional_str(item, "protocol", default="vless"),
        network=_optional_str(item, "network", default="tcp"),
        security=_optional_str(item, "security", default="reality"),
        flow=_optional_str(item, "flow", default="xtls-rprx-vision"),
        fingerprint=_optional_str(item, "fingerprint", default="firefox"),
        sni=_optional_str(item, "sni", default="www.google.com"),
        short_id=_optional_str(item, "short_id", default=""),
        spider_x=_optional_str(item, "spider_x", default="/"),
        secret_ref=_require_str(item, "secret_ref"),
    )


def load_server_nodes(path: str | None = None) -> list[ServerNode]:
    registry_path = path or os.getenv("SERVER_REGISTRY_PATH", DEFAULT_SERVER_REGISTRY_PATH)
    data = _load_json_file(registry_path)

    raw_servers = data.get("servers")

    if not isinstance(raw_servers, list):
        raise ServerRegistryError("Server registry must contain a 'servers' list")

    nodes = [_build_server_node(item) for item in raw_servers]

    codes = [node.code for node in nodes]
    duplicate_codes = sorted({code for code in codes if codes.count(code) > 1})

    if duplicate_codes:
        raise ServerRegistryError(f"Duplicate server code(s): {', '.join(duplicate_codes)}")

    display_names = [node.display_name for node in nodes]
    duplicate_display_names = sorted({name for name in display_names if display_names.count(name) > 1})

    if duplicate_display_names:
        raise ServerRegistryError(f"Duplicate server display_name(s): {', '.join(duplicate_display_names)}")

    return sorted(nodes, key=lambda node: (-node.priority, node.code))


def load_enabled_server_nodes(path: str | None = None) -> list[ServerNode]:
    return [node for node in load_server_nodes(path) if node.enabled]


def get_server_node(code: str, path: str | None = None) -> ServerNode:
    for node in load_server_nodes(path):
        if node.code == code:
            return node

    raise ServerRegistryError(f"Server not found: {code}")


def load_panel_credentials(
    server: ServerNode,
    secrets_path: str | None = None,
) -> PanelCredentials:
    path = secrets_path or os.getenv("SERVER_SECRETS_PATH", DEFAULT_SERVER_SECRETS_PATH)
    values = _load_env_file(path)

    username_key = f"{server.secret_ref}_PANEL_USERNAME"
    password_key = f"{server.secret_ref}_PANEL_PASSWORD"

    username = values.get(username_key, "").strip()
    password = values.get(password_key, "").strip()

    if not username:
        raise ServerRegistryError(f"Missing secret: {username_key}")

    if not password:
        raise ServerRegistryError(f"Missing secret: {password_key}")

    return PanelCredentials(username=username, password=password)


def get_enabled_direct_cidrs(path: str | None = None) -> list[str]:
    return [node.direct_cidr for node in load_enabled_server_nodes(path)]
