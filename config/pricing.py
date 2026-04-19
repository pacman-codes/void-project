import os


def as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


FREE_TRAFFIC_LIMIT_MB = as_int(os.getenv("FREE_TRAFFIC_LIMIT_MB"), 3072)

PAID_PRICE_1M_RUB = as_int(os.getenv("PAID_PRICE_1M_RUB"), 249)
PAID_DISCOUNT_6M_PERCENT = as_int(os.getenv("PAID_DISCOUNT_6M_PERCENT"), 15)
PAID_DISCOUNT_12M_PERCENT = as_int(os.getenv("PAID_DISCOUNT_12M_PERCENT"), 35)

LAUNCH_OFFER_LIMIT_USERS = as_int(os.getenv("LAUNCH_OFFER_LIMIT_USERS"), 10)
LAUNCH_OFFER_PRICE_1M_RUB = as_int(os.getenv("LAUNCH_OFFER_PRICE_1M_RUB"), 100)
LAUNCH_OFFER_PRICE_6M_RUB = as_int(os.getenv("LAUNCH_OFFER_PRICE_6M_RUB"), 600)
LAUNCH_OFFER_PRICE_12M_RUB = as_int(os.getenv("LAUNCH_OFFER_PRICE_12M_RUB"), 1200)
