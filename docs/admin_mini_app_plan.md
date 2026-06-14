# Internal Telegram Admin Mini App v0 Plan

## Scope

Admin Mini App v0 is an internal read-only dashboard for operational visibility. It is not a user Mini App and must only be available to Telegram IDs explicitly listed in `ADMIN_MINIAPP_TELEGRAM_IDS`.

v0 must not include destructive or state-changing actions:

- no paid extension buttons;
- no traffic reset;
- no subscription token rotation;
- no mass messages;
- no provisioning;
- no payment changes;
- no firewall, systemd, nginx, or production host changes.

## Current Repo Findings

Entrypoints:

- `main.py` starts the aiogram bot polling loop, initializes the DB, registers handlers, and starts schedulers.
- `webhook_server.py` is the existing `aiohttp` HTTP app for `/health` and YooKassa webhooks.
- `subscription_server.py` is a separate standard-library HTTP server for token-based subscription/config delivery.

Database/session patterns:

- `db/database.py` defines SQLAlchemy async engine/session helpers from `settings.DATABASE_URL`.
- `async_session_maker` is the legacy-compatible session alias used across handlers/services.
- Models live in `db/models.py`; migrations live under `migrations/versions`.

Subscription/web structure:

- Public subscription routes are isolated in `subscription_server.py`.
- Subscription link creation and rendering are in `services/subscription_link_service.py`.
- Subscription links are token-addressed and must not be reused as admin authentication.

Existing admin logic:

- Bot admin commands live mainly in `bot/handlers/admin_tools.py` and `bot/handlers/admin_users.py`.
- Existing bot-admin auth uses `ADMIN_TELEGRAM_IDS` and `message.from_user.id`.
- Existing admin commands include mutations such as paid/free activation, reset, cleanup, traffic set/reset, expiry runs, and legacy notifications. These actions are intentionally out of scope for Mini App v0.

User/event/traffic models:

- `User` contains identity/display fields, access state, subscription expiry, traffic counters, payment state, promo state, legal state, and device counters.
- `VpnAccess` contains server/device metadata plus sensitive `external_id`, `client_uuid`, and `config_url`.
- `UserSubscriptionLink` contains sensitive subscription `token`, activity state, and usage/rotation timestamps.
- `UserEvent` contains event metadata and `details_json`, which may contain nested operational data and must be sanitized before display.
- Traffic read/sync logic lives in `services/traffic_service.py`; v0 admin routes must use DB counters only and must not call panel sync.

Config/env pattern:

- `config/config.py` loads `.env.dev` first when present, otherwise `.env`.
- Core settings are stored in a `Settings` dataclass.
- `config/runtime.py` enforces production safety around `APP_ENV`, `DEV_MODE`, and `PANEL_ENABLED`.
- Server registry is loaded by `services/server_registry.py` from `SERVER_REGISTRY_PATH`, with secrets separately loaded from `SERVER_SECRETS_PATH`.

## Proposed Mini App Architecture

Admin Mini App backend should live in the existing `aiohttp` app (`webhook_server.py`) because it is already the repo's async HTTP app and can share SQLAlchemy async sessions without adding another framework.

Layers:

- `webhook_server.py`: HTTP route registration and request/response handling.
- `services/admin_miniapp_auth.py`: Telegram WebApp `initData` verification and admin allowlist checks.
- `services/admin_miniapp_service.py`: read-only DB queries, safe serializers, and masking/redaction.
- Future frontend: a minimal Telegram WebApp bundle can call these routes by passing `window.Telegram.WebApp.initData` in `X-Telegram-Init-Data`.

v0 route handlers must only call read-only DB/registry helpers. They must not call `VPNService` mutators, payment services, traffic sync/reset functions, bot send-message functions, shell scripts, deployment scripts, or panel mutation APIs.

## v0 Screens

Minimal screens for the first UI PR:

- Admin home: authenticated admin identity, read-only badge, top-level stats.
- Users list: searchable/paginated safe user rows.
- User detail: safe profile fields, active access row summaries, subscription link status, masked token, recent sanitized events.
- Traffic summary: DB traffic totals and per-access-type counters.
- Servers: registry node visibility without panel credentials or secret refs.

No large UI library is needed unless the repo later adds a frontend toolchain.

## v0 Read-Only API Routes

All routes require Telegram Mini App `initData` in the `X-Telegram-Init-Data` header. They may also accept `Authorization: tma <initData>` for non-browser clients.

- `GET /miniapp/admin/me`
  - Returns verified admin Telegram identity and `read_only: true`.

- `GET /miniapp/admin/stats`
  - Returns DB-only counts for users, access rows, active subscription links, and traffic totals.

- `GET /miniapp/admin/users`
  - Query params: `limit`, `offset`, `access_type`, `q`.
  - Returns only safe user-list fields.

- `GET /miniapp/admin/users/{telegram_id}`
  - Returns safe user detail, active access summaries, subscription link presence, masked tokens, and recent sanitized events.

- `GET /miniapp/admin/users/{telegram_id}/events`
  - Returns recent sanitized events for one user.

- `GET /miniapp/admin/traffic/summary`
  - Returns DB traffic counters only. No panel sync.

- `GET /miniapp/admin/servers`
  - Returns safe server registry fields only. No `server_secrets.env` reads beyond registry loader behavior, no credential output.

## Telegram Mini App Auth Model

Frontend flow:

