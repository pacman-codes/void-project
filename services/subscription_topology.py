from __future__ import annotations


CURRENT_SUBSCRIPTION_SERVER_CODES = (
    "prod_1",
    "netherlands_1",
)
CURRENT_SUBSCRIPTION_SERVER_CODE_SET = frozenset(CURRENT_SUBSCRIPTION_SERVER_CODES)

VLESS_TECHNICAL_DEVICE_NUMBERS = {
    "prod_1": 104,
    "netherlands_1": 102,
}
HY2_TECHNICAL_DEVICE_NUMBERS = {
    "prod_1": 9003,
    "netherlands_1": 9002,
}

VLESS_TECHNICAL_DEVICE_MIN = 100
HY2_TECHNICAL_DEVICE_MIN = 9000


def get_vless_device_number(server_code: str) -> int:
    try:
        return VLESS_TECHNICAL_DEVICE_NUMBERS[server_code]
    except KeyError as exc:
        raise ValueError(f"Unsupported subscription server: {server_code}") from exc


def get_hy2_device_number(server_code: str) -> int:
    try:
        return HY2_TECHNICAL_DEVICE_NUMBERS[server_code]
    except KeyError as exc:
        raise ValueError(f"Unsupported subscription server: {server_code}") from exc
