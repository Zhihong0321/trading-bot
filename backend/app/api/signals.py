"""Signal endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query

from ..config import CONFIG
from ..models import IndicatorInfo, SignalResponse, SignalWeights
from ..state import STATE

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("")
def get_signal(ts: Optional[datetime] = Query(None)) -> SignalResponse:
    """Return the current signal snapshot."""
    _ = ts  # reserved for future deterministic lookup
    return STATE.latest_signal()


@router.get("/indicators")
def list_indicators() -> dict[str, list[IndicatorInfo]]:
    """Describe the indicators that feed the aggregate signal."""
    return {
        "indicators": [
            IndicatorInfo(
                name="ema_slope",
                description="EMA20 vs EMA50 slope z-score",
                parameters={"length_fast": "20", "length_slow": "50"},
                default_weight=CONFIG.weights["ema_slope"],
            ),
            IndicatorInfo(
                name="macd",
                description="MACD histogram normalized by ATR",
                parameters={"fast": "12", "slow": "26", "signal": "9"},
                default_weight=CONFIG.weights["macd"],
            ),
            IndicatorInfo(
                name="bb_pos",
                description="Bollinger Bands %B",
                parameters={"length": "20", "stddev": "2"},
                default_weight=CONFIG.weights["bb_pos"],
            ),
            IndicatorInfo(
                name="atr_brk",
                description="ATR breakout detector",
                parameters={"atr_length": "14", "multiplier": "1.0"},
                default_weight=CONFIG.weights["atr_brk"],
            ),
            IndicatorInfo(
                name="vwap_dev",
                description="Session VWAP deviation",
                parameters={"session": "european"},
                default_weight=CONFIG.weights["vwap_dev"],
            ),
        ]
    }


@router.put("/weights")
def update_weights(weights: SignalWeights) -> SignalWeights:
    """Update indicator weights with simple normalization."""
    total = sum(abs(value) for value in weights.model_dump().values())
    if total == 0:
        raise ValueError("Weights must not all be zero")
    normalized = {name: value / total for name, value in weights.model_dump().items()}
    CONFIG.weights.update(normalized)
    return SignalWeights(**CONFIG.weights)
