from __future__ import annotations


CURRENT_SUBSCRIPTION_SERVER_CODES = (
    "prod_1",
    "netherlands_1",
    "node3",
)

VLESS_TECHNICAL_DEVICE_NUMBERS = {
    "prod_1": 104,
    "netherlands_1": 102,
    "node3": 105,
}
HY2_TECHNICAL_DEVICE_NUMBERS = {
    "prod_1": 9003,
    "netherlands_1": 9002,
    "node3": 9005,
}


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
