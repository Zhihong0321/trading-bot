"""Service entrypoint exposing the bot status over HTTP for Railway."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict

from trading_bot.bot import TradingBot
from trading_bot.config import load_config


LOGGER = logging.getLogger(__name__)


def configure_logging() -> None:
    """Configure root logging if no handlers are attached."""

    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )


class BotStatusTracker:
    """Thread-safe status container shared with the HTTP server."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: str = "initializing"
        self._details: Dict[str, object] = {}
        self._started_at = time.time()

    def update(self, state: str, details: Dict[str, object]) -> None:
        with self._lock:
            data = dict(details)
            self._state = state
            data.setdefault("state", state)
            data["started_at"] = self._started_at
            data["last_updated"] = time.time()
            self._details = data

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            payload = {
                "state": self._state,
                "started_at": self._started_at,
                "last_updated": time.time(),
            }
            payload.update(self._details)
            return payload


def make_request_handler(status: BotStatusTracker):
    """Factory producing a request handler bound to the provided status."""

    class RequestHandler(BaseHTTPRequestHandler):
        server_version = "TradingBotHTTP/1.0"

        def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
            if self.path not in {"/", "/healthz", "/status"}:
                self.send_response(404)
                self.end_headers()
                return

            payload = status.snapshot()
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            LOGGER.info("HTTP %s - %s", self.address_string(), format % args)

    return RequestHandler


def run_bot_thread(bot: TradingBot, status: BotStatusTracker) -> None:
    """Run the bot inside a thread and surface failures to the tracker."""

    async def runner() -> None:
        try:
            await bot.run()
        except Exception as exc:  # pragma: no cover - defensive safety net
            LOGGER.exception("Bot crashed")
            status.update("error", {"state": "error", "message": str(exc)})
            raise
        else:
            status.update("stopped", {"state": "stopped"})

    asyncio.run(runner())


def run() -> None:
    """Instantiate the bot, expose status via HTTP, and block forever."""

    configure_logging()

    env = os.getenv("BOT_ENV", "testnet").lower()
    port = int(os.getenv("PORT", "8000"))
    config = load_config()
    config.environment = "production" if env == "production" else "testnet"

    status = BotStatusTracker()

    def status_callback(state: str, payload: Dict[str, object]) -> None:
        status.update(state, payload)

    bot = TradingBot(config, status_callback=status_callback)

    thread = threading.Thread(target=run_bot_thread, args=(bot, status), name="bot-thread", daemon=True)
    thread.start()

    handler = make_request_handler(status)
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    LOGGER.info("HTTP status server running on port %s", port)

    server.daemon_threads = True

    def handle_shutdown(signum: int, frame) -> None:  # noqa: D401, ANN001 - signal handler signature
        LOGGER.info("Received signal %s, shutting down", signum)
        server.shutdown()

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        status.update("stopped", {"state": "stopped"})
        server.server_close()
        LOGGER.info("Status server stopped")


if __name__ == "__main__":
    run()
