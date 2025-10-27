"""Real-time and historical data feed for Binance ETH/USDT."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List

from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_fixed

LOGGER = logging.getLogger(__name__)

BINANCE_REST = "https://api.binance.com"
TESTNET_REST = "https://testnet.binance.vision"
@dataclass
class Candle:
    """Represents a 1-minute candle."""

    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


async def _async_json_request(url: str, params: Dict[str, Any] | None = None, timeout: float = 10.0) -> Any:
    """Execute an HTTP GET returning JSON using the standard library."""

    params = params or {}
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}" if query else url

    def _request() -> Any:
        request = urllib.request.Request(
            full_url,
            headers={
                "User-Agent": "TradingBot/0.1",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset("utf-8")
            data = response.read()
        return json.loads(data.decode(charset))

    return await asyncio.to_thread(_request)


async def fetch_historical_candles(
    symbol: str,
    limit: int = 500,
    base_url: str = BINANCE_REST,
) -> List[Candle]:
    """Fetch historical 1m candles for the symbol."""

    endpoint = f"{base_url}/api/v3/klines"
    params = {"symbol": symbol, "interval": "1m", "limit": min(limit, 1000)}
    data = await _async_json_request(endpoint, params=params)

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


async def fetch_candles_between(
    symbol: str,
    start_time: datetime,
    end_time: datetime,
    *,
    base_url: str = BINANCE_REST,
) -> List[Candle]:
    """Fetch candles between the provided timestamps (inclusive)."""

    if end_time <= start_time:
        return []

    endpoint = f"{base_url}/api/v3/klines"
    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)
    candles: List[Candle] = []
    current_start = start_ms

    while current_start < end_ms:
        params = {
            "symbol": symbol,
            "interval": "1m",
            "limit": 1000,
            "startTime": current_start,
            "endTime": end_ms,
        }
        batch = await _async_json_request(endpoint, params=params)
        if not batch:
            break

        for entry in batch:
            open_time = int(entry[0])
            if open_time < start_ms or open_time > end_ms:
                continue
            candles.append(
                Candle(
                    open_time=datetime.fromtimestamp(open_time / 1000),
                    open=float(entry[1]),
                    high=float(entry[2]),
                    low=float(entry[3]),
                    close=float(entry[4]),
                    volume=float(entry[5]),
                )
            )

        last_close = int(batch[-1][6])
        next_start = last_close + 1
        if next_start <= current_start:
            break
        current_start = next_start
        if len(batch) < 1000:
            break

    return candles


async def _retryable_json(url: str, params: Dict[str, Any] | None = None) -> Any:
    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type((urllib.error.URLError, TimeoutError)),
        stop=stop_after_attempt(5),
        wait=wait_fixed(2),
        reraise=True,
    ):
        with attempt:
            return await _async_json_request(url, params=params)


def _build_stream_payload(kline: List[Any], ticker: Dict[str, Any], book: Dict[str, Any]) -> Dict[str, Any]:
    close_time = int(kline[6])
    return {
        "k": {
            "t": int(kline[0]),
            "T": close_time,
            "o": kline[1],
            "c": kline[4],
            "h": kline[2],
            "l": kline[3],
            "v": kline[5],
        },
        "ticker": ticker,
        "book": book,
        "b": book.get("bidPrice"),
        "a": book.get("askPrice"),
    }


async def stream_market_data(
    symbol: str,
    testnet: bool = False,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Stream combined kline, ticker, and bookTicker data."""

    base_rest = TESTNET_REST if testnet else BINANCE_REST
    klines_endpoint = f"{base_rest}/api/v3/klines"
    ticker_endpoint = f"{base_rest}/api/v3/ticker/24hr"
    book_endpoint = f"{base_rest}/api/v3/ticker/bookTicker"

    last_close_time: int | None = None

    while True:
        klines = await _retryable_json(
            klines_endpoint,
            params={"symbol": symbol, "interval": "1m", "limit": 2},
        )
        if not klines:
            await asyncio.sleep(1)
            continue

        latest = klines[-1]
        close_time = int(latest[6])
        if last_close_time is not None and close_time == last_close_time:
            await asyncio.sleep(1)
            continue

        ticker = await _retryable_json(ticker_endpoint, params={"symbol": symbol})
        book = await _retryable_json(book_endpoint, params={"symbol": symbol})
        payload = _build_stream_payload(latest, ticker, book)
        yield payload
        last_close_time = close_time
        await asyncio.sleep(1)


async def check_ping_latency(base_url: str = BINANCE_REST) -> float:
    """Measure REST latency for monitoring."""

    start = datetime.utcnow()
    await _async_json_request(f"{base_url}/api/v3/ping", params={})
    end = datetime.utcnow()
    return (end - start).total_seconds() * 1000


__all__ = [
    "Candle",
    "fetch_historical_candles",
    "fetch_candles_between",
    "stream_market_data",
    "check_ping_latency",
]
