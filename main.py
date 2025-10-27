"""Command-line entry point for the trading bot."""

from __future__ import annotations

import asyncio
import logging
import os

from trading_bot.bot import TradingBot
from trading_bot.config import load_config


def configure_logging() -> None:
    """Configure root logging if no handlers are attached."""

    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )


def run() -> None:
    """Instantiate the bot and run its main loop."""

    configure_logging()

    env = os.getenv("BOT_ENV", "testnet").lower()
    config = load_config()
    config.environment = "production" if env == "production" else "testnet"

    bot = TradingBot(config)
    asyncio.run(bot.run())


if __name__ == "__main__":
    run()
