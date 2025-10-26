"""FastAPI application entrypoint."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .api import configuration, data_import, signals, sim
from .config import CONFIG

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

REPLAY_SPEED_OPTIONS = [
    {"value": "step", "label": "Step"},
    {"value": "1x", "label": "1×"},
    {"value": "2x", "label": "2×"},
    {"value": "5x", "label": "5×"},
    {"value": "10x", "label": "10×"},
    {"value": "20x", "label": "20×"},
]

app = FastAPI(
    title="EUR/USD Signal Simulator",
    version="0.1.0",
    description=(
        "Prototype backend implementing the public API contract for the "
        "EUR/USD 30-second signal simulator."
    ),
)

app.include_router(sim.router)
app.include_router(signals.router)
app.include_router(configuration.router)
app.include_router(data_import.router)


def _dashboard_defaults() -> Dict[str, Any]:
    """Return a dictionary of simulation defaults for the dashboard UI."""

    defaults = CONFIG.simulation
    return {
        "dataset_id": defaults.dataset_id,
        "start_ts": defaults.start_ts,
        "speed": defaults.speed,
        "initial_fund": defaults.initial_fund,
        "leverage_cap": defaults.leverage_cap,
        "risk_pct": defaults.risk_pct,
        "entry_thresholds": {
            "buy": defaults.entry_threshold_buy,
            "sell": defaults.entry_threshold_sell,
        },
        "sl_atr_mult": defaults.sl_atr_mult,
        "tp_mult": defaults.tp_mult,
        "trailing_stop": defaults.trailing_stop,
        "spread_model": defaults.spread_model,
        "avg_spread_pips": defaults.avg_spread_pips,
        "commission_model": defaults.commission_model,
        "commission_per_million_per_side": defaults.commission_per_million_per_side,
        "event_guard": {
            "enabled": defaults.event_guard_enabled,
            "window_sec": defaults.event_guard_window_sec,
        },
        "rng_seed": defaults.rng_seed,
    }


def _import_defaults() -> Dict[str, str]:
    """Return default window suggestions for the data import UI."""

    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = (end - timedelta(days=7)).replace(microsecond=0)
    return {
        "start": start.isoformat().replace("+00:00", "Z"),
        "end": end.isoformat().replace("+00:00", "Z"),
    }


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    """Simple health endpoint for infrastructure checks."""
    return {"status": "ok", "dataset": CONFIG.simulation.dataset_id}


@app.get("/", response_class=HTMLResponse)
def root(request: Request) -> HTMLResponse:
    """Render the interactive dashboard."""

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "defaults": _dashboard_defaults(),
            "cost_presets": CONFIG.costs,
            "risk": CONFIG.risk,
            "replay_speeds": REPLAY_SPEED_OPTIONS,
        },
    )


@app.get("/data-import", response_class=HTMLResponse)
def data_import_page(request: Request) -> HTMLResponse:
    """Render the data import management interface."""

    return templates.TemplateResponse(
        "data_import.html",
        {
            "request": request,
            "defaults": _import_defaults(),
        },
    )
