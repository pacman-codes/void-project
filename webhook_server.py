import logging

from aiohttp import web

from config.config import settings
from services.admin_miniapp_auth import (
    AdminMiniAppAuthError,
    AdminMiniAppIdentity,
    authenticate_admin_init_data,
)
from services.admin_miniapp_service import (
    get_admin_servers,
    get_admin_stats,
    get_admin_traffic_summary,
    get_admin_user_detail,
    get_admin_user_events,
    get_admin_users,
)
from services.yookassa_webhook_service import process_yookassa_notification


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def health_handler(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def yookassa_webhook_handler(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.Response(text="invalid json", status=400)

    status_code, message = await process_yookassa_notification(payload)
    logger.info("YooKassa webhook processed: status=%s message=%s", status_code, message)
    return web.Response(text=message, status=status_code)


def _extract_admin_init_data(request: web.Request) -> str:
    init_data = request.headers.get("X-Telegram-Init-Data", "").strip()
    if init_data:
        return init_data

    auth_header = request.headers.get("Authorization", "").strip()
    scheme, _, value = auth_header.partition(" ")
    if scheme.lower() in {"tma", "telegramwebapp"}:
        return value.strip()

    return ""


def _auth_error_response(exc: AdminMiniAppAuthError) -> web.Response:
    return web.json_response(
        {
            "error": exc.code,
            "message": exc.message,
        },
        status=exc.status,
    )


def _require_admin(request: web.Request) -> AdminMiniAppIdentity:
    return authenticate_admin_init_data(_extract_admin_init_data(request))


def _parse_int_query(
    request: web.Request,
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = request.query.get(name)
    if raw is None or raw == "":
        return default

    try:
        value = int(raw)
    except ValueError:
        return default

    return max(minimum, min(value, maximum))


def _parse_telegram_id(request: web.Request) -> int:
    try:
        telegram_id = int(request.match_info["telegram_id"])
    except (KeyError, ValueError) as exc:
        raise web.HTTPBadRequest(text="invalid telegram_id") from exc

    if telegram_id <= 0:
        raise web.HTTPBadRequest(text="invalid telegram_id")

    return telegram_id


async def admin_me_handler(request: web.Request) -> web.Response:
    try:
        admin = _require_admin(request)
    except AdminMiniAppAuthError as exc:
        return _auth_error_response(exc)

    return web.json_response(
        {
            "telegram_id": admin.telegram_id,
            "username": admin.username,
            "first_name": admin.first_name,
            "last_name": admin.last_name,
            "auth_date": admin.auth_date,
            "read_only": True,
        }
    )


async def admin_stats_handler(request: web.Request) -> web.Response:
    try:
        _require_admin(request)
    except AdminMiniAppAuthError as exc:
        return _auth_error_response(exc)

    return web.json_response(await get_admin_stats())


async def admin_users_handler(request: web.Request) -> web.Response:
    try:
        _require_admin(request)
    except AdminMiniAppAuthError as exc:
        return _auth_error_response(exc)

    payload = await get_admin_users(
        limit=_parse_int_query(request, "limit", default=50, minimum=1, maximum=100),
        offset=_parse_int_query(request, "offset", default=0, minimum=0, maximum=10000),
        access_type=request.query.get("access_type"),
        query=request.query.get("q"),
    )
    return web.json_response(payload)


async def admin_user_detail_handler(request: web.Request) -> web.Response:
    try:
        _require_admin(request)
        telegram_id = _parse_telegram_id(request)
    except AdminMiniAppAuthError as exc:
        return _auth_error_response(exc)

    payload = await get_admin_user_detail(telegram_id)
    if payload is None:
        return web.json_response({"error": "not_found"}, status=404)

    return web.json_response(payload)


async def admin_user_events_handler(request: web.Request) -> web.Response:
    try:
        _require_admin(request)
        telegram_id = _parse_telegram_id(request)
    except AdminMiniAppAuthError as exc:
        return _auth_error_response(exc)

    return web.json_response(
        await get_admin_user_events(
            telegram_id,
            limit=_parse_int_query(request, "limit", default=20, minimum=1, maximum=50),
        )
    )


async def admin_traffic_summary_handler(request: web.Request) -> web.Response:
    try:
        _require_admin(request)
    except AdminMiniAppAuthError as exc:
        return _auth_error_response(exc)

    return web.json_response(await get_admin_traffic_summary())


async def admin_servers_handler(request: web.Request) -> web.Response:
    try:
        _require_admin(request)
    except AdminMiniAppAuthError as exc:
        return _auth_error_response(exc)

    return web.json_response(await get_admin_servers())


def create_app() -> web.Application:
    app = web.Application(client_max_size=2 * 1024 * 1024)
    app.router.add_get("/health", health_handler)
    app.router.add_post("/yookassa/webhook", yookassa_webhook_handler)
    app.router.add_get("/miniapp/admin/me", admin_me_handler)
    app.router.add_get("/miniapp/admin/stats", admin_stats_handler)
    app.router.add_get("/miniapp/admin/users", admin_users_handler)
    app.router.add_get("/miniapp/admin/users/{telegram_id}/events", admin_user_events_handler)
    app.router.add_get("/miniapp/admin/users/{telegram_id}", admin_user_detail_handler)
    app.router.add_get("/miniapp/admin/traffic/summary", admin_traffic_summary_handler)
    app.router.add_get("/miniapp/admin/servers", admin_servers_handler)
    return app


if __name__ == "__main__":
    web.run_app(
        create_app(),
        host=settings.webhook_host,
        port=settings.webhook_port,
    )
