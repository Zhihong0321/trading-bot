"""Trading bot package."""

from trading_bot.bot import TradingBot
from trading_bot.config import load_config

__all__ = ["TradingBot", "load_config"]
