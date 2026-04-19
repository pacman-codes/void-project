import os


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


APP_ENV = os.getenv("APP_ENV", "dev").strip().lower()
DEV_MODE = _to_bool(os.getenv("DEV_MODE"), default=(APP_ENV != "prod"))
PANEL_ENABLED = _to_bool(os.getenv("PANEL_ENABLED"), default=(APP_ENV == "prod"))
