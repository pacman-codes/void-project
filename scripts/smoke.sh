#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/vpn/telegram_bot"
cd "$PROJECT_DIR"

if [ -f "$PROJECT_DIR/venv/bin/activate" ]; then
  source "$PROJECT_DIR/venv/bin/activate"
fi

echo "== 1. Python compile =="
python3 -m py_compile main.py webhook_server.py
python3 -m compileall -q bot services config db scripts

echo "== 2. Critical imports =="
python3 - << 'PY'
import main
import webhook_server

from db.database import async_session_maker
from db.models import User, UserEvent, VPNAccess, UserSubscriptionLink

from services.yookassa_webhook_service import process_yookassa_notification
from services.payment_service import create_redirect_payment, sync_payment_status, clear_user_payment_state
from services.subscription_service import activate_paid_for_user
from services.traffic_service import sync_user_traffic_from_panel
from services.audit_log_service import log_user_event

from bot.handlers.admin_tools import router as admin_router
from bot.handlers.start import router as start_router

print("critical imports ok")
PY

echo "== 3. ENV critical keys =="
python3 - << 'PY'
import os
from pathlib import Path

env_path = Path(".env")
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)

required = [
    "BOT_TOKEN",
    "DATABASE_URL",
    "ADMIN_TELEGRAM_IDS",
    "YOOKASSA_SHOP_ID",
    "YOOKASSA_SECRET_KEY",
    "YOOKASSA_RETURN_URL",
]

missing = [key for key in required if not os.getenv(key)]
if missing:
    raise SystemExit("Missing env keys: " + ", ".join(missing))

print("env ok")
PY

echo "== 4. DB connection and critical tables =="
python3 - << 'PY'
import os
import asyncio
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

env_path = Path(".env")
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)

required_tables = {
    "users",
    "vpn_accesses",
    "user_subscription_links",
    "user_events",
}

