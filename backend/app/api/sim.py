"""Simulation endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..config import CONFIG
from ..models import DatasetsResponse, SimulationStartRequest
from ..state import STATE

router = APIRouter(prefix="/sim", tags=["simulation"])


@router.post("/start")
def start_simulation(request: SimulationStartRequest) -> dict[str, str]:
    """Start a new simulation run using in-memory defaults."""
    if STATE.run_id is not None:
        raise HTTPException(status_code=400, detail="Simulation already running")

    run_id = STATE.start(request)
    return {"run_id": run_id}


@router.post("/stop")
def stop_simulation() -> dict[str, str]:
    """Stop the current simulation."""
    if STATE.run_id is None:
        raise HTTPException(status_code=400, detail="No active simulation")
    STATE.stop()
    return {"status": "stopped"}


@router.get("/status")
def get_status() -> dict:
    """Return a snapshot of the simulation state."""
    return STATE.status().model_dump()


@router.get("/trades")
def get_trades(run_id: str = Query(..., description="Simulation run identifier")) -> dict:
    """Return the captured trade log for the requested run."""
    if STATE.run_id != run_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"trades": [trade.model_dump() for trade in STATE.trades]}


@router.get("/datasets")
def list_datasets() -> DatasetsResponse:
    """Return placeholder dataset metadata for the replay engine."""
    return DatasetsResponse(
        datasets=[
            {
                "dataset_id": CONFIG.simulation.dataset_id,
                "description": "Sample EUR/USD replay dataset",
            }
        ]
    )
