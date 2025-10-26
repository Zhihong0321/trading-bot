"""Lightweight simulation runner used by the prototype backend."""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .config import CONFIG
from .models import (
    SignalResponse,
    SignalScores,
    SignalWeights,
    SimulationStartRequest,
    TradeLogEntry,
)


@dataclass
class GeneratedBar:
    """Simple container describing a single simulated bar."""

    timestamp: datetime
    bid: float
    ask: float
    spread_pips: float


def _ensure_utc(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def generate_sample_dataset(
    start_ts: datetime, count: int = 240, spread_pips: float = 1.2
) -> List[GeneratedBar]:
    """Produce a deterministic sequence of EUR/USD bars."""

    start_ts = _ensure_utc(start_ts)
    mid_price = 1.0825
    bars: List[GeneratedBar] = []
    spread = spread_pips * 0.0001

    for index in range(count):
        phase = index / 14.0
        swing = math.sin(phase) * 0.0008 + math.sin(phase / 3.0) * 0.0004
        drift = math.cos(phase / 6.0) * 0.0002
        mid = mid_price + swing + drift
        ts = start_ts + timedelta(seconds=30 * index)
        bid = mid - spread / 2
        ask = mid + spread / 2
        bars.append(
            GeneratedBar(timestamp=ts, bid=round(bid, 5), ask=round(ask, 5), spread_pips=spread_pips)
        )

    return bars


def _normalize(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _build_scores(index: int) -> Dict[str, float]:
    phase = index / 12.0
    return {
        "ema_slope": _normalize(math.sin(phase) * 0.9),
        "macd": _normalize(math.sin(phase / 1.5) * 0.95),
        "bb_pos": _normalize(math.cos(phase / 1.2)),
        "atr_brk": _normalize(math.sin(phase / 2.2) * 0.85),
        "vwap_dev": _normalize(math.cos(phase / 1.8) * 0.9),
    }


SPEED_TO_INTERVAL: Dict[str, float] = {
    "step": 1.0,
    "1x": 1.0,
    "2x": 0.6,
    "5x": 0.25,
    "10x": 0.12,
    "20x": 0.06,
}


class SimulationRunner:
    """Background worker that drives the fake replay engine."""

    def __init__(self, state: "SimulationState", request: SimulationStartRequest) -> None:
        from .state import SimulationState  # local import to avoid cycle

        self._state: SimulationState = state
        self._request = request
        self._weights = SignalWeights(**CONFIG.weights)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._interval = SPEED_TO_INTERVAL.get(request.speed, 1.0)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=1.0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _run(self) -> None:
        bars = generate_sample_dataset(
            start_ts=self._request.start_ts,
            spread_pips=self._request.spread_model.avg_pips
            if self._request.spread_model.avg_pips is not None
            else CONFIG.simulation.avg_spread_pips,
        )

        run_id = self._state.run_id
        if run_id is None:
            return

        trades: List[TradeLogEntry] = []
        equity = self._request.initial_fund
        peak_equity = equity
        open_position: Optional[dict] = None
        previous_signal = 0
        wins = 0

        for index, bar in enumerate(bars):
            if self._stop_event.is_set():
                break

            scores = _build_scores(index)
            aggregate = sum(
                getattr(self._weights, name) * score for name, score in scores.items()
            )
            aggregate = _normalize(aggregate)
            signal_int = int(round(aggregate * 5))
            confidence = min(1.0, abs(aggregate) * 0.95)

            signal = SignalResponse(
                signal_int=signal_int,
                s_norm=aggregate,
                confidence=confidence,
                scores=SignalScores(**scores),
                weights=self._weights,
                meta={
                    "prev_signal_int": str(previous_signal),
                    "timestamp": bar.timestamp.isoformat(),
                    "bid": f"{bar.bid:.5f}",
                    "ask": f"{bar.ask:.5f}",
                },
            )

            open_position_snapshot: Optional[dict] = None
            if open_position is None:
                if signal_int >= self._request.entry_thresholds.buy:
                    units = self._position_size(bar.ask)
                    open_position = {
                        "side": "LONG",
                        "units": units,
                        "entry_price": bar.ask,
                        "entry_ts": bar.timestamp,
                        "spread_in": bar.spread_pips,
                    }
                elif signal_int <= self._request.entry_thresholds.sell:
                    units = self._position_size(bar.bid)
                    open_position = {
                        "side": "SHORT",
                        "units": units,
                        "entry_price": bar.bid,
                        "entry_ts": bar.timestamp,
                        "spread_in": bar.spread_pips,
                    }
            else:
                direction = 1 if open_position["side"] == "LONG" else -1
                exit_price = bar.bid if direction == 1 else bar.ask
                entry_price = open_position["entry_price"]
                units = open_position["units"]
                unrealized = (exit_price - entry_price) * direction * units
                open_position_snapshot = {
                    "side": open_position["side"],
                    "units": units,
                    "entry_price": entry_price,
                    "entry_ts": open_position["entry_ts"].isoformat(),
                    "unrealized_pnl": round(unrealized, 2),
                }

                should_flip = (
                    direction == 1 and signal_int <= self._request.entry_thresholds.sell
                ) or (direction == -1 and signal_int >= self._request.entry_thresholds.buy)
                should_flatten = (
                    direction == 1 and signal_int <= 1
                ) or (direction == -1 and signal_int >= -1)

                if should_flip or should_flatten:
                    pnl = (exit_price - entry_price) * direction * units
                    equity += pnl
                    if pnl > 0:
                        wins += 1
                    trade = TradeLogEntry(
                        run_id=run_id,
                        ts_open=open_position["entry_ts"],
                        side=open_position["side"],
                        units=units,
                        price_in=entry_price,
                        price_out=exit_price,
                        spread_pips_in=open_position["spread_in"],
                        spread_pips_out=bar.spread_pips,
                        commission_in=0.0,
                        commission_out=0.0,
                        sl_tp="NONE",
                        reason_exit="Flip" if should_flip else "NeutralCross",
                        pnl_gross=round(pnl, 2),
                        pnl_net=round(pnl, 2),
                    )
                    trades.append(trade)
                    open_position = None
                    open_position_snapshot = None

                    if should_flip:
                        if signal_int >= self._request.entry_thresholds.buy:
                            units = self._position_size(bar.ask)
                            open_position = {
                                "side": "LONG",
                                "units": units,
                                "entry_price": bar.ask,
                                "entry_ts": bar.timestamp,
                                "spread_in": bar.spread_pips,
                            }
                        elif signal_int <= self._request.entry_thresholds.sell:
                            units = self._position_size(bar.bid)
                            open_position = {
                                "side": "SHORT",
                                "units": units,
                                "entry_price": bar.bid,
                                "entry_ts": bar.timestamp,
                                "spread_in": bar.spread_pips,
                            }

            peak_equity = max(peak_equity, equity)
            drawdown = 0.0
            if peak_equity > 0:
                drawdown = max(0.0, (peak_equity - equity) / peak_equity * 100.0)
            trade_count = len(trades)
            win_rate = (wins / trade_count) * 100 if trade_count else 0.0

            market_snapshot = {
                "bid": bar.bid,
                "ask": bar.ask,
                "spread_pips": bar.spread_pips,
                "mid": round((bar.bid + bar.ask) / 2, 5),
            }
            signal_summary = {
                "signal_int": signal_int,
                "s_norm": round(aggregate, 3),
                "confidence": round(confidence, 3),
            }

            self._state.update_from_runner(
                timestamp=bar.timestamp,
                equity=round(equity, 2),
                drawdown=round(drawdown, 2),
                open_position=open_position_snapshot,
                signal=signal,
                trades=trades,
                kpis={"trades": float(trade_count), "win_rate": round(win_rate, 2)},
                market=market_snapshot,
                signal_summary=signal_summary,
            )

            previous_signal = signal_int

            if self._interval > 0 and self._stop_event.wait(self._interval):
                break

        self._state.complete_run()

    def _position_size(self, price: float) -> int:
        max_notional = self._request.initial_fund * self._request.leverage_cap
        units = max_notional / price if price else 0
        suggested = max(1000, min(int(units * 0.1), int(units)))
        return int(round(suggested / 1000.0) * 1000)


__all__ = ["SimulationRunner", "generate_sample_dataset"]

