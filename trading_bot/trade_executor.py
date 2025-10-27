"""Order execution and position management logic."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional

from trading_bot.config import AppConfig
from trading_bot.state import BotContext, BotState

LOGGER = logging.getLogger(__name__)


@dataclass
class Order:
    """Represents an order placed with Binance."""

    order_id: Optional[int]
    symbol: str
    side: str
    price: float
    quantity: float
    status: str


class TradeExecutor:
    """Simplified wrapper around Binance order endpoints.

    The implementation is intentionally conservative and logs actions instead of
    placing live orders when API keys are not provided. Integration with the
    Binance REST API can be enabled by populating the environment variables
    `BINANCE_API_KEY` and `BINANCE_API_SECRET` and implementing the authenticated
    requests inside the placeholder methods.
    """

    def __init__(self, config: AppConfig, context: BotContext):
        self.config = config
        self.context = context

    async def __aenter__(self) -> "TradeExecutor":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def place_limit_buy(self, price: float, quantity: float) -> Order:
        LOGGER.info("Placing limit buy order at %.2f for quantity %.5f", price, quantity)
        await asyncio.sleep(0.1)
        return Order(order_id=None, symbol=self.config.strategy.symbol, side="BUY", price=price, quantity=quantity, status="FILLED")

    async def place_oco_sell(self, entry_price: float, quantity: float) -> Dict[str, Order]:
        tp_price = entry_price * (1 + self.config.risk.take_profit_pct)
        sl_price = entry_price * (1 - self.config.risk.stop_loss_pct)
        LOGGER.info(
            "Placing OCO sell orders TP %.2f SL %.2f for quantity %.5f", tp_price, sl_price, quantity
        )
        await asyncio.sleep(0.1)
        return {
            "take_profit": Order(None, self.config.strategy.symbol, "SELL", tp_price, quantity, "OPEN"),
            "stop_loss": Order(None, self.config.strategy.symbol, "SELL", sl_price, quantity, "OPEN"),
        }

    async def cancel_all(self) -> None:
        LOGGER.warning("Cancelling all open orders")
        await asyncio.sleep(0.1)

    async def manage_position(self) -> None:
        position = self.context.position
        if not position:
            return
        if time.time() - position.timestamp > self.config.strategy.max_position_lifetime:
            LOGGER.info("Closing position due to timeout")
            await self.cancel_all()
            self.context.transition(BotState.COOLDOWN)


__all__ = ["TradeExecutor", "Order"]
