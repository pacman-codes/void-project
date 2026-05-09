from __future__ import annotations

import json
import secrets
import string
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote

import httpx

from config.config import config


class PanelClientError(Exception):
    """Базовая ошибка клиента панели."""


class PanelAuthError(PanelClientError):
    """Ошибка авторизации."""


class PanelRequestError(PanelClientError):
    """Ошибка запроса к панели."""


@dataclass
class InboundClient:
    id: str
    email: str
    enable: bool
    flow: str
    limit_ip: int
    total_gb_bytes: int
    expiry_time_ms: int
    tg_id: str
    sub_id: str
    comment: str = ""
    reset: int = 0
    created_at: int = 0
    updated_at: int = 0


@dataclass
class InboundInfo:
    id: int
    remark: str
    protocol: str
    port: int
    enable: bool
    tag: str
    raw: dict[str, Any]
    settings: dict[str, Any]
    stream_settings: dict[str, Any]
    sniffing: dict[str, Any]
    clients: list[InboundClient]


class PanelClient:
    def __init__(self) -> None:
        self.origin = config.panel_origin
        self.base_path = config.panel_path
        self.username = config.panel_username
        self.password = config.panel_password
        self.verify_ssl = config.panel_verify_ssl
        self.timeout = config.panel_timeout

        if not self.origin:
            raise PanelClientError("Не задан PANEL_ORIGIN в .env")

        if not self.base_path:
            raise PanelClientError("Не задан PANEL_PATH в .env")

        if not self.username:
            raise PanelClientError("Не задан PANEL_USERNAME в .env")

        if not self.password:
            raise PanelClientError("Не задан PANEL_PASSWORD в .env")

    @property
    def base_url(self) -> str:
        return f"{self.origin}{self.base_path}"

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self.base_url}{path}"

    async def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            verify=self.verify_ssl,
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "telegram-bot-panel-client/1.0",
                "Accept": "application/json, text/plain, */*",
            },
        )

    @staticmethod
    def _parse_json_field(value: Any, field_name: str) -> dict[str, Any]:
        if value is None:
            return {}

        if isinstance(value, dict):
            return value

        if isinstance(value, str):
            value = value.strip()
            if not value:
                return {}
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise PanelRequestError(
                    f"Поле {field_name} содержит невалидный JSON: {value[:300]}"
                ) from exc

            if not isinstance(parsed, dict):
                raise PanelRequestError(
                    f"Поле {field_name} распарсилось, но результат не dict: {type(parsed)}"
                )
            return parsed

        raise PanelRequestError(
            f"Поле {field_name} имеет неожиданный тип: {type(value)}"
        )

    @staticmethod
    def _generate_sub_id(length: int = 16) -> str:
        alphabet = string.ascii_lowercase + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    @staticmethod
    def _total_gb_to_bytes(total_gb: int) -> int:
        if total_gb <= 0:
            return 0
        return total_gb * 1024 * 1024 * 1024

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self._url(path)

        try:
            response = await client.request(
                method=method,
                url=url,
                json=json_data,
            )
        except httpx.HTTPError as exc:
            raise PanelRequestError(f"Ошибка сети при запросе {url}: {exc}") from exc

        if response.status_code != 200:
            raise PanelRequestError(
                f"Панель вернула HTTP {response.status_code} для {url}. "
                f"Body: {response.text[:500]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise PanelRequestError(
                f"Ответ панели не JSON для {url}: {response.text[:500]}"
            ) from exc

        if not isinstance(data, dict):
            raise PanelRequestError(
                f"Ответ панели имеет неожиданный тип для {url}: {type(data)}"
            )

        return data

    async def _get_two_factor_enabled_with_client(self, client: httpx.AsyncClient) -> bool:
        data = await self._request_json(
            client,
            "POST",
            "/getTwoFactorEnable",
            json_data={},
        )

        if not data.get("success"):
            raise PanelRequestError(
                f"Панель вернула success=false при проверке двухфакторки: {data}"
            )

        return bool(data.get("obj"))

    async def get_two_factor_enabled(self) -> bool:
        async with await self._build_client() as client:
            return await self._get_two_factor_enabled_with_client(client)

    async def login(self) -> httpx.AsyncClient:
        client = await self._build_client()

        try:
            two_factor_enabled = await self._get_two_factor_enabled_with_client(client)
            if two_factor_enabled:
                await client.aclose()
                raise PanelAuthError(
                    "В панели включена двухфакторная авторизация. "
                    "На текущем шаге код работает только без 2FA."
                )

            data = await self._request_json(
                client,
                "POST",
                "/login",
                json_data={
                    "username": self.username,
                    "password": self.password,
                    "twoFactorCode": "",
                },
            )

            if not data.get("success"):
                await client.aclose()
                raise PanelAuthError(f"Логин неуспешен: {data}")

            return client

        except Exception:
            await client.aclose()
            raise

    async def get_inbound_raw(self, inbound_id: int) -> dict[str, Any]:
        client = await self.login()
        try:
            data = await self._request_json(
                client,
                "GET",
                f"/panel/api/inbounds/get/{inbound_id}",
            )
        finally:
            await client.aclose()

        if not data.get("success"):
            raise PanelRequestError(f"Панель вернула success=false: {data}")

        obj = data.get("obj")
        if not isinstance(obj, dict):
            raise PanelRequestError(f"Поле obj отсутствует или не dict: {data}")

        return obj

    def _build_inbound_client(self, raw_client: dict[str, Any]) -> InboundClient:
        return InboundClient(
            id=str(raw_client.get("id", "")),
            email=str(raw_client.get("email", "")),
            enable=bool(raw_client.get("enable", True)),
            flow=str(raw_client.get("flow", "")),
            limit_ip=int(raw_client.get("limitIp", 0) or 0),
            total_gb_bytes=int(raw_client.get("totalGB", 0) or 0),
            expiry_time_ms=int(raw_client.get("expiryTime", 0) or 0),
            tg_id=str(raw_client.get("tgId", "")),
            sub_id=str(raw_client.get("subId", "")),
            comment=str(raw_client.get("comment", "")),
            reset=int(raw_client.get("reset", 0) or 0),
            created_at=int(raw_client.get("created_at", 0) or 0),
            updated_at=int(raw_client.get("updated_at", 0) or 0),
        )

    async def get_inbound_info(self, inbound_id: int) -> InboundInfo:
        raw = await self.get_inbound_raw(inbound_id)

        settings = self._parse_json_field(raw.get("settings"), "settings")
        stream_settings = self._parse_json_field(raw.get("streamSettings"), "streamSettings")
        sniffing = self._parse_json_field(raw.get("sniffing"), "sniffing")

        raw_clients = settings.get("clients", [])
        if raw_clients is None:
            raw_clients = []

        if not isinstance(raw_clients, list):
            raise PanelRequestError("settings.clients должен быть списком")

        clients = [
            self._build_inbound_client(item)
            for item in raw_clients
            if isinstance(item, dict)
        ]

        return InboundInfo(
            id=int(raw.get("id")),
            remark=str(raw.get("remark", "")),
            protocol=str(raw.get("protocol", "")),
            port=int(raw.get("port", 0) or 0),
            enable=bool(raw.get("enable", True)),
            tag=str(raw.get("tag", "")),
            raw=raw,
            settings=settings,
            stream_settings=stream_settings,
            sniffing=sniffing,
            clients=clients,
        )

    async def get_inbound(self, inbound_id: int) -> dict[str, Any]:
        info = await self.get_inbound_info(inbound_id)
        return {
            "id": info.id,
            "remark": info.remark,
            "protocol": info.protocol,
            "port": info.port,
            "enable": info.enable,
            "tag": info.tag,
            "settings": info.settings,
            "stream_settings": info.stream_settings,
            "sniffing": info.sniffing,
            "clients": [asdict(client) for client in info.clients],
            "raw": info.raw,
        }

    async def get_client_by_email(self, inbound_id: int, email: str) -> dict[str, Any] | None:
        inbound = await self.get_inbound_info(inbound_id)

        for client in inbound.clients:
            if client.email == email:
                return asdict(client)

        return None

    async def get_client_traffic_by_email(self, email: str) -> dict[str, Any]:
        if not email:
            raise PanelRequestError("email пустой, получить traffic невозможно")

        client = await self.login()
        try:
            data = await self._request_json(
                client,
                "GET",
                f"/panel/api/inbounds/getClientTraffics/{quote(email, safe='')}",
            )
        finally:
            await client.aclose()

        if not data.get("success"):
            raise PanelRequestError(
                f"Панель вернула success=false при getClientTraffics для {email}: {data}"
            )

        obj = data.get("obj")
        if not isinstance(obj, dict):
            raise PanelRequestError(
                f"Поле obj отсутствует или не dict при getClientTraffics для {email}: {data}"
            )

        return obj

    async def get_client_traffic_by_uuid(self, client_uuid: str) -> list[dict[str, Any]]:
        if not client_uuid:
            raise PanelRequestError("client_uuid пустой, получить traffic невозможно")

        client = await self.login()
        try:
            data = await self._request_json(
                client,
                "GET",
                f"/panel/api/inbounds/getClientTrafficsById/{quote(client_uuid, safe='')}",
            )
        finally:
            await client.aclose()

        if not data.get("success"):
            raise PanelRequestError(
                f"Панель вернула success=false при getClientTrafficsById для {client_uuid}: {data}"
            )

        obj = data.get("obj")
        if isinstance(obj, list):
            return [item for item in obj if isinstance(item, dict)]

        if isinstance(obj, dict):
            return [obj]

        return []


    async def add_client(
        self,
        inbound_id: int,
        client_id: str,
        email: str,
        *,
        total_gb: int = 0,
        expiry_time_ms: int = 0,
        limit_ip: int = 0,
        flow: str = "",
        enable: bool = True,
        tg_id: str = "",
        sub_id: str | None = None,
        comment: str = "",
    ) -> dict[str, Any]:
        existing = await self.get_client_by_email(inbound_id, email)
        if existing is not None:
            raise PanelRequestError(
                f"Клиент с email '{email}' уже существует в inbound {inbound_id}"
            )

        if sub_id is None:
            sub_id = self._generate_sub_id()

        client_payload = {
            "id": client_id,
            "email": email,
            "limitIp": limit_ip,
            "totalGB": self._total_gb_to_bytes(total_gb),
            "expiryTime": expiry_time_ms,
            "enable": enable,
            "tgId": tg_id,
            "subId": sub_id,
            "flow": flow,
            "comment": comment,
            "reset": 0,
        }

        payload = {
            "id": inbound_id,
            "settings": json.dumps(
                {"clients": [client_payload]},
                ensure_ascii=False,
            ),
        }

        client = await self.login()
        try:
            data = await self._request_json(
                client,
                "POST",
                "/panel/api/inbounds/addClient",
                json_data=payload,
            )
        finally:
            await client.aclose()

        if not data.get("success"):
            raise PanelRequestError(f"Панель вернула success=false при addClient: {data}")

        created = await self.get_client_by_email(inbound_id, email)
        if created is None:
            raise PanelRequestError(
                "Панель ответила success=true, но созданный клиент не найден повторным чтением inbound"
            )

        return {
            "success": True,
            "message": data.get("msg", ""),
            "client": created,
        }

    async def delete_client(self, inbound_id: int, client_id: str) -> dict[str, Any]:
        if not client_id:
            raise PanelRequestError("client_id пустой, удаление клиента невозможно")

        last_error: Exception | None = None

        for method in ("POST", "DELETE"):
            client = await self.login()
            try:
                data = await self._request_json(
                    client,
                    method,
                    f"/panel/api/inbounds/{inbound_id}/delClient/{client_id}",
                )
            except PanelRequestError as exc:
                last_error = exc
                continue
            finally:
                await client.aclose()

            if not data.get("success"):
                raise PanelRequestError(
                    f"Панель вернула success=false при удалении клиента {client_id}: {data}"
                )

            return {
                "success": True,
                "message": data.get("msg", ""),
                "client_id": client_id,
            }

        raise PanelRequestError(
            f"Не удалось удалить клиента {client_id} из inbound {inbound_id}: {last_error}"
        )

    async def debug_probe(self, inbound_id: int) -> dict[str, Any]:
        result: dict[str, Any] = {
            "success": False,
            "base_url": self.base_url,
            "two_factor_enabled": None,
            "login_ok": False,
            "inbound_ok": False,
            "inbound_id": inbound_id,
            "message": "",
            "inbound_preview": None,
        }

        try:
            two_factor_enabled = await self.get_two_factor_enabled()
            result["two_factor_enabled"] = two_factor_enabled

            client = await self.login()
            result["login_ok"] = True

            try:
                data = await self._request_json(
                    client,
                    "GET",
                    f"/panel/api/inbounds/get/{inbound_id}",
                )
            finally:
                await client.aclose()

            if data.get("success") is True:
                result["success"] = True
                result["inbound_ok"] = True
                result["message"] = "Соединение с панелью работает, логин успешен, inbound получен."
                result["inbound_preview"] = data.get("obj")
                return result

            result["message"] = "Логин успешен, но inbound не получен."
            result["inbound_preview"] = data
            return result

        except Exception as exc:
            result["message"] = str(exc)
            return result
