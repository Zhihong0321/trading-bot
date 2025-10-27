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

        def _write_response(self, body: bytes, *, status_code: int = 200, content_type: str = "application/json") -> None:
            self.send_response(status_code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
            if self.path not in {"/", "/healthz", "/status"}:
                self.send_response(404)
                self.end_headers()
                return

            payload = status.snapshot()
            if self.path == "/":
                html = [
                    "<!DOCTYPE html>",
                    "<html lang=\"en\">",
                    "<head>",
                    "  <meta charset=\"utf-8\">",
                    "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
                    "  <title>Trading Bot Status</title>",
                    "  <style>",
                    "    body { font-family: system-ui, sans-serif; margin: 2rem; background: #0f172a; color: #e2e8f0; }",
                    "    h1 { margin-bottom: 0.5rem; }",
                    "    .meta { color: #94a3b8; margin-bottom: 1.5rem; }",
                    "    table { border-collapse: collapse; width: 100%; max-width: 640px; background: #1e293b; border-radius: 0.5rem; overflow: hidden; }",
                    "    th, td { padding: 0.75rem 1rem; border-bottom: 1px solid #334155; text-align: left; }",
                    "    th { background: #334155; text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.1em; color: #cbd5f5; }",
                    "    tr:last-child td { border-bottom: none; }",
                    "    code { background: #111827; padding: 0.15rem 0.35rem; border-radius: 0.25rem; }",
                    "    pre { background: #111827; padding: 1rem; border-radius: 0.5rem; overflow-x: auto; color: #93c5fd; }",
                    "  </style>",
                    "  <meta http-equiv=\"refresh\" content=\"15\">",
                    "</head>",
                    "<body>",
                    "  <h1>Trading Bot Status</h1>",
                    "  <p class=\"meta\">Auto-refreshing every 15 seconds &middot; <a href=\"/status\" style=\"color:#38bdf8\">JSON</a> &middot; <a href=\"/healthz\" style=\"color:#38bdf8\">Health</a></p>",
                ]

                def human(value: object) -> str:
                    if isinstance(value, float):
                        return f"{value:,.4f}" if abs(value) < 1000 else f"{value:,.2f}"
                    return str(value)

                rows = []
                for key in sorted(payload.keys()):
                    rows.append(f"    <tr><th>{key}</th><td>{human(payload[key])}</td></tr>")

                html.extend([
                    "  <table>",
                    *rows,
                    "  </table>",
                    "  <h2 style=\"margin-top:2rem;\">Raw Payload</h2>",
                    f"  <pre>{json.dumps(payload, indent=2)}</pre>",
                    "</body>",
                    "</html>",
                ])
                body = "\n".join(html).encode("utf-8")
                self._write_response(body, content_type="text/html; charset=utf-8")
                return

            if self.path == "/healthz":
                state = payload.get("state", "unknown")
                status_code = 200 if state in {"running", "position_closed"} else 503
                body = json.dumps({"state": state}).encode("utf-8")
                self._write_response(body, status_code=status_code)
                return

            body = json.dumps(payload).encode("utf-8")
            self._write_response(body)

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
