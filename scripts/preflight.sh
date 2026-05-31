#!/usr/bin/env bash
set -euo pipefail
PYTHON_BIN="${PYTHON_BIN:-./venv/bin/python}"

cd /home/vpn/telegram_bot

echo "== Python compile =="
"$PYTHON_BIN" -m py_compile main.py webhook_server.py
"$PYTHON_BIN" -m compileall -q bot services config db

echo "== Import check =="
"$PYTHON_BIN" - << 'PY'
import main
import webhook_server
from services.yookassa_webhook_service import process_yookassa_notification
from services.payment_service import create_redirect_payment, sync_payment_status
print("imports ok")
PY

echo "== Webhook local health =="
curl -fsS http://127.0.0.1:8081/health
echo

echo "== Webhook public route =="
code="$(curl -k -s -o /tmp/void_webhook_check.out -w '%{http_code}' https://pay.voidmod.space:8443/yookassa/webhook)"
if [ "$code" != "405" ]; then
  echo "Expected 405 for GET /yookassa/webhook, got $code"
  cat /tmp/void_webhook_check.out || true
  exit 1
fi
echo "public webhook route ok: HTTP $code"

echo "== Systemd =="
systemctl is-active --quiet voidbot
systemctl is-active --quiet voidbot-webhook
echo "systemd ok"

echo "PREFLIGHT OK"
