"""In-memory state store for the simulator prototype."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
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
from .simulator import SimulationRunner


class SimulationState:
    """Container for the current simulation session."""

    def __init__(self) -> None:
        self.run_id: Optional[str] = None
        self.start_request: Optional[SimulationStartRequest] = None
        self.trades: List[TradeLogEntry] = []
        self.equity: float = CONFIG.simulation.initial_fund
        self.drawdown: float = 0.0
        self.last_update: Optional[datetime] = None
        self.open_position: Optional[Dict[str, object]] = None
        self.kpis: Dict[str, float] = {"trades": 0.0}
        self._latest_signal: SignalResponse = self._idle_signal()
        self.market: Optional[Dict[str, float]] = None
        self.signal_summary: Optional[Dict[str, float]] = None
        self._lock = Lock()
        self._runner: Optional[SimulationRunner] = None

    def start(self, request: SimulationStartRequest) -> str:
        with self._lock:
            if self.run_id is not None:
                raise RuntimeError("Simulation already running")

            self.run_id = f"sim-{int(datetime.now(tz=timezone.utc).timestamp())}"
            self.start_request = request
            self.trades = []
            self.equity = request.initial_fund
            self.drawdown = 0.0
            self.last_update = request.start_ts
            self.open_position = None
            self.kpis = {"trades": 0.0}
            self._latest_signal = self._idle_signal()
            self.market = None
            self.signal_summary = None
            runner = SimulationRunner(self, request)
            self._runner = runner

        runner.start()
        return self.run_id

    def stop(self) -> None:
        runner: Optional[SimulationRunner]
        with self._lock:
            runner = self._runner
            self._runner = None

        if runner is not None:
            runner.stop()

        with self._lock:
            self.run_id = None
            self.start_request = None
            self.trades = []
            self.equity = CONFIG.simulation.initial_fund
            self.drawdown = 0.0
            self.last_update = None
            self.open_position = None
            self.kpis = {"trades": 0.0}
            self._latest_signal = self._idle_signal()
            self.market = None
            self.signal_summary = None

    def complete_run(self) -> None:
        with self._lock:
            self.run_id = None
            self._runner = None

    def status(self) -> SimulationStatus:
        with self._lock:
            return SimulationStatus(
                run_id=self.run_id,
                clock_ts=self.last_update,
                equity=self.equity,
                dd=self.drawdown,
                open_position=self.open_position,
                market=self.market,
                signal=self.signal_summary,
                kpis=self.kpis,
            )

    def latest_signal(self) -> SignalResponse:
        with self._lock:
            return self._latest_signal

    def update_from_runner(
        self,
        *,
        timestamp: datetime,
        equity: float,
        drawdown: float,
        open_position: Optional[Dict[str, object]],
        signal: SignalResponse,
        trades: List[TradeLogEntry],
        kpis: Dict[str, float],
        market: Dict[str, float],
        signal_summary: Dict[str, float],
    ) -> None:
        with self._lock:
            if self.run_id is None:
                return
            self.last_update = timestamp
            self.equity = equity
            self.drawdown = drawdown
            self.open_position = open_position
            self.trades = list(trades)
            self.kpis = kpis
            self._latest_signal = signal
            self.market = market
            self.signal_summary = signal_summary

    def _idle_signal(self) -> SignalResponse:
        weights = SignalWeights(**CONFIG.weights)
        return SignalResponse(
            signal_int=0,
            s_norm=0.0,
            confidence=0.0,
            scores=SignalScores(),
            weights=weights,
            meta={"prev_signal_int": "0"},
        )


STATE = SimulationState()
