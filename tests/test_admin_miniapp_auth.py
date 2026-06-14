from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from urllib.parse import urlencode

from config.config import settings
from services.admin_miniapp_auth import (
    AdminMiniAppAuthError,
    authenticate_admin_init_data,
    parse_admin_miniapp_telegram_ids,
    verify_telegram_webapp_init_data,
)


BOT_TOKEN = "123456:test-token"


def build_signed_init_data(fields: dict[str, str]) -> str:
    data_check_string = "\n".join(
        sorted(f"{key}={value}" for key, value in fields.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return urlencode({**fields, "hash": signature})


class AdminMiniAppAuthTests(unittest.TestCase):
    def test_verify_valid_init_data(self) -> None:
        init_data = build_signed_init_data(
            {
                "auth_date": "1000",
                "query_id": "abc",
                "user": json.dumps({"id": 42, "username": "owner"}, separators=(",", ":")),
            }
        )

        values = verify_telegram_webapp_init_data(
            init_data,
            bot_token=BOT_TOKEN,
            max_age_seconds=60,
            now_seconds=1010,
        )

        self.assertEqual(values["auth_date"], "1000")
        self.assertIn('"id":42', values["user"])

    def test_verify_rejects_invalid_signature(self) -> None:
        init_data = build_signed_init_data(
            {
                "auth_date": "1000",
                "user": json.dumps({"id": 42}, separators=(",", ":")),
            }
        )

        with self.assertRaises(AdminMiniAppAuthError) as context:
            verify_telegram_webapp_init_data(
                init_data + "x",
                bot_token=BOT_TOKEN,
                max_age_seconds=60,
                now_seconds=1010,
            )

        self.assertEqual(context.exception.code, "invalid_signature")

    def test_verify_rejects_stale_init_data(self) -> None:
        init_data = build_signed_init_data(
            {
                "auth_date": "1000",
                "user": json.dumps({"id": 42}, separators=(",", ":")),
            }
        )

        with self.assertRaises(AdminMiniAppAuthError) as context:
            verify_telegram_webapp_init_data(
                init_data,
                bot_token=BOT_TOKEN,
                max_age_seconds=60,
                now_seconds=2000,
            )

        self.assertEqual(context.exception.code, "stale_init_data")

    def test_verify_rejects_missing_auth_date(self) -> None:
        init_data = build_signed_init_data(
            {
                "user": json.dumps({"id": 42}, separators=(",", ":")),
            }
        )

        with self.assertRaises(AdminMiniAppAuthError) as context:
            verify_telegram_webapp_init_data(
                init_data,
                bot_token=BOT_TOKEN,
                max_age_seconds=60,
                now_seconds=1010,
            )

        self.assertEqual(context.exception.code, "missing_auth_date")

    def test_parse_allowlist_uses_numeric_ids_only(self) -> None:
        self.assertEqual(
            parse_admin_miniapp_telegram_ids("1, 2;bad; 3"),
            {1, 2, 3},
        )

    def test_authenticate_requires_allowlisted_telegram_id(self) -> None:
        old_bot_token = settings.BOT_TOKEN
        old_allowlist = settings.ADMIN_MINIAPP_TELEGRAM_IDS
        old_max_age = settings.ADMIN_MINIAPP_INITDATA_MAX_AGE_SECONDS

        try:
            settings.BOT_TOKEN = BOT_TOKEN
            settings.ADMIN_MINIAPP_INITDATA_MAX_AGE_SECONDS = 0

            init_data = build_signed_init_data(
                {
                    "auth_date": "1000",
                    "user": json.dumps(
                        {"id": 42, "username": "owner"},
                        separators=(",", ":"),
                    ),
                }
            )

            settings.ADMIN_MINIAPP_TELEGRAM_IDS = "42"
            identity = authenticate_admin_init_data(init_data)
            self.assertEqual(identity.telegram_id, 42)

            settings.ADMIN_MINIAPP_TELEGRAM_IDS = "43"
            with self.assertRaises(AdminMiniAppAuthError) as context:
                authenticate_admin_init_data(init_data)
            self.assertEqual(context.exception.status, 403)
        finally:
            settings.BOT_TOKEN = old_bot_token
            settings.ADMIN_MINIAPP_TELEGRAM_IDS = old_allowlist
            settings.ADMIN_MINIAPP_INITDATA_MAX_AGE_SECONDS = old_max_age


if __name__ == "__main__":
    unittest.main()
