"""Real-time and historical data feed for Binance ETH/USDT."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List

import aiohttp
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_fixed

LOGGER = logging.getLogger(__name__)

BINANCE_REST = "https://api.binance.com"
BINANCE_WS = "wss://stream.binance.com:9443/stream"
TESTNET_REST = "https://testnet.binance.vision"
TESTNET_WS = "wss://testnet.binance.vision/stream"


class DataFeedError(RuntimeError):
    """Raised when the websocket feed fails persistently."""


@dataclass
class Candle:
    """Represents a 1-minute candle."""

    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


async def fetch_historical_candles(
    session: aiohttp.ClientSession,
    symbol: str,
    limit: int = 500,
    base_url: str = BINANCE_REST,
) -> List[Candle]:
    """Fetch historical 1m candles for the symbol."""

    endpoint = f"{base_url}/api/v3/klines"
    params = {"symbol": symbol, "interval": "1m", "limit": min(limit, 1000)}
    async with session.get(endpoint, params=params, timeout=10) as resp:
        resp.raise_for_status()
        data = await resp.json()

    candles = []
    for entry in data:
        candles.append(
            Candle(
                open_time=datetime.fromtimestamp(entry[0] / 1000),
                open=float(entry[1]),
                high=float(entry[2]),
                low=float(entry[3]),
                close=float(entry[4]),
                volume=float(entry[5]),
            )
        )
    return candles


async def _ws_loop(url: str, streams: List[str]) -> AsyncGenerator[Dict[str, Any], None]:
    """Open a websocket connection and yield parsed messages."""

    stream_path = "/".join(streams)
    ws_url = f"{url}?streams={stream_path}"
    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        stop=stop_after_attempt(5),
        wait=wait_fixed(3),
        reraise=True,
    ):
        with attempt:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(ws_url, heartbeat=60) as ws:
                    LOGGER.info("Connected to Binance websocket: %s", ws_url)
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            yield json.loads(msg.data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            raise DataFeedError(f"Websocket error: {msg.data}")


async def stream_market_data(
    symbol: str,
    testnet: bool = False,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Stream combined kline, ticker, and bookTicker data."""

    base = TESTNET_WS if testnet else BINANCE_WS
    streams = [
        f"{symbol.lower()}@kline_1m",
        f"{symbol.lower()}@ticker",
        f"{symbol.lower()}@bookTicker",
    ]
    partial: Dict[str, Dict[str, Any]] = {}
    async for payload in _ws_loop(base, streams):
        data = payload.get("data", payload)
        stream_name = payload.get("stream", "")

        if "kline" in stream_name and "k" in data:
            partial["k"] = data["k"]
        elif stream_name.endswith("bookTicker"):
            partial["book"] = data
        elif stream_name.endswith("ticker"):
            partial["ticker"] = data

        if "k" in partial and "book" in partial:
            combined = {
                "k": partial["k"],
                "ticker": partial.get("ticker", {}),
                "book": partial["book"],
                "b": partial["book"].get("b"),
                "a": partial["book"].get("a"),
            }
            yield combined


async def check_ping_latency(base_url: str = BINANCE_REST) -> float:
    """Measure REST latency for monitoring."""

    start = datetime.utcnow()
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base_url}/api/v3/ping", timeout=5) as resp:
            resp.raise_for_status()
            await resp.text()
    end = datetime.utcnow()
    return (end - start).total_seconds() * 1000


__all__ = ["Candle", "fetch_historical_candles", "stream_market_data", "check_ping_latency", "DataFeedError"]
