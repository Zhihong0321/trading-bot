"""Pydantic models for API payloads."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, validator

SignalSide = Literal["LONG", "SHORT"]


class SpreadModel(BaseModel):
    type: Literal["preset", "custom"] = "preset"
    name: Optional[str] = None
    avg_pips: Optional[float] = Field(
        None, description="Average spread in pips for custom configurations"
    )


class CommissionModel(BaseModel):
    type: Literal["none", "per_million"] = "none"
    usd_per_million_per_side: Optional[float] = None


class EntryThresholds(BaseModel):
    buy: int = Field(ge=0)
    sell: int = Field(le=0)

    @validator("buy")
    def validate_buy(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Buy threshold must be non-negative")
        return value

    @validator("sell")
    def validate_sell(cls, value: int) -> int:
        if value > 0:
            raise ValueError("Sell threshold must be non-positive")
        return value


class EventGuardConfig(BaseModel):
    enabled: bool = True
    window_sec: int = Field(default=90, ge=0)


class SimulationStartRequest(BaseModel):
    dataset_id: str
    start_ts: datetime
    speed: Literal["10x", "1x", "step"] = "1x"
    initial_fund: float = Field(gt=0)
    leverage_cap: float = Field(default=10.0, gt=0)
    risk_pct: float = Field(default=0.7, ge=0)
    entry_thresholds: EntryThresholds
    sl_atr_mult: float = Field(default=1.2, gt=0)
    tp_mult: float = Field(default=2.0, gt=0)
    trailing_stop: bool = False
    spread_model: SpreadModel = Field(default_factory=SpreadModel)
    commission_model: CommissionModel = Field(default_factory=CommissionModel)
    event_guard: EventGuardConfig = Field(default_factory=EventGuardConfig)
    rng_seed: int = 42


class SimulationStatus(BaseModel):
    run_id: Optional[str]
    clock_ts: Optional[datetime]
    equity: Optional[float]
    dd: Optional[float]
    open_position: Optional[Dict[str, Optional[float]]]
    kpis: Dict[str, float] = Field(default_factory=dict)


class TradeLogEntry(BaseModel):
    run_id: str
    ts_open: datetime
    side: SignalSide
    units: int
    price_in: float
    price_out: Optional[float]
    spread_pips_in: float
    spread_pips_out: Optional[float]
    commission_in: float
    commission_out: Optional[float]
    sl_tp: Literal["TP", "SL", "NONE"]
    reason_exit: Optional[Literal["TP", "Flip", "NeutralCross", "Manual"]]
    pnl_gross: Optional[float]
    pnl_net: Optional[float]


class SignalScores(BaseModel):
    ema_slope: float = 0.0
    macd: float = 0.0
    bb_pos: float = 0.0
    atr_brk: float = 0.0
    vwap_dev: float = 0.0


class SignalWeights(BaseModel):
    ema_slope: float
    macd: float
    bb_pos: float
    atr_brk: float
    vwap_dev: float


class SignalResponse(BaseModel):
    asset: str = "EUR_USD"
    tf: str = "30s"
    signal_version: str = "0.1.0"
    signal_int: int
    s_norm: float
    confidence: float
    scores: SignalScores
    weights: SignalWeights
    meta: Dict[str, Optional[str]] = Field(default_factory=dict)


class IndicatorInfo(BaseModel):
    name: str
    description: str
    parameters: Dict[str, str]
    default_weight: float


class DatasetsResponse(BaseModel):
    datasets: List[Dict[str, str]]
