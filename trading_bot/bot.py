"""Main bot orchestration module."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict

from trading_bot.config import AppConfig, load_config
from trading_bot.data.feed import BINANCE_REST, TESTNET_REST, fetch_historical_candles, stream_market_data
from trading_bot.state import BotContext, BotState
from trading_bot.strategy import Strategy
from trading_bot.trade_executor import TradeExecutor

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


class TradingBot:
    """Coordinates data, strategy evaluation, and execution."""

    def __init__(self, config: AppConfig | None = None):
        self.config = config or load_config()
        self.context = BotContext()
        self.strategy = Strategy(self.config, self.context)
        self.executor = TradeExecutor(self.config, self.context)
        self.balances: Dict[str, float] = {"USDT": self.config.risk.capital}

    async def prime_indicators(self) -> None:
        """Load historical candles to seed indicators."""

        base_url = TESTNET_REST if self.config.environment == "testnet" else BINANCE_REST
        candles = await fetch_historical_candles(self.config.strategy.symbol, limit=50, base_url=base_url)
        for candle in candles:
            payload = {
                "k": {
                    "c": candle.close,
                    "v": candle.volume,
                    "T": int(candle.open_time.timestamp() * 1000),
                },
                "b": candle.close,
                "a": candle.close,
            }
            self.strategy.update_indicators(payload)
        if candles:
            self.balances["last_candle_high"] = candles[-1].high
            self.balances["previous_candle_high"] = candles[-2].high if len(candles) > 1 else candles[-1].high
        else:
            self.balances["last_candle_high"] = 0.0
            self.balances["previous_candle_high"] = 0.0

    async def run(self) -> None:
        await self.prime_indicators()
        async with self.executor:
            async for payload in stream_market_data(
                self.config.strategy.symbol,
                testnet=self.config.environment == "testnet",
            ):
                if "k" not in payload:
                    continue
                previous_high = float(self.balances.get("last_candle_high", 0.0))
                snapshot = self.strategy.update_indicators(payload)
                self.balances["last_candle_high"] = float(payload["k"]["h"])
                self.balances["previous_candle_high"] = previous_high

                if not self.strategy.cooldown_ready():
                    continue

                if self.context.state == BotState.HALTED:
                    LOGGER.error("Trading halted: %s", self.context.halted_reason)
                    break

                if self.context.position and self.context.state == BotState.MANAGE_POSITION:
                    await self.executor.manage_position()
                    continue

                if self.strategy.entry_allowed(snapshot, self.balances):
                    position = self.strategy.create_entry(snapshot)
                    order = await self.executor.place_limit_buy(position.entry_price, position.quantity)
                    if order.status == "FILLED":
                        cost = order.price * order.quantity
                        self.balances["USDT"] -= cost
                        await self.executor.place_oco_sell(order.price, order.quantity)
                        self.context.transition(BotState.MANAGE_POSITION)
                        LOGGER.info("Position opened at %.2f", order.price)
                        # For the skeleton we simulate immediate take profit
                        pnl = order.quantity * order.price * self.config.risk.take_profit_pct
                        self.strategy.on_trade_result(pnl, True)
                        self.balances["USDT"] += cost + pnl


async def main() -> None:
    env = os.getenv("BOT_ENV", "testnet")
    config = load_config()
    config.environment = "production" if env == "production" else "testnet"
    bot = TradingBot(config)
    try:
        await bot.run()
    except KeyboardInterrupt:
        LOGGER.info("Bot stopped manually")


if __name__ == "__main__":
    asyncio.run(main())
