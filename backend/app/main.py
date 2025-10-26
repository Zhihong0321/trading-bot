"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI

from .api import configuration, signals, sim
from .config import CONFIG

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


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    """Simple health endpoint for infrastructure checks."""
    return {"status": "ok", "dataset": CONFIG.simulation.dataset_id}


@app.get("/")
def root() -> dict[str, str]:
    """Provide a simple landing response for root requests."""

    return {
        "message": "EUR/USD Signal Simulator backend is running.",
        "docs": "/docs",
        "status": "/healthz",
    }
