"""In-memory state store for the simulator prototype."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from .config import CONFIG
from .models import (
    SignalResponse,
    SignalScores,
    SignalWeights,
    SimulationStartRequest,
    SimulationStatus,
    TradeLogEntry,
)


class SimulationState:
    """Container for the current simulation session."""

    def __init__(self) -> None:
        self.run_id: Optional[str] = None
        self.start_request: Optional[SimulationStartRequest] = None
        self.trades: List[TradeLogEntry] = []
        self.equity: float = CONFIG.simulation.initial_fund
        self.drawdown: float = 0.0
        self.last_update: Optional[datetime] = None

    def start(self, request: SimulationStartRequest) -> str:
        self.run_id = f"sim-{int(datetime.now(tz=timezone.utc).timestamp())}"
        self.start_request = request
        self.trades.clear()
        self.equity = request.initial_fund
        self.drawdown = 0.0
        self.last_update = request.start_ts
        return self.run_id

    def stop(self) -> None:
        self.run_id = None
        self.start_request = None
        self.trades.clear()
        self.equity = CONFIG.simulation.initial_fund
        self.drawdown = 0.0
        self.last_update = None

    def status(self) -> SimulationStatus:
        return SimulationStatus(
            run_id=self.run_id,
            clock_ts=self.last_update,
            equity=self.equity,
            dd=self.drawdown,
            open_position=None,
            kpis={"trades": float(len(self.trades))},
        )

    def latest_signal(self) -> SignalResponse:
        weights = SignalWeights(**CONFIG.weights)
        return SignalResponse(
            signal_int=0,
            s_norm=0.0,
            confidence=0.0,
            scores=SignalScores(),
            weights=weights,
            meta={
                "prev_signal_int": "0",
                "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            },
        )

    def append_trade(self, trade: TradeLogEntry) -> None:
        self.trades.append(trade)


STATE = SimulationState()
