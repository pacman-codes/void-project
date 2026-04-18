import logging

from aiohttp import web

from config.config import settings
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


def create_app() -> web.Application:
    app = web.Application(client_max_size=2 * 1024 * 1024)
    app.router.add_get("/health", health_handler)
    app.router.add_post("/yookassa/webhook", yookassa_webhook_handler)
    return app


if __name__ == "__main__":
    web.run_app(
        create_app(),
        host=settings.webhook_host,
        port=settings.webhook_port,
    )
