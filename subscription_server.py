from __future__ import annotations

import asyncio
import logging
import os
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from services.subscription_link_service import (
    SubscriptionLinkError,
    build_public_subscription_url,
    build_subscription_by_token,
    build_v2rayn_json_by_token,
)
from services.happ_auto_profile_service import (
    build_happ_auto_json_by_token,
    build_happ_auto_status_by_token,
    build_happ_cdn_json_by_token,
    build_happ_cdn_min_json_by_token,
    build_public_happ_auto_url,
)


HOST = os.getenv("SUBSCRIPTION_HOST", "127.0.0.1")
PORT = int(os.getenv("SUBSCRIPTION_PORT", "8088"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("SUBSCRIPTION_REQUEST_TIMEOUT", "15"))

TEXT_ENDPOINTS = {"sub"}
JSON_ENDPOINTS = {
    "v2rayn",
    "json",
    "auto",
    "happ-auto",
    "incy-auto",
    "auto-status",
    "happ-auto-status",
    "incy-auto-status",
    "happ-cdn",
    "happ-cdn-min",
}
REDIRECT_ENDPOINTS = {
    "happ",
    "happ-auto-import",
}
ALLOWED_ENDPOINTS = TEXT_ENDPOINTS | JSON_ENDPOINTS | REDIRECT_ENDPOINTS

_loop = asyncio.new_event_loop()


def _run_loop_forever() -> None:
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


_loop_thread = threading.Thread(target=_run_loop_forever, daemon=True)
_loop_thread.start()


def run_async(coro):
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=REQUEST_TIMEOUT_SECONDS)


class SubscriptionHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._handle_request(head_only=False)

    def do_HEAD(self) -> None:
        self._handle_request(head_only=True)

    def _handle_request(self, head_only: bool = False) -> None:
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]

        if len(parts) != 2 or parts[0] not in ALLOWED_ENDPOINTS:
            self._send_text(404, "Not found\n", head_only=head_only)
            return

        endpoint = parts[0]
        token = unquote(parts[1]).strip()

        if not token:
            self._send_text(400, "Bad request\n", head_only=head_only)
            return

        if endpoint == "happ":
            subscription_url = build_public_subscription_url(token)
            self._redirect(f"happ://add/{subscription_url}", head_only=head_only)
            return

        if endpoint == "happ-auto-import":
            profile_url = build_public_happ_auto_url(token)
            self._redirect(f"happ://add/{profile_url}", head_only=head_only)
            return

        try:
            if endpoint in {"auto", "happ-auto", "incy-auto"}:
                body = run_async(build_happ_auto_json_by_token(token))
                self._send_json(200, body, head_only=head_only)
                return

            if endpoint in {"auto-status", "happ-auto-status", "incy-auto-status"}:
                body = run_async(build_happ_auto_status_by_token(token))
                self._send_json(200, body, head_only=head_only)
                return

            if endpoint == "happ-cdn-min":
                body = run_async(build_happ_cdn_min_json_by_token(token))
                self._send_json(200, body, head_only=head_only)
                return

            if endpoint == "happ-cdn":
                body = run_async(build_happ_cdn_json_by_token(token))
                self._send_json(200, body, head_only=head_only)
                return

            if endpoint in {"v2rayn", "json"}:
                body = run_async(build_v2rayn_json_by_token(token))
                self._send_json(200, body, head_only=head_only)
                return

            body = run_async(build_subscription_by_token(token))
        except SubscriptionLinkError as exc:
            self._send_text(403, f"{exc}\n", head_only=head_only)
            return
        except FutureTimeoutError:
            logging.exception("Subscription endpoint timed out")
            self._send_text(504, "Timeout\n", head_only=head_only)
            return
        except Exception:
            logging.exception("Subscription endpoint failed")
            self._send_text(500, "Internal error\n", head_only=head_only)
            return

        self._send_text(200, body, head_only=head_only)

    def log_message(self, format: str, *args) -> None:
        logging.info("subscription_server: " + format, *args)

    def _redirect(self, url: str, head_only: bool = False) -> None:
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _send_text(self, status: int, body: str, head_only: bool = False) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def _send_json(self, status: int, body: str, head_only: bool = False) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if not head_only:
            self.wfile.write(data)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    server = ThreadingHTTPServer((HOST, PORT), SubscriptionHandler)
    print(f"Subscription server started on {HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
