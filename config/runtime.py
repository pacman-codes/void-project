import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
ENV_DEV_FILE = BASE_DIR / ".env.dev"


def _load_runtime_env() -> None:
    # PROD must not silently become DEV just because runtime.py was imported first.
    if ENV_DEV_FILE.exists():
        load_dotenv(ENV_DEV_FILE, override=True)
    else:
        load_dotenv(ENV_FILE, override=True)


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


_load_runtime_env()

APP_ENV = os.getenv("APP_ENV", "dev").strip().lower()
DEV_MODE = _to_bool(os.getenv("DEV_MODE"), default=(APP_ENV != "prod"))
PANEL_ENABLED = _to_bool(os.getenv("PANEL_ENABLED"), default=(APP_ENV == "prod"))

if APP_ENV == "prod" and DEV_MODE:
    raise RuntimeError("Unsafe config: APP_ENV=prod but DEV_MODE=true")

if APP_ENV == "prod" and not PANEL_ENABLED:
    raise RuntimeError("Unsafe config: APP_ENV=prod but PANEL_ENABLED=false")
