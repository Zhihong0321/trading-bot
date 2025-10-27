"""Risk controls and guard rails."""

from __future__ import annotations

import time
from dataclasses import dataclass

from trading_bot.config import AppConfig
from trading_bot.state import BotContext, BotState


@dataclass
class RiskManager:
    """Enforces position sizing and daily guard rails."""

    config: AppConfig
    context: BotContext

    def can_take_trade(self, available_usdt: float) -> bool:
        risk = self.config.risk
        stats = self.context.stats
        if self.context.state == BotState.HALTED:
            return False
        if stats.trades_taken >= risk.max_trades_per_day:
            self.context.state = BotState.HALTED
            self.context.halted_reason = "Max trades reached"
            return False
        if stats.daily_pnl <= -risk.max_daily_loss:
            self.context.state = BotState.HALTED
            self.context.halted_reason = "Daily loss limit reached"
            return False
        if stats.consecutive_losses >= 3:
            self.context.state = BotState.HALTED
            self.context.halted_reason = "Three consecutive losses"
            return False
        if available_usdt < risk.position_size:
            return False
        return True

    def position_size(self, price: float) -> float:
        """Return position quantity respecting exchange precision."""

        quote_size = self.config.risk.position_size
        quantity = quote_size / price
        return round(quantity, 5)  # Binance lot size for ETHUSDT spot is 0.00001

    def start_cooldown(self, was_win: bool, *, now: float | None = None) -> None:
        duration = (
            self.config.risk.cooldown_after_win if was_win else self.config.risk.cooldown_after_loss
        )
        base = now if now is not None else time.time()
        self.context.cooldown_expires = base + duration
        self.context.transition(BotState.COOLDOWN)

    def cooldown_elapsed(self, *, now: float | None = None) -> bool:
        current = now if now is not None else time.time()
        return current >= self.context.cooldown_expires


__all__ = ["RiskManager"]
