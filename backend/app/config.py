"""Application configuration utilities."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import tomllib
from pydantic import BaseModel

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "defaults.toml"


class SimulationDefaults(BaseModel):
    dataset_id: str
    start_ts: str
    speed: str
    initial_fund: float
    leverage_cap: float
    risk_pct: float
    entry_threshold_buy: int
    entry_threshold_sell: int
    sl_atr_mult: float
    tp_mult: float
    trailing_stop: bool
    spread_model: str
    avg_spread_pips: float
    commission_model: str
    commission_per_million_per_side: float
    event_guard_enabled: bool
    event_guard_window_sec: int
    rng_seed: int


class Config(BaseModel):
    simulation: SimulationDefaults
    weights: Dict[str, float]
    costs: Dict[str, Dict[str, float]]
    risk: Dict[str, float]


def load_config(path: Path | None = None) -> Config:
    """Load configuration from a TOML file.

    Args:
        path: Optional path to override the default configuration location.

    Returns:
        Parsed :class:`Config` instance containing defaults for the application.
    """

    config_path = path or DEFAULT_CONFIG_PATH
    with config_path.open("rb") as file:
        data = tomllib.load(file)
    return Config(**data)


CONFIG = load_config()
