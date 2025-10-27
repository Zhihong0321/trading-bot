"""Configuration objects for the trading bot."""

from __future__ import annotations

from datetime import time
from typing import Literal

from pydantic import BaseModel, Field, validator


class RiskConfig(BaseModel):
    """Risk related configuration parameters.

    Values follow the trading specification provided in the project brief.
    """

    capital: float = Field(300, description="Total deployable capital in USDT")
    risk_per_trade: float = Field(3, description="Dollar risk per trade")
    position_size: float = Field(75, description="Nominal position size per trade in USDT")
    stop_loss_pct: float = Field(0.003, description="Stop loss percentage as decimal")
    take_profit_pct: float = Field(0.0045, description="Take profit percentage as decimal")
    max_daily_loss: float = Field(9, description="Daily maximum drawdown in USDT")
    max_trades_per_day: int = Field(12, description="Maximum number of trades per day")
    cooldown_after_loss: int = Field(120, description="Cooldown seconds after a losing trade")
    cooldown_after_win: int = Field(60, description="Cooldown seconds after a winning trade")


class MarketFiltersConfig(BaseModel):
    """Market regime filters that gate trading activity."""

    active_hours_start: time = Field(time(6, 0), description="Start of active trading window (UTC)")
    active_hours_end: time = Field(time(22, 0), description="End of active trading window (UTC)")
    max_spread_pct: float = Field(0.0005, description="Maximum allowed bid/ask spread")
    max_atr_pct: float = Field(0.02, description="Maximum allowed hourly ATR as fraction of price")
    min_volume_multiplier: float = Field(
        1.3, description="Multiplier for minimum acceptable current volume vs average"
    )


class StrategyConfig(BaseModel):
    """Strategy level parameters."""

    symbol: Literal["ETHUSDT"] = "ETHUSDT"
    quantity_source: Literal["capital", "fixed"] = Field(
        "fixed", description="Whether to size positions from capital or fixed size"
    )
    limit_order_timeout: int = Field(15, description="Seconds before an unfilled entry order is cancelled")
    max_position_lifetime: int = Field(300, description="Seconds before a stale position is closed")
    break_even_trigger: float = Field(0.002, description="Profit percentage to move stop to break-even")

    @validator("symbol")
    def uppercase_symbol(cls, v: str) -> str:
        return v.upper()


class MonitoringConfig(BaseModel):
    """Operational monitoring configuration."""

    ping_latency_threshold_ms: int = Field(200, description="Latency threshold to Binance API in milliseconds")
    health_check_interval: int = Field(30, description="Interval in seconds to run background health checks")


class AppConfig(BaseModel):
    """Top-level application configuration."""

    environment: Literal["testnet", "production"] = Field(
        "testnet", description="Bot environment toggling between Binance testnet and production"
    )
    risk: RiskConfig = Field(default_factory=RiskConfig)
    filters: MarketFiltersConfig = Field(default_factory=MarketFiltersConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    data_directory: str = Field("./data", description="Path for persisting fetched data and logs")


DEFAULT_CONFIG = AppConfig()
"""Default configuration used by the bot."""


def load_config() -> AppConfig:
    """Return a default application configuration.

    In the future this can be extended to read from environment variables or files.
    """

    return DEFAULT_CONFIG.copy(deep=True)


__all__ = ["AppConfig", "RiskConfig", "MarketFiltersConfig", "StrategyConfig", "MonitoringConfig", "load_config"]