async def main():
    engine = create_async_engine(os.getenv("DATABASE_URL"))
    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT current_database(), current_user"))).fetchone()
        print(f"db ok: {row[0]} as {row[1]}")

        rows = await conn.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
        """))
        tables = {r[0] for r in rows.fetchall()}

        missing = sorted(required_tables - tables)
        if missing:
            raise SystemExit("Missing critical tables: " + ", ".join(missing))

        print("critical tables ok")

    await engine.dispose()

asyncio.run(main())
PY

echo "== 5. Alembic status =="
alembic current

echo "== 6. Systemd services =="
systemctl is-active --quiet voidbot
echo "voidbot active"
systemctl is-active --quiet voidbot-webhook
echo "voidbot-webhook active"
systemctl is-active --quiet void-subscription
echo "void-subscription active"

echo "== 7. Webhook local health =="
curl -fsS http://127.0.0.1:8081/health
echo

echo "== 8. Webhook public route =="
code="$(curl -k -s -o /tmp/void_smoke_webhook.out -w '%{http_code}' https://pay.voidmod.space:8443/yookassa/webhook)"
if [ "$code" != "405" ]; then
  echo "Expected 405 for GET /yookassa/webhook, got $code"
  cat /tmp/void_smoke_webhook.out || true
  exit 1
fi
echo "webhook public route ok: HTTP $code"

echo "== 9. Subscription endpoints =="
code="$(curl -k -s -o /tmp/void_smoke_sub_health.out -w '%{http_code}' https://pay.voidmod.space:8443/health)"
if [ "$code" != "200" ]; then
  echo "Expected 200 for public /health, got $code"
  cat /tmp/void_smoke_sub_health.out || true
  exit 1
fi
echo "pay health ok: HTTP $code"

code="$(curl -s -o /tmp/void_smoke_local_sub.out -w '%{http_code}' http://127.0.0.1:8088/sub/__smoke_fake_token__)"
if [ "$code" = "502" ] || [ "$code" = "000" ]; then
  echo "Bad local subscription route /sub/__smoke_fake_token__: HTTP $code"
  cat /tmp/void_smoke_local_sub.out || true
  exit 1
fi
echo "local subscription route reachable: HTTP $code"

for path in "/sub/__smoke_fake_token__" "/happ/__smoke_fake_token__"; do
  code="$(curl -k -s -o /tmp/void_smoke_fake_route.out -w '%{http_code}' "https://pay.voidmod.space:8443${path}")"
  if [ "$code" = "502" ] || [ "$code" = "000" ]; then
    echo "Bad public subscription route ${path}: HTTP $code"
    cat /tmp/void_smoke_fake_route.out || true
    exit 1
  fi
  echo "public subscription route ${path} reachable: HTTP $code"
done

echo "== 10. Business DB checks =="
python3 - << 'PY'
import os
import asyncio
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

env_path = Path(".env")
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)

async def main():
    engine = create_async_engine(os.getenv("DATABASE_URL"))
    async with engine.connect() as conn:
        active_links = await conn.scalar(text("""
            SELECT COUNT(*)
            FROM user_subscription_links
            WHERE is_active IS true
        """))
        print(f"active_subscription_links={active_links}")

        pending_payments = await conn.scalar(text("""
            SELECT COUNT(*)
            FROM users
            WHERE payment_status = 'pending'
              AND payment_id IS NOT NULL
        """))
        print(f"pending_payments={pending_payments}")

        critical_events = await conn.scalar(text("""
            SELECT COUNT(*)
            FROM user_events
            WHERE created_at > (NOW() AT TIME ZONE 'UTC') - INTERVAL '24 hours'
              AND event_type IN (
                'payment_activation_failed',
                'subscription_paid_activation_failed',
                'subscription_expiry_failed'
              )
        """))
        if critical_events and int(critical_events) > 0:
            raise SystemExit(f"Critical payment/subscription events in last 24h: {critical_events}")

        print("business db checks ok")

    await engine.dispose()

asyncio.run(main())
PY

echo "== 10b. External API checks =="
python3 - << 'PY'
import os
import asyncio
from pathlib import Path
import httpx

env_path = Path(".env")
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)

async def main():
    bot_token = os.getenv("BOT_TOKEN")
    yookassa_shop_id = os.getenv("YOOKASSA_SHOP_ID")
    yookassa_secret_key = os.getenv("YOOKASSA_SECRET_KEY")

    async with httpx.AsyncClient(timeout=15.0) as client:
        tg_response = await client.get(f"https://api.telegram.org/bot{bot_token}/getMe")
        if tg_response.status_code != 200:
            raise SystemExit(f"Telegram getMe failed: HTTP {tg_response.status_code}")
        tg_data = tg_response.json()
        if not tg_data.get("ok"):
            raise SystemExit(f"Telegram getMe returned ok=false: {tg_data}")
        username = (tg_data.get("result") or {}).get("username")
        print(f"telegram api ok: @{username}")

        yk_response = await client.get(
            "https://api.yookassa.ru/v3/payments?limit=1",
            auth=(yookassa_shop_id, yookassa_secret_key),
        )
        if yk_response.status_code in {401, 403}:
            raise SystemExit(f"YooKassa credentials check failed: HTTP {yk_response.status_code}")
        if yk_response.status_code < 200 or yk_response.status_code >= 500:
            raise SystemExit(f"YooKassa API unexpected status: HTTP {yk_response.status_code}")
        print(f"yookassa api reachable: HTTP {yk_response.status_code}")

asyncio.run(main())
PY

echo "== 11. Nginx config =="
sudo nginx -t

echo "== 12. Recent critical logs =="
if journalctl -u voidbot -n 120 --no-pager -l | grep -Ei "Traceback|ImportError|ModuleNotFoundError|CRITICAL" >/tmp/void_smoke_bot_errors.out; then
  echo "Recent bot critical errors found:"
  cat /tmp/void_smoke_bot_errors.out
  exit 1
fi
echo "bot recent critical logs ok"

if journalctl -u voidbot-webhook -n 120 --no-pager -l | grep -Ei "Traceback|ImportError|ModuleNotFoundError|CRITICAL" >/tmp/void_smoke_webhook_errors.out; then
  echo "Recent webhook critical errors found:"
  cat /tmp/void_smoke_webhook_errors.out
  exit 1
fi
echo "webhook recent critical logs ok"

echo "== SMOKE OK =="
