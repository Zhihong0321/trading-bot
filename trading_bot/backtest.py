"""Historical backtesting utilities for the trading dashboard."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, root_validator

from trading_bot.config import AppConfig, load_config
from trading_bot.data.feed import BINANCE_REST, TESTNET_REST, fetch_candles_between
from trading_bot.state import BotContext, BotState
from trading_bot.strategy import Strategy


class SimulationParameters(BaseModel):
    """User-configurable knobs for running a simulation."""

    start: datetime = Field(..., description="Inclusive start timestamp for historical candles")
    end: datetime = Field(..., description="Exclusive end timestamp for historical candles")
    initial_capital: float = Field(300, gt=0, description="Starting balance in USDT")
    position_size: float = Field(75, gt=0, description="Nominal position size per trade in USDT")
    stop_loss_pct: float = Field(0.003, gt=0, description="Stop loss percentage as decimal fraction")
    take_profit_pct: float = Field(0.0045, gt=0, description="Take profit percentage as decimal fraction")
    break_even_trigger: float = Field(0.002, ge=0, description="Profit percentage that moves stop to entry")
    entry_fee_pct: float = Field(0.00075, ge=0, description="Entry fee percentage (maker)")
    exit_fee_pct: float = Field(0.001, ge=0, description="Exit fee percentage (taker)")
    environment: str = Field("production", description="Data source environment (production/testnet)")

    @root_validator
    def validate_range(cls, values: Dict[str, object]) -> Dict[str, object]:
        start: Optional[datetime] = values.get("start")  # type: ignore[assignment]
        end: Optional[datetime] = values.get("end")  # type: ignore[assignment]
        if start and end:
            if end <= start:
                raise ValueError("End time must be after start time")
            if end - start > timedelta(days=7):
                raise ValueError("Simulation window cannot exceed 7 days")
        return values


@dataclass
class SimulationTrade:
    """Single trade outcome during the simulation."""

    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    reason: str
    holding_seconds: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat(),
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "pnl": self.pnl,
            "reason": self.reason,
            "holding_seconds": self.holding_seconds,
        }


@dataclass
class SimulationResult:
    """Aggregate result for a simulation run."""

    parameters: SimulationParameters
    trades: List[SimulationTrade]
    final_balance: float
    net_pnl: float
    win_rate: float
    profit_factor: float | None
    max_drawdown: float
    max_drawdown_pct: float
    average_trade_duration: float

    def to_dict(self) -> Dict[str, object]:
        params = self.parameters.dict()
        params["start"] = self.parameters.start.isoformat()
        params["end"] = self.parameters.end.isoformat()
        return {
            "parameters": params,
            "summary": {
                "final_balance": self.final_balance,
                "net_pnl": self.net_pnl,
                "win_rate": self.win_rate,
                "profit_factor": self.profit_factor,
                "max_drawdown": self.max_drawdown,
                "max_drawdown_pct": self.max_drawdown_pct,
                "average_trade_duration": self.average_trade_duration,
                "trades": len(self.trades),
            },
            "trades": [trade.to_dict() for trade in self.trades],
        }


async def run_backtest(params: SimulationParameters, *, base_config: AppConfig | None = None) -> SimulationResult:
    """Execute the scalping strategy over the requested historical window."""

    config = (base_config or load_config()).copy(deep=True)
    config.environment = "testnet" if params.environment.lower() == "testnet" else "production"
    config.risk.capital = params.initial_capital
    config.risk.position_size = params.position_size
    config.risk.stop_loss_pct = params.stop_loss_pct
    config.risk.take_profit_pct = params.take_profit_pct
    config.risk.risk_per_trade = params.position_size * params.stop_loss_pct
    config.strategy.break_even_trigger = params.break_even_trigger

    base_url = BINANCE_REST if config.environment == "production" else TESTNET_REST

    candles = await fetch_candles_between(
        config.strategy.symbol,
        params.start,
        params.end,
        base_url=base_url,
    )
    if not candles:
        raise ValueError("No candles returned for the requested window")

    context = BotContext()
    strategy = Strategy(config, context)
    balances: Dict[str, float] = {
        "USDT": config.risk.capital,
        "last_candle_high": 0.0,
        "previous_candle_high": 0.0,
    }

    trades: List[SimulationTrade] = []
    entry_cost: float = 0.0
    entry_fee: float = 0.0
    peak_equity = config.risk.capital
    max_drawdown = 0.0

    for candle in candles:
        close_time = candle.open_time + timedelta(minutes=1)
        previous_high = float(balances.get("last_candle_high", 0.0))
        bid = candle.close * (1 - 0.0001)
        ask = candle.close * (1 + 0.0001)
        payload = {
            "k": {
                "t": int(candle.open_time.timestamp() * 1000),
                "T": int(close_time.timestamp() * 1000),
                "o": candle.open,
                "c": candle.close,
                "h": candle.high,
                "l": candle.low,
                "v": candle.volume,
            },
            "b": bid,
            "a": ask,
        }
        snapshot = strategy.update_indicators(payload)
        balances["last_candle_high"] = candle.high
        balances["previous_candle_high"] = previous_high or candle.high
        candle_ts = close_time.timestamp()

        position = context.position
        if position:
            if (
                not position.break_even_activated
                and candle.high >= position.entry_price * (1 + config.strategy.break_even_trigger)
            ):
                position.break_even_activated = True
                position.stop_loss = max(position.stop_loss, position.entry_price)

            exit_price: Optional[float] = None
            exit_reason = ""

            if candle.low <= position.stop_loss:
                exit_price = position.stop_loss
                exit_reason = "stop_loss"
            elif candle.high >= position.take_profit:
                exit_price = position.take_profit
                exit_reason = "take_profit"
            elif candle_ts - position.timestamp >= config.strategy.max_position_lifetime:
                exit_price = candle.close
                exit_reason = "time_exit"

            if exit_price is not None:
                exit_value = exit_price * position.quantity
                exit_fee = exit_value * params.exit_fee_pct
                pnl = exit_value - exit_fee - (entry_cost + entry_fee)
                balances["USDT"] += exit_value - exit_fee
                was_win = pnl > 0
                strategy.on_trade_result(pnl, was_win, now=candle_ts)
                trades.append(
                    SimulationTrade(
                        entry_time=datetime.fromtimestamp(position.timestamp),
                        exit_time=close_time,
                        entry_price=position.entry_price,
                        exit_price=exit_price,
                        quantity=position.quantity,
                        pnl=pnl,
                        reason=exit_reason,
                        holding_seconds=candle_ts - position.timestamp,
                    )
                )
                context.position = None
                entry_cost = 0.0
                entry_fee = 0.0
                equity = balances["USDT"]
                peak_equity = max(peak_equity, equity)
                drawdown = peak_equity - equity
                max_drawdown = max(max_drawdown, drawdown)
                continue

        if not strategy.cooldown_ready(now=candle_ts):
            continue

        if context.position:
            continue

        if strategy.entry_allowed(snapshot, balances, now=candle_ts):
            position = strategy.create_entry(snapshot, now=candle_ts)
            context.transition(BotState.MANAGE_POSITION)
            entry_cost = position.entry_price * position.quantity
            entry_fee = entry_cost * params.entry_fee_pct
            balances["USDT"] -= entry_cost + entry_fee

    if context.position:
        last_candle = candles[-1]
        close_time = last_candle.open_time + timedelta(minutes=1)
        position = context.position
        exit_price = last_candle.close
        exit_value = exit_price * position.quantity
        exit_fee = exit_value * params.exit_fee_pct
        candle_ts = close_time.timestamp()
        pnl = exit_value - exit_fee - (entry_cost + entry_fee)
        balances["USDT"] += exit_value - exit_fee
        was_win = pnl > 0
        strategy.on_trade_result(pnl, was_win, now=candle_ts)
        trades.append(
            SimulationTrade(
                entry_time=datetime.fromtimestamp(position.timestamp),
                exit_time=close_time,
                entry_price=position.entry_price,
                exit_price=exit_price,
                quantity=position.quantity,
                pnl=pnl,
                reason="final_close",
                holding_seconds=candle_ts - position.timestamp,
            )
        )
        context.position = None
        equity = balances["USDT"]
        peak_equity = max(peak_equity, equity)
        drawdown = peak_equity - equity
        max_drawdown = max(max_drawdown, drawdown)

    final_balance = balances["USDT"]
    net_pnl = final_balance - params.initial_capital

    total_trades = len(trades)
    wins = len([trade for trade in trades if trade.pnl > 0])
    win_rate = (wins / total_trades * 100) if total_trades else 0.0
    gross_profit = sum(trade.pnl for trade in trades if trade.pnl > 0)
    gross_loss = abs(sum(trade.pnl for trade in trades if trade.pnl < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss else None
    average_duration = (
        sum(trade.holding_seconds for trade in trades) / total_trades if total_trades else 0.0
    )
    max_drawdown_pct = (max_drawdown / peak_equity * 100) if peak_equity else 0.0

    return SimulationResult(
        parameters=params,
        trades=trades,
        final_balance=final_balance,
        net_pnl=net_pnl,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        average_trade_duration=average_duration,
    )


def run_backtest_sync(params: SimulationParameters, *, base_config: AppConfig | None = None) -> SimulationResult:
    """Synchronously execute :func:`run_backtest` for convenience."""

    return asyncio.run(run_backtest(params, base_config=base_config))


__all__ = [
    "SimulationParameters",
    "SimulationResult",
    "SimulationTrade",
    "run_backtest",
    "run_backtest_sync",
]
