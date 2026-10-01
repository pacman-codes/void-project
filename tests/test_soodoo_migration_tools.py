from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "scripts" / "export_soodoo_migration.py"
NOTIFY = ROOT / "scripts" / "notify_soodoo_transition.py"


class SoodooMigrationToolTests(unittest.TestCase):
    def test_export_is_read_only_and_secret_free(self) -> None:
        source = EXPORT.read_text(encoding="utf-8")
        self.assertIn('SET TRANSACTION READ ONLY', source)
        self.assertIn('"telegram_id": int(user.telegram_id)', source)
        self.assertIn('"subscription_expiry": utc_iso(user.subscription_expiry)', source)
        self.assertIn('"device_limit": max(1, int(user.device_limit or 1))', source)
        self.assertIn('"access_type": user.access_type', source)
        self.assertNotIn("VpnAccess", source)
        self.assertNotIn("VPNAccess", source)
        self.assertNotIn("UserSubscriptionLink", source)
        self.assertNotIn("client_uuid", source)
        self.assertNotIn("config_url", source)
        self.assertNotIn("BOT_TOKEN", source)

    def test_export_writes_private_manifest_and_digest(self) -> None:
        source = EXPORT.read_text(encoding="utf-8")
        self.assertIn("0o600", source)
        self.assertIn("hashlib.sha256(raw).hexdigest()", source)
        self.assertIn("MANIFEST_SHA256=", source)
        self.assertIn("SOURCE_USERS=", source)

    def test_export_materializes_orm_values_before_rollback(self) -> None:
        source = EXPORT.read_text(encoding="utf-8")
        build_index = source.index("document = build_document(users, now)")
        rollback_index = source.index("await session.rollback()", build_index)
        self.assertLess(build_index, rollback_index)
        self.assertLess(source.index("ids = [int(user.telegram_id)"), rollback_index)

    def test_notification_defaults_to_dry_run(self) -> None:
        source = NOTIFY.read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--send", action="store_true")', source)
        self.assertIn('if not args.send:', source)
        self.assertIn('SEND_EXECUTED=no', source)

    def test_notification_requires_exact_message_hash_confirmation(self) -> None:
        source = NOTIFY.read_text(encoding="utf-8")
        self.assertIn("if args.confirm != digest:", source)
        self.assertIn("VOID_NOTIFICATION_FAILED=CONFIRM", source)
        self.assertIn("message_sha256", source)

    def test_notification_is_resumable_and_aggregate_only(self) -> None:
        source = NOTIFY.read_text(encoding="utf-8")
        self.assertIn('if previous in {"delivered", "blocked"}:', source)
        self.assertIn('DELIVERED=', source)
        self.assertIn('BLOCKED=', source)
        self.assertIn('FAILED=', source)
        self.assertIn('PENDING=', source)
        self.assertNotIn("print(telegram_id", source)


if __name__ == "__main__":
    unittest.main()
