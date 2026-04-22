import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
ENV_DEV_FILE = BASE_DIR / ".env.dev"

if ENV_DEV_FILE.exists():
    load_dotenv(ENV_DEV_FILE, override=True)
else:
    load_dotenv(ENV_FILE, override=True)


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    BOT_TOKEN: str
    DATABASE_URL: str

    PANEL_ORIGIN: str
    PANEL_PATH: str
    PANEL_USERNAME: str
    PANEL_PASSWORD: str
    PANEL_VERIFY_SSL: bool
    PANEL_TIMEOUT: float

    YOOKASSA_SHOP_ID: str
    YOOKASSA_SECRET_KEY: str
    YOOKASSA_RETURN_URL: str

    WEBHOOK_HOST: str
    WEBHOOK_PORT: int

    @property
    def bot_token(self) -> str:
        return self.BOT_TOKEN

    @property
    def database_url(self) -> str:
        return self.DATABASE_URL

    @property
    def panel_origin(self) -> str:
        return self.PANEL_ORIGIN

    @property
    def panel_path(self) -> str:
        return self.PANEL_PATH

    @property
    def panel_username(self) -> str:
        return self.PANEL_USERNAME

    @property
    def panel_password(self) -> str:
        return self.PANEL_PASSWORD

    @property
    def panel_verify_ssl(self) -> bool:
        return self.PANEL_VERIFY_SSL

    @property
    def panel_timeout(self) -> float:
        return self.PANEL_TIMEOUT

    @property
    def yookassa_shop_id(self) -> str:
        return self.YOOKASSA_SHOP_ID

    @property
    def yookassa_secret_key(self) -> str:
        return self.YOOKASSA_SECRET_KEY

    @property
    def yookassa_return_url(self) -> str:
        return self.YOOKASSA_RETURN_URL

    @property
    def webhook_host(self) -> str:
        return self.WEBHOOK_HOST

    @property
    def webhook_port(self) -> int:
        return self.WEBHOOK_PORT


def load_settings() -> Settings:
    panel_path = os.getenv("PANEL_PATH", "").strip()

    if panel_path and not panel_path.startswith("/"):
        panel_path = f"/{panel_path}"

    panel_path = panel_path.rstrip("/")

    return Settings(
        BOT_TOKEN=os.getenv("BOT_TOKEN", "").strip(),
        DATABASE_URL=os.getenv("DATABASE_URL", "").strip(),
        PANEL_ORIGIN=os.getenv("PANEL_ORIGIN", "").strip().rstrip("/"),
        PANEL_PATH=panel_path,
        PANEL_USERNAME=os.getenv("PANEL_USERNAME", "").strip(),
        PANEL_PASSWORD=os.getenv("PANEL_PASSWORD", "").strip(),
        PANEL_VERIFY_SSL=_to_bool(os.getenv("PANEL_VERIFY_SSL"), default=False),
        PANEL_TIMEOUT=float(os.getenv("PANEL_TIMEOUT", "20")),
        YOOKASSA_SHOP_ID=os.getenv("YOOKASSA_SHOP_ID", "").strip(),
        YOOKASSA_SECRET_KEY=os.getenv("YOOKASSA_SECRET_KEY", "").strip(),
        YOOKASSA_RETURN_URL=os.getenv("YOOKASSA_RETURN_URL", "").strip(),
        WEBHOOK_HOST=os.getenv("WEBHOOK_HOST", "127.0.0.1").strip(),
        WEBHOOK_PORT=int(os.getenv("WEBHOOK_PORT", "8081")),
    )


settings = load_settings()
config = settings
