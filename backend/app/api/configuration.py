"""Configuration endpoints for costs and risk."""
from __future__ import annotations

from fastapi import APIRouter

from ..config import CONFIG

router = APIRouter(tags=["configuration"])


@router.get("/costs")
def get_costs() -> dict[str, dict[str, float]]:
    """Return configured cost presets."""
    return CONFIG.costs


@router.put("/costs")
def update_costs(costs: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """Replace configured cost presets."""
    CONFIG.costs.clear()
    CONFIG.costs.update(costs)
    return CONFIG.costs


@router.get("/risk")
def get_risk() -> dict[str, float]:
    """Return risk guard rails."""
    return CONFIG.risk


@router.put("/risk")
def update_risk(risk: dict[str, float]) -> dict[str, float]:
    """Update risk guard rails."""
    CONFIG.risk.update(risk)
    return CONFIG.risk
