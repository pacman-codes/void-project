import os

from config.config import settings  # noqa: F401


def as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


ENABLE_REFERRAL = as_bool(os.getenv("ENABLE_REFERRAL"), default=False)
ENABLE_LAUNCH_OFFER = as_bool(os.getenv("ENABLE_LAUNCH_OFFER"), default=True)
