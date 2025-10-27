"""Trading strategy implementing the conservative EMA momentum scalper."""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from trading_bot.config import AppConfig
from trading_bot.indicators import EMA, RSI, RollingWindow, atr
from trading_bot.risk import RiskManager
from trading_bot.state import BotContext, BotState, Position

LOGGER = logging.getLogger(__name__)


@dataclass
class MarketSnapshot:
    """Aggregated view of latest market data."""

    price: float
    bid: float
    ask: float
    spread_pct: float
    candle_close_time: datetime
    volume: float
    avg_volume: Optional[float]
    ema_fast: Optional[float]
    ema_slow: Optional[float]
    rsi: Optional[float]
    atr_pct: Optional[float]


class Strategy:
    """Decision engine evaluating entry/exit rules."""

    def __init__(self, config: AppConfig, context: BotContext):
        self.config = config
        self.context = context
        self.risk_manager = RiskManager(config, context)
        self.ema_fast = EMA(8)
        self.ema_slow = EMA(21)
        self.rsi = RSI(14)
        self.volume_ma = RollingWindow(10)
        self.last_trade_timestamp = 0.0
        self.last_result: Optional[str] = None
        self.highs = deque(maxlen=61)
        self.lows = deque(maxlen=61)
        self.closes = deque(maxlen=61)

    def update_indicators(self, candle: Dict[str, Any]) -> MarketSnapshot:
        kline = candle["k"]
        close_price = float(kline["c"])
        volume = float(kline["v"])
        high = float(kline["h"])
        low = float(kline["l"])
        ema_fast = self.ema_fast.update(close_price)
        ema_slow = self.ema_slow.update(close_price)
        rsi_value = self.rsi.update(close_price)
        self.volume_ma.append(volume)
        avg_volume = self.volume_ma.mean()
        self.highs.append(high)
        self.lows.append(low)
        self.closes.append(close_price)
        atr_pct = None
        if len(self.highs) >= 60:
            atr_value = atr(self.highs, self.lows, self.closes)
            atr_pct = atr_value / close_price if close_price else None

        bid = float(candle.get("b", close_price))
        ask = float(candle.get("a", close_price))
        spread_pct = (ask - bid) / close_price if close_price else 0.0

        return MarketSnapshot(
            price=close_price,
            bid=bid,
            ask=ask,
            spread_pct=spread_pct,
            candle_close_time=datetime.fromtimestamp(kline["T"] / 1000),
            volume=volume,
            avg_volume=avg_volume,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            rsi=rsi_value,
            atr_pct=atr_pct,
        )

    def entry_allowed(
        self,
        snapshot: MarketSnapshot,
        balances: Dict[str, float],
        *,
        now: float | None = None,
    ) -> bool:
        filters = self.config.filters
        current_ts = now if now is not None else time.time()
        clock_time = snapshot.candle_close_time.time()
        if not (filters.active_hours_start <= clock_time <= filters.active_hours_end):
            return False
        if snapshot.spread_pct > filters.max_spread_pct:
            return False
        if snapshot.avg_volume is None or snapshot.avg_volume <= 0:
            return False
        if snapshot.volume < filters.min_volume_multiplier * snapshot.avg_volume:
            return False
        if snapshot.atr_pct is not None and snapshot.atr_pct > filters.max_atr_pct:
            return False
        if snapshot.ema_fast is None or snapshot.ema_slow is None:
            return False
        if snapshot.ema_fast <= snapshot.ema_slow:
            return False
        if snapshot.rsi is None or not 35 <= snapshot.rsi <= 70:
            return False
        if snapshot.price <= float(balances.get("previous_candle_high", 0)):
            return False
        if current_ts - self.last_trade_timestamp < 180:
            return False
        if not self.risk_manager.can_take_trade(balances.get("USDT", 0.0)):
            return False
        return True

    def create_entry(self, snapshot: MarketSnapshot, *, now: float | None = None) -> Position:
        price = snapshot.bid
        quantity = self.risk_manager.position_size(price)
        take_profit = price * (1 + self.config.risk.take_profit_pct)
        stop_loss = price * (1 - self.config.risk.stop_loss_pct)
        position = Position(
            symbol=self.config.strategy.symbol,
            entry_price=price,
            quantity=quantity,
            timestamp=now if now is not None else time.time(),
            take_profit=take_profit,
            stop_loss=stop_loss,
        )
        self.context.position = position
        self.context.transition(BotState.PLACE_ENTRY)
        LOGGER.info("Generated entry signal at %s", snapshot.candle_close_time)
        return position

    def on_trade_result(self, pnl: float, was_win: bool, *, now: float | None = None) -> None:
        self.context.stats.register_win(pnl) if was_win else self.context.stats.register_loss(pnl)
        current_ts = now if now is not None else time.time()
        self.last_trade_timestamp = current_ts
        self.last_result = "win" if was_win else "loss"
        self.risk_manager.start_cooldown(was_win, now=current_ts)

    def cooldown_ready(self, *, now: float | None = None) -> bool:
        if self.context.state != BotState.COOLDOWN:
            return True
        if self.risk_manager.cooldown_elapsed(now=now):
            self.context.transition(BotState.IDLE)
            return True
        return False


__all__ = ["Strategy", "MarketSnapshot"]
