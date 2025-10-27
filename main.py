"""Service entrypoint exposing the bot status over HTTP for Railway."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional
from urllib import parse

from trading_bot.bot import TradingBot
from trading_bot.config import load_config
from trading_bot.backtest import SimulationParameters, run_backtest_sync


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


class SimulationStore:
    """Stores the latest backtest results and orchestrates runs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: Optional[Dict[str, object]] = None
        self._running = False
        self._error: Optional[str] = None

    def start(self) -> None:
        with self._lock:
            if self._running:
                raise RuntimeError("A simulation is already running")
            self._running = True
            self._error = None

    def finish(self, result: Dict[str, object]) -> None:
        with self._lock:
            self._running = False
            self._latest = result

    def fail(self, message: str) -> None:
        with self._lock:
            self._running = False
            self._error = message

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            return {
                "running": self._running,
                "error": self._error,
                "result": self._latest.copy() if self._latest else None,
            }


def _format_datetime_for_input(dt_value: datetime) -> str:
    return dt_value.strftime("%Y-%m-%dT%H:%M")


def make_request_handler(status: BotStatusTracker, simulations: SimulationStore):
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
            if self.path not in {"/", "/healthz", "/status", "/simulation.json"}:
                self.send_response(404)
                self.end_headers()
                return

            payload = status.snapshot()
            if self.path == "/":
                sim_snapshot = simulations.snapshot()
                now = datetime.utcnow()
                default_end = now
                default_start = now - timedelta(hours=6)
                latest_result = sim_snapshot.get("result")
                if latest_result:
                    params = latest_result.get("parameters", {})
                    start_val = params.get("start")
                    end_val = params.get("end")
                    if isinstance(start_val, str):
                        try:
                            start_val = datetime.fromisoformat(start_val)
                        except ValueError:
                            start_val = None
                    if isinstance(end_val, str):
                        try:
                            end_val = datetime.fromisoformat(end_val)
                        except ValueError:
                            end_val = None
                    if isinstance(start_val, datetime):
                        default_start = start_val
                    if isinstance(end_val, datetime):
                        default_end = end_val
                sim_running = sim_snapshot.get("running")
                sim_error = sim_snapshot.get("error")
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
                    "  <h1>Trading Bot Control Center</h1>",
                    "  <p class=\"meta\">Auto-refreshing every 15 seconds &middot; <a href=\"/status\" style=\"color:#38bdf8\">JSON</a> &middot; <a href=\"/healthz\" style=\"color:#38bdf8\">Health</a> &middot; <a href=\"/simulation.json\" style=\"color:#38bdf8\">Simulation JSON</a></p>",
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
                    "  <section style=\"margin-top:2.5rem; background:#1e293b; padding:1.5rem; border-radius:0.75rem; max-width:720px;\">",
                    "    <h2 style=\"margin-top:0;\">Run Historical Simulation</h2>",
                    "    <p style=\"color:#94a3b8;\">Select a time window and adjust strategy parameters to replay the market and inspect trade-by-trade results.</p>",
                    "    <form method=\"post\" action=\"/simulate\" style=\"display:grid; gap:1rem; grid-template-columns:repeat(auto-fit,minmax(220px,1fr));\">",
                    f"      <label>Start (UTC)<br><input type=\"datetime-local\" name=\"start\" value=\"{_format_datetime_for_input(default_start)}\" required style=\"width:100%; padding:0.5rem; border-radius:0.5rem; border:none; background:#0f172a; color:#e2e8f0;\"></label>",
                    f"      <label>End (UTC)<br><input type=\"datetime-local\" name=\"end\" value=\"{_format_datetime_for_input(default_end)}\" required style=\"width:100%; padding:0.5rem; border-radius:0.5rem; border:none; background:#0f172a; color:#e2e8f0;\"></label>",
                    f"      <label>Initial Capital (USDT)<br><input type=\"number\" step=\"0.01\" min=\"10\" name=\"initial_capital\" value=\"{payload.get('balance', 300)}\" style=\"width:100%; padding:0.5rem; border-radius:0.5rem; border:none; background:#0f172a; color:#e2e8f0;\"></label>",
                    "      <label>Position Size (USDT)<br><input type=\"number\" step=\"0.01\" min=\"1\" name=\"position_size\" value=\"75\" style=\"width:100%; padding:0.5rem; border-radius:0.5rem; border:none; background:#0f172a; color:#e2e8f0;\"></label>",
                    "      <label>Stop Loss %<br><input type=\"number\" step=\"0.0001\" min=\"0.0001\" name=\"stop_loss_pct\" value=\"0.003\" style=\"width:100%; padding:0.5rem; border-radius:0.5rem; border:none; background:#0f172a; color:#e2e8f0;\"></label>",
                    "      <label>Take Profit %<br><input type=\"number\" step=\"0.0001\" min=\"0.0001\" name=\"take_profit_pct\" value=\"0.0045\" style=\"width:100%; padding:0.5rem; border-radius:0.5rem; border:none; background:#0f172a; color:#e2e8f0;\"></label>",
                    "      <label>Break-even Trigger %<br><input type=\"number\" step=\"0.0001\" min=\"0\" name=\"break_even_trigger\" value=\"0.002\" style=\"width:100%; padding:0.5rem; border-radius:0.5rem; border:none; background:#0f172a; color:#e2e8f0;\"></label>",
                    "      <label>Environment<br><select name=\"environment\" style=\"width:100%; padding:0.5rem; border-radius:0.5rem; border:none; background:#0f172a; color:#e2e8f0;\"><option value=\"production\">Production</option><option value=\"testnet\">Testnet</option></select></label>",
                    "      <label>Entry Fee %<br><input type=\"number\" step=\"0.0001\" min=\"0\" name=\"entry_fee_pct\" value=\"0.00075\" style=\"width:100%; padding:0.5rem; border-radius:0.5rem; border:none; background:#0f172a; color:#e2e8f0;\"></label>",
                    "      <label>Exit Fee %<br><input type=\"number\" step=\"0.0001\" min=\"0\" name=\"exit_fee_pct\" value=\"0.001\" style=\"width:100%; padding:0.5rem; border-radius:0.5rem; border:none; background:#0f172a; color:#e2e8f0;\"></label>",
                    "      <div style=\"grid-column:1 / -1;\">",
                    f"        <button type=\"submit\" style=\"padding:0.75rem 1.5rem; background:#38bdf8; border:none; border-radius:999px; color:#0f172a; font-weight:600; cursor:pointer;\" {'disabled' if sim_running else ''}>",
                    "Run Simulation" if not sim_running else "Simulation running...",
                    "        </button>",
                    "      </div>",
                    "    </form>",
                ])
                if sim_error:
                    html.append(
                        f"    <p style=\"color:#f87171; margin-top:1rem;\">Simulation failed: {sim_error}</p>"
                    )
                if latest_result:
                    summary = latest_result.get("summary", {})
                    trades = latest_result.get("trades", [])
                    html.extend([
                        "    <div style=\"margin-top:2rem;\">",
                        "      <h3>Simulation Summary</h3>",
                        "      <table style=\"border-collapse:collapse; width:100%; max-width:720px; background:#0f172a; border-radius:0.5rem; overflow:hidden;\">",
                    ])
                    for key, label in [
                        ("trades", "Trades"),
                        ("final_balance", "Final Balance"),
                        ("net_pnl", "Net PnL"),
                        ("win_rate", "Win Rate (%)"),
                        ("profit_factor", "Profit Factor"),
                        ("max_drawdown", "Max Drawdown (USDT)"),
                        ("max_drawdown_pct", "Max Drawdown (%)"),
                        ("average_trade_duration", "Avg Duration (s)"),
                    ]:
                        value = summary.get(key, "-")
                        html.append(
                            f"        <tr><th style=\"padding:0.6rem 1rem; border-bottom:1px solid #1e293b; text-align:left; background:#111827;\">{label}</th><td style=\"padding:0.6rem 1rem; border-bottom:1px solid #1e293b;\">{value}</td></tr>"
                        )
                    html.extend([
                        "      </table>",
                        "    </div>",
                    ])
                    if trades:
                        html.extend([
                            "    <div style=\"margin-top:2rem; overflow-x:auto;\">",
                            "      <h3>Trade Log</h3>",
                            "      <table style=\"border-collapse:collapse; min-width:720px; background:#0f172a; border-radius:0.5rem; overflow:hidden;\">",
                            "        <thead><tr><th style=\"padding:0.5rem; text-align:left; background:#111827;\">Entry</th><th style=\"padding:0.5rem; text-align:left; background:#111827;\">Exit</th><th style=\"padding:0.5rem; text-align:right; background:#111827;\">Entry Price</th><th style=\"padding:0.5rem; text-align:right; background:#111827;\">Exit Price</th><th style=\"padding:0.5rem; text-align:right; background:#111827;\">Qty</th><th style=\"padding:0.5rem; text-align:right; background:#111827;\">PnL</th><th style=\"padding:0.5rem; text-align:left; background:#111827;\">Reason</th></tr></thead>",
                            "        <tbody>",
                        ])
                        for trade in trades:
                            entry_time = trade.get("entry_time", "-")
                            exit_time = trade.get("exit_time", "-")
                            entry_price = float(trade.get("entry_price", 0.0))
                            exit_price = float(trade.get("exit_price", 0.0))
                            quantity = float(trade.get("quantity", 0.0))
                            pnl_value = float(trade.get("pnl", 0.0))
                            reason = trade.get("reason", "-")
                            row = (
                                "          <tr>"
                                "<td style=\"padding:0.5rem; border-bottom:1px solid #1e293b;\">{entry}</td>"
                                "<td style=\"padding:0.5rem; border-bottom:1px solid #1e293b;\">{exit}</td>"
                                "<td style=\"padding:0.5rem; border-bottom:1px solid #1e293b; text-align:right;\">{entry_price:.4f}</td>"
                                "<td style=\"padding:0.5rem; border-bottom:1px solid #1e293b; text-align:right;\">{exit_price:.4f}</td>"
                                "<td style=\"padding:0.5rem; border-bottom:1px solid #1e293b; text-align:right;\">{quantity:.5f}</td>"
                                "<td style=\"padding:0.5rem; border-bottom:1px solid #1e293b; text-align:right;\">{pnl:.4f}</td>"
                                "<td style=\"padding:0.5rem; border-bottom:1px solid #1e293b;\">{reason}</td>"
                                "</tr>"
                            ).format(
                                entry=entry_time,
                                exit=exit_time,
                                entry_price=entry_price,
                                exit_price=exit_price,
                                quantity=quantity,
                                pnl=pnl_value,
                                reason=reason,
                            )
                            html.append(row)
                        html.extend([
                            "        </tbody>",
                            "      </table>",
                            "    </div>",
                        ])
                    html.extend([
                        "    <h3 style=\"margin-top:2rem;\">Raw Simulation JSON</h3>",
                        f"    <pre>{json.dumps(latest_result, indent=2)}</pre>",
                    ])
                html.extend([
                    "  </section>",
                    "  <h2 style=\"margin-top:2rem;\">Raw Bot Status</h2>",
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

            if self.path == "/simulation.json":
                sim_snapshot = simulations.snapshot()
                body = json.dumps(sim_snapshot, default=str).encode("utf-8")
                self._write_response(body)
                return

            body = json.dumps(payload).encode("utf-8")
            self._write_response(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            LOGGER.info("HTTP %s - %s", self.address_string(), format % args)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/simulate":
                self.send_response(404)
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length", "0"))
            data = self.rfile.read(length).decode("utf-8")
            form = parse.parse_qs(data)

            def get_value(key: str, default: str) -> str:
                return form.get(key, [default])[0]

            try:
                start = datetime.fromisoformat(get_value("start", ""))
                end = datetime.fromisoformat(get_value("end", ""))
            except ValueError:
                simulations.fail("Invalid start or end datetime")
                self._write_response(
                    json.dumps({"error": "Invalid datetime inputs"}).encode("utf-8"),
                    status_code=400,
                )
                return

            try:
                params = SimulationParameters(
                    start=start,
                    end=end,
                    initial_capital=float(get_value("initial_capital", "300")),
                    position_size=float(get_value("position_size", "75")),
                    stop_loss_pct=float(get_value("stop_loss_pct", "0.003")),
                    take_profit_pct=float(get_value("take_profit_pct", "0.0045")),
                    break_even_trigger=float(get_value("break_even_trigger", "0.002")),
                    entry_fee_pct=float(get_value("entry_fee_pct", "0.00075")),
                    exit_fee_pct=float(get_value("exit_fee_pct", "0.001")),
                    environment=get_value("environment", "production"),
                )
            except Exception as exc:  # noqa: BLE001 - surface validation errors
                simulations.fail(str(exc))
                self._write_response(
                    json.dumps({"error": str(exc)}).encode("utf-8"),
                    status_code=400,
                )
                return

            try:
                simulations.start()
            except RuntimeError as exc:
                self._write_response(
                    json.dumps({"error": str(exc)}).encode("utf-8"),
                    status_code=409,
                )
                return

            try:
                result = run_backtest_sync(params)
            except Exception as exc:  # pragma: no cover - defensive logging
                LOGGER.exception("Simulation failed")
                simulations.fail(str(exc))
                self._write_response(
                    json.dumps({"error": str(exc)}).encode("utf-8"),
                    status_code=500,
                )
                return

            simulations.finish(result.to_dict())
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

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
    simulations = SimulationStore()

    def status_callback(state: str, payload: Dict[str, object]) -> None:
        status.update(state, payload)

    bot = TradingBot(config, status_callback=status_callback)

    thread = threading.Thread(target=run_bot_thread, args=(bot, status), name="bot-thread", daemon=True)
    thread.start()

    handler = make_request_handler(status, simulations)
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