1. Telegram opens the internal Mini App.
2. Frontend reads `window.Telegram.WebApp.initData`.
3. Frontend sends that raw `initData` in `X-Telegram-Init-Data` on every API request.
4. Backend verifies the `initData` HMAC using `BOT_TOKEN`.
5. Backend parses the signed Telegram user object and extracts `user.id`.
6. Backend checks `user.id` against `ADMIN_MINIAPP_TELEGRAM_IDS`.
7. Backend returns 403 for signed but non-allowed Telegram IDs.

Security rules:

- Never accept a frontend-posted `telegram_id` as proof of identity.
- Never trust Telegram username for admin access.
- Do not use subscription tokens, config links, or bot command auth as Mini App API auth.
- Keep `initData` out of query strings because URLs are often logged.
- Reject stale `initData` using `ADMIN_MINIAPP_INITDATA_MAX_AGE_SECONDS` unless explicitly set to `0` for a controlled local test.

## Allowlist Model

Use a dedicated allowlist:

```dotenv
ADMIN_MINIAPP_TELEGRAM_IDS=111111111,222222222
ADMIN_MINIAPP_INITDATA_MAX_AGE_SECONDS=86400
```

Rules:

- Values must be numeric Telegram IDs only.
- Owner ID and support operator ID are the only intended v0 entries.
- `ADMIN_TELEGRAM_IDS` remains separate for bot command admins.
- Empty or invalid `ADMIN_MINIAPP_TELEGRAM_IDS` means no Mini App access.

## Safe Data Fields

Users list may expose only:

- `telegram_id`
- `username`
- `first_name`
- `last_name`
- `access_type`
- `is_active`
- `subscription_expiry`
- `traffic_used`
- `traffic_limit`
- `device_limit`
- `created_at`
- `active_access_row_count`
- last event type/time

User detail may expose:

- the safe user fields above;
- active access rows with `server_name`, `device_name`, and `is_active` only;
- subscription link existence, active count, last used time, and masked token;
- recent events after recursive masking/redaction.

Servers route may expose:

- `code`
- `display_name`
- `provider`
- `enabled`
- `priority`
- `protocol`
- `network`
- public endpoint

Servers route must not expose panel origin, panel path, inbound secrets, `secret_ref`, credentials, private keys, Reality short IDs, or raw registry secrets.

## Sensitive Fields Never Exposed

Never expose:

- `BOT_TOKEN`
- payment secrets and YooKassa secret key
- `.env` values
- `server_secrets.env` values
- panel usernames/passwords
- panel API tokens or CSRF tokens
- full subscription tokens
- full `config_url`
- full `vless://` links
- full `hy2://` or `hysteria2://` links
- client UUIDs
- backup passwords
- private keys
- raw secrets from server registry or runtime config
- payment confirmation URLs
- raw payment IDs unless masked
- raw event `details_json` without sanitization

## Masked-Field Rules

Required masking rules:

- subscription token: `****abcd`
- UUID/client UUID: `****-****-****-1234`
- config URL: `hidden`
- `vless://...`, `hy2://...`, `hysteria2://...`: `hidden`
- payment ID / external ID: `****abcd`
- password/secret/private key/API key: `hidden`
- arbitrary event strings: replace embedded UUIDs and config links before returning them

Serializers should whitelist fields first, then mask. Do not serialize ORM objects directly.

## Future v1 Actions

If write actions are added later, use a preview/dry-run/apply/audit flow:

1. Preview endpoint returns what would change and why, with all secrets masked.
2. Dry-run endpoint performs validation and dependency checks without changing DB, panel, payment provider, or Telegram state.
3. Apply endpoint requires a fresh signed `initData`, admin ID allowlist, explicit action ID, and action-specific confirmation.
4. Apply writes an immutable `UserEvent` audit record with actor Telegram ID, target Telegram ID, request ID, before/after summary, and status.
5. Apply returns a result summary and never returns secrets.

Potential v1 actions:

- extend paid expiry;
- reset free traffic;
- rotate subscription token;
- disable one access row;
- run single-user payment sync;
- send a single templated support message.

Actions that affect many users, production networking, host firewall, systemd, nginx, deploy scripts, backups, or raw panel credentials should remain outside the Mini App unless a separate approval and audit design exists.

## Tests Before Production Enablement

Before enabling in production:

- Compile touched Python files with `python3 -m py_compile`.
- Unit-test Telegram `initData` verification with valid, invalid hash, stale auth date, future auth date, missing user, and non-allowlisted ID.
- Unit-test `ADMIN_MINIAPP_TELEGRAM_IDS` parsing with comma/semicolon separators and invalid entries.
- Unit-test masking for token, UUID, config URL, vless/hy2 links, payment ID, password/secret keys, and nested event details.
- Integration-test all v0 routes with:
  - no auth header -> 401;
  - invalid signature -> 401;
  - valid non-admin -> 403;
  - valid admin -> 200;
  - missing user detail -> 404.
- Verify route responses do not contain `BOT_TOKEN`, `PANEL_PASSWORD`, `YOOKASSA_SECRET_KEY`, full subscription tokens, `vless://`, `hy2://`, full UUIDs, or `config_url` contents.
- Verify `/miniapp/admin/traffic/summary` does not call panel sync or mutate traffic counters.
- Verify `/miniapp/admin/servers` does not expose panel credentials, panel path/origin, `secret_ref`, short IDs, or secrets file values.
- Review HTTP access logs to ensure `initData` is not logged in URLs.
- Keep the Mini App behind the existing private/admin deployment path until the allowlist and response scans are verified.
