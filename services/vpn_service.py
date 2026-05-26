import os
import uuid
from urllib.parse import quote, urlparse

from sqlalchemy import func, select

from config.config import config
from db.database import async_session_maker
from db.models import User, VPNAccess
from services.panel_client import PanelClient

from config.runtime import DEV_MODE, PANEL_ENABLED


MAIN_INBOUND_ID = 8  # fallback; PANEL_INBOUND_ID env override is used by VPNService
MIGRATION_INBOUND_ID = 9
MIGRATION_SERVER_NAME = "migration-8449"


class VPNServiceError(Exception):
    """Ошибка сервиса выдачи доступа."""


class VPNService:
    def __init__(self) -> None:
        self.panel_client: PanelClient | None = None
        # PANEL_INBOUND_ID env override.
        self.inbound_id = int(os.getenv("PANEL_INBOUND_ID", str(MAIN_INBOUND_ID)))
        self.server_name = "main"

    def _get_panel_client(self) -> PanelClient:
        if self.panel_client is None:
            self.panel_client = PanelClient()
        return self.panel_client

    def _build_fake_config_url(self, telegram_id: int, device_number: int, client_id: str) -> str:
        return (
            f"vless://{client_id}@dev.local:443"
            f"?type=tcp&encryption=none&security=reality"
            f"&pbk=DEV_PUBLIC_KEY"
            f"&fp=chrome"
            f"&sni=dev.local"
            f"&sid=dev{device_number}"
            f"&spx=%2F"
            f"#main-user_{telegram_id}_{device_number}"
        )

    def _extract_panel_host(self) -> str:
        raw_origin = (config.panel_origin or "").strip()
        if not raw_origin:
            raise VPNServiceError("PANEL_ORIGIN пустой")

        origin_for_parse = raw_origin
        if "://" not in origin_for_parse:
            origin_for_parse = f"https://{origin_for_parse}"

        parsed = urlparse(origin_for_parse)
        host = (parsed.hostname or "").strip()

        if not host:
            raise VPNServiceError(
                f"Не удалось определить hostname из PANEL_ORIGIN: {config.panel_origin}"
            )

        return host

    def _build_config_url(self, inbound: dict, client: dict) -> str:
        protocol = inbound.get("protocol", "")
        if protocol != "vless":
            raise VPNServiceError(f"Сейчас поддерживается только protocol=vless, получено: {protocol}")

        port = inbound.get("port")
        if not port:
            raise VPNServiceError("В inbound нет port")

        client_id = client.get("id")
        if not client_id:
            raise VPNServiceError("У клиента нет id")

        stream_settings = inbound.get("stream_settings", {})
        if not isinstance(stream_settings, dict):
            raise VPNServiceError("stream_settings должен быть dict")

        reality_settings = stream_settings.get("realitySettings", {})
        if not isinstance(reality_settings, dict):
            raise VPNServiceError("realitySettings должен быть dict")

        reality_inner_settings = reality_settings.get("settings", {})
        if not isinstance(reality_inner_settings, dict):
            raise VPNServiceError("realitySettings.settings должен быть dict")

        public_key = reality_inner_settings.get("publicKey", "")
        if not public_key:
            raise VPNServiceError("Не найден publicKey в inbound")

        fingerprint = reality_inner_settings.get("fingerprint", "chrome") or "chrome"

        server_name = reality_inner_settings.get("serverName", "")
        if not server_name:
            server_names = reality_settings.get("serverNames", [])
            if isinstance(server_names, list) and server_names:
                server_name = str(server_names[0])

        if not server_name:
            raise VPNServiceError("Не найден serverName / serverNames в inbound")

        short_ids = reality_settings.get("shortIds", [])
        short_id = os.getenv("PANEL_REALITY_SHORT_ID", "").strip()
        if not short_id and isinstance(short_ids, list) and short_ids:
            # 3x-ui subscription export uses the last generated shortId.
            short_id = str(short_ids[-1])

        spider_x = (
            os.getenv("PANEL_REALITY_SPIDER_X", "").strip()
            or reality_inner_settings.get("spiderX")
            or reality_settings.get("spiderX")
            or "/"
        )

        network = stream_settings.get("network", "tcp") or "tcp"
        security = stream_settings.get("security", "reality") or "reality"

        if security != "reality":
            raise VPNServiceError(f"Сейчас поддерживается только security=reality, получено: {security}")

        address = self._extract_panel_host()

        email = client.get("email", "access")
        tag = quote(f"{self.server_name}-{email}")

        query_parts = [
            f"type={quote(str(network))}",
            "encryption=none",
            f"security={quote(str(security))}",
            f"pbk={quote(str(public_key))}",
            f"fp={quote(str(fingerprint))}",
            f"sni={quote(str(server_name))}",
            f"sid={quote(str(short_id))}",
            f"spx={quote(str(spider_x), safe='/')}",
        ]

        config_url = f"vless://{client_id}@{address}:{port}?{'&'.join(query_parts)}#{tag}"
        return config_url

    async def create_vpn_user(
        self,
        telegram_id: int,
        device_number: int,
        email: str | None = None,
    ) -> dict:
        email = email or f"user_{telegram_id}_{device_number}"

        if DEV_MODE:
            if not PANEL_ENABLED:
                client_id = str(uuid.uuid4())
                fake_client = {
                    "id": client_id,
                    "email": email,
                }
                config_url = self._build_fake_config_url(
                    telegram_id=telegram_id,
                    device_number=device_number,
                    client_id=client_id,
                )
                return {
                    "created": True,
                    "client": fake_client,
                    "config_url": config_url,
                }
        elif not PANEL_ENABLED:
            raise VPNServiceError("PANEL_ENABLED=False в non-DEV окружении: выдача fake key запрещена")

        existing_client = await self._get_panel_client().get_client_by_email(
            inbound_id=self.inbound_id,
            email=email,
        )

        if existing_client is not None:
            if not bool(existing_client.get("enable", True)):
                updated_result = await self._get_panel_client().update_client_enable(
                    inbound_id=self.inbound_id,
                    client_id=str(existing_client["id"]),
                    enable=True,
                )
                updated_client = updated_result.get("client")
                if updated_client is not None:
                    existing_client = updated_client

            inbound = await self._get_panel_client().get_inbound(self.inbound_id)
            config_url = self._build_config_url(inbound, existing_client)

            return {
                "created": False,
                "client": existing_client,
                "config_url": config_url,
            }

        created_result = await self._get_panel_client().add_client(
            inbound_id=self.inbound_id,
            client_id=str(uuid.uuid4()),
            email=email,
            total_gb=0,
            expiry_time_ms=0,
            limit_ip=0,
            flow="",
            enable=True,
            tg_id=str(telegram_id),
            comment=f"telegram user {telegram_id} device {device_number}",
        )

        client = created_result.get("client")
        if client is None:
            raise VPNServiceError("Клиент был создан, но не вернулся из panel_client")

        inbound = await self._get_panel_client().get_inbound(self.inbound_id)
        config_url = self._build_config_url(inbound, client)

        return {
            "created": True,
            "client": client,
            "config_url": config_url,
        }

    async def _count_user_devices(self, session, user_id: int) -> int:
        result = await session.execute(
            select(func.count(VPNAccess.id)).where(
                VPNAccess.user_id == user_id,
                VPNAccess.is_active.is_(True),
            )
        )
        return int(result.scalar() or 0)

    async def _ensure_slot_record(
        self,
        session,
        user: User,
        device_number: int,
        device_name: str | None = None,
        email: str | None = None,
    ) -> dict:
        panel_result = await self.create_vpn_user(
            user.telegram_id,
            device_number,
            email=email,
        )
        client = panel_result["client"]
        config_url = panel_result["config_url"]

        access_result = await session.execute(
            select(VPNAccess).where(
                VPNAccess.user_id == user.id,
                VPNAccess.device_number == device_number,
            )
        )
        access = access_result.scalar_one_or_none()

        if access is None:
            access = VPNAccess(
                user_id=user.id,
                server_name=self.server_name if not DEV_MODE else "dev",
                external_id=client["email"],
                client_uuid=client["id"],
                config_url=config_url,
                is_active=True,
                device_number=device_number,
                device_name=device_name or f"Устройство {device_number}",
            )
            session.add(access)
        else:
            access.server_name = self.server_name if not DEV_MODE else "dev"
            access.external_id = client["email"]
            access.client_uuid = client["id"]
            access.config_url = config_url
            access.is_active = True
            access.device_number = device_number
            if device_name:
                access.device_name = device_name

        return {
            "created_in_panel": panel_result["created"],
            "external_id": client["email"],
            "client_uuid": client["id"],
            "config_url": config_url,
        }

    async def ensure_vpn_access_record(
        self,
        telegram_id: int,
        device_number: int = 1,
        device_name: str | None = None,
    ) -> dict:
        async with async_session_maker() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = user_result.scalar_one_or_none()

            if user is None:
                raise VPNServiceError(f"Пользователь с telegram_id={telegram_id} не найден в БД")

            if user.device_limit is None or user.device_limit <= 0:
                user.device_limit = 1

            if device_number > user.device_limit:
                raise VPNServiceError("Лимит устройств для этого тарифа исчерпан")

            slot_result = await self._ensure_slot_record(
                session=session,
                user=user,
                device_number=device_number,
                device_name=device_name,
            )

            actual_used_devices = await self._count_user_devices(session, user.id)
            user.used_devices = max(user.used_devices or 0, actual_used_devices)

            await session.commit()

            return {
                "user_id": user.id,
                "device_number": device_number,
                "device_limit": user.device_limit,
                "used_devices": user.used_devices,
                "external_id": slot_result["external_id"],
                "client_uuid": slot_result["client_uuid"],
                "config_url": slot_result["config_url"],
                "created_in_panel": slot_result["created_in_panel"],
                "is_active": True,
            }

    async def create_next_device_access(
        self,
        telegram_id: int,
        device_name: str | None = None,
    ) -> dict:
        async with async_session_maker() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = user_result.scalar_one_or_none()

            if user is None:
                raise VPNServiceError(f"Пользователь с telegram_id={telegram_id} не найден в БД")

            if user.device_limit is None or user.device_limit <= 0:
                user.device_limit = 1

            current_used_devices = await self._count_user_devices(session, user.id)

            if current_used_devices >= user.device_limit:
                raise VPNServiceError(
                    f"Лимит устройств исчерпан: {current_used_devices} из {user.device_limit}"
                )

            next_device_number = current_used_devices + 1

            slot_result = await self._ensure_slot_record(
                session=session,
                user=user,
                device_number=next_device_number,
                device_name=device_name,
            )

            user.used_devices = next_device_number
            await session.commit()

            return {
                "user_id": user.id,
                "device_number": next_device_number,
                "device_limit": user.device_limit,
                "used_devices": user.used_devices,
                "external_id": slot_result["external_id"],
                "client_uuid": slot_result["client_uuid"],
                "config_url": slot_result["config_url"],
                "created_in_panel": slot_result["created_in_panel"],
                "is_active": True,
            }

    async def regenerate_vpn_access_record(
        self,
        telegram_id: int,
        device_number: int = 1,
        device_name: str | None = None,
    ) -> dict:
        async with async_session_maker() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = user_result.scalar_one_or_none()

            if user is None:
                raise VPNServiceError(f"Пользователь с telegram_id={telegram_id} не найден в БД")

            if user.device_limit is None or user.device_limit <= 0:
                user.device_limit = 1

            if device_number > user.device_limit:
                raise VPNServiceError("Лимит устройств для этого тарифа исчерпан")

            access_result = await session.execute(
                select(VPNAccess).where(
                    VPNAccess.user_id == user.id,
                    VPNAccess.device_number == device_number,
                )
            )
            access = access_result.scalar_one_or_none()

            old_client_uuid = access.client_uuid if access is not None else ""

            if old_client_uuid and not DEV_MODE:
                await self._get_panel_client().delete_client(
                    inbound_id=self.inbound_id,
                    client_id=old_client_uuid,
                )

            if access is not None:
                await session.delete(access)
                await session.flush()

            unique_email = f"user_{telegram_id}_{device_number}_regen_{uuid.uuid4().hex[:8]}"

            slot_result = await self._ensure_slot_record(
                session=session,
                user=user,
                device_number=device_number,
                device_name=device_name or f"Устройство {device_number}",
                email=unique_email,
            )

            actual_used_devices = await self._count_user_devices(session, user.id)
            user.used_devices = max(user.used_devices or 0, actual_used_devices)

            await session.commit()

            return {
                "user_id": user.id,
                "device_number": device_number,
                "device_limit": user.device_limit,
                "used_devices": user.used_devices,
                "external_id": slot_result["external_id"],
                "client_uuid": slot_result["client_uuid"],
                "config_url": slot_result["config_url"],
                "created_in_panel": slot_result["created_in_panel"],
                "is_active": True,
            }

    async def ensure_migration_8449_access_record(
        self,
        telegram_id: int,
        device_number: int = 1,
        device_name: str | None = None,
    ) -> dict:
        """Create or refresh a parallel rescue access on inbound 9 / port 8449.

        This does not delete or disable old 443 access records.
        It is used for soft migration when the user opens the subscription link screen.
        """
        email = f"user_{telegram_id}_{device_number}_m8449"
        db_device_number = 100 + device_number

        old_inbound_id = self.inbound_id
        old_server_name = self.server_name

        try:
            self.inbound_id = MIGRATION_INBOUND_ID
            self.server_name = MIGRATION_SERVER_NAME

            panel_result = await self.create_vpn_user(
                telegram_id=telegram_id,
                device_number=device_number,
                email=email,
            )
        finally:
            self.inbound_id = old_inbound_id
            self.server_name = old_server_name

        client = panel_result["client"]
        config_url = panel_result["config_url"]

        async with async_session_maker() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = user_result.scalar_one_or_none()

            if user is None:
                raise VPNServiceError(f"Пользователь с telegram_id={telegram_id} не найден в БД")

            access_result = await session.execute(
                select(VPNAccess).where(
                    VPNAccess.user_id == user.id,
                    VPNAccess.external_id == email,
                )
            )
            access = access_result.scalar_one_or_none()

            if access is None:
                access = VPNAccess(
                    user_id=user.id,
                    server_name=MIGRATION_SERVER_NAME,
                    external_id=client["email"],
                    client_uuid=client["id"],
                    config_url=config_url,
                    is_active=True,
                    device_number=db_device_number,
                    device_name=device_name or "Новое подключение",
                )
                session.add(access)
            else:
                access.server_name = MIGRATION_SERVER_NAME
                access.external_id = client["email"]
                access.client_uuid = client["id"]
                access.config_url = config_url
                access.is_active = True
                access.device_number = db_device_number
                if device_name:
                    access.device_name = device_name

            await session.commit()

            return {
                "user_id": user.id,
                "device_number": db_device_number,
                "external_id": client["email"],
                "client_uuid": client["id"],
                "config_url": config_url,
                "created_in_panel": panel_result["created"],
                "is_active": True,
            }

    async def get_access_records(self, telegram_id: int) -> list[VPNAccess]:
        async with async_session_maker() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = user_result.scalar_one_or_none()

            if user is None:
                return []

            access_result = await session.execute(
                select(VPNAccess)
                .where(VPNAccess.user_id == user.id)
                .order_by(VPNAccess.device_number.asc())
            )
            return list(access_result.scalars().all())
