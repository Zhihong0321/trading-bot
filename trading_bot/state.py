"""Bot state machine definition."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class BotState(Enum):
    """Finite state machine representing the bot lifecycle."""

    IDLE = auto()
    PLACE_ENTRY = auto()
    MANAGE_POSITION = auto()
    COOLDOWN = auto()
    HALTED = auto()


@dataclass
class Position:
    """Represents the lifecycle of a single open trade."""

    symbol: str
    entry_price: float
    quantity: float
    timestamp: float
    take_profit: float
    stop_loss: float
    status: str = "open"
    break_even_activated: bool = False


@dataclass
class TradeStats:
    """Simple container for daily trade statistics."""

    trades_taken: int = 0
    wins: int = 0
    losses: int = 0
    daily_pnl: float = 0.0
    consecutive_losses: int = 0

    def register_win(self, pnl: float) -> None:
        self.trades_taken += 1
        self.wins += 1
        self.daily_pnl += pnl
        self.consecutive_losses = 0

    def register_loss(self, pnl: float) -> None:
        self.trades_taken += 1
        self.losses += 1
        self.daily_pnl += pnl
        self.consecutive_losses += 1

    def reset(self) -> None:
        self.trades_taken = 0
        self.wins = 0
        self.losses = 0
        self.daily_pnl = 0.0
        self.consecutive_losses = 0


@dataclass
class BotContext:
    """Holds mutable runtime data for the bot."""

    state: BotState = BotState.IDLE
    position: Optional[Position] = None
    stats: TradeStats = field(default_factory=TradeStats)
    cooldown_expires: float = 0.0
    halted_reason: Optional[str] = None

    def transition(self, new_state: BotState) -> None:
        """Transition to a new state, updating context as needed."""

        self.state = new_state
        if new_state == BotState.COOLDOWN:
            self.position = None


__all__ = ["BotState", "BotContext", "Position", "TradeStats"]
