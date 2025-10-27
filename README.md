# Trading Bot Reset

This repository contains a fresh implementation of an ETH/USDT scalping bot built
to satisfy the "Conservative EMA Momentum Scalper" specification. It uses
Binance market data exclusively and emphasises risk management, observability,
and a clear separation between strategy evaluation and execution.

## Project Features

- **Binance Data Feed** – Streams 1-minute klines, ticker, and order book top
  levels using WebSockets. Includes utilities to download historical candles to
  seed indicators.
- **Strategy Engine** – Implements the refined scalping rule-set with EMA, RSI,
  spread, volume, cooldown, and daily guard-rail checks.
- **Risk Management** – Centralised module for position sizing, cooldown
  enforcement, and daily loss/trade limits.
- **State Machine** – Encodes bot lifecycle (`IDLE → PLACE_ENTRY →
  MANAGE_POSITION → COOLDOWN`) with support for halting on safety triggers.
- **Execution Layer** – Provides async wrappers around order placement,
  placeholder logic for OCO orders, and position timeout handling.
- **Configuration** – Pydantic models mirroring the specification parameters
  (capital, risk per trade, limits, monitoring thresholds, etc.).
- **Logging Utilities** – Simple helper for persistent logging to disk.

## Getting Started

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# or install the package in editable mode
pip install -e .
```

Set your Binance API credentials as environment variables if you plan to extend
`TradeExecutor` with live order placement:

```bash
export BINANCE_API_KEY="your-key"
export BINANCE_API_SECRET="your-secret"
```

## Running the Bot

```bash
python main.py
```

The entry point now hosts a lightweight HTTP status server (compatible with
Railway's platform expectations) in front of the background trading loop. The
root path (`GET /`) renders a live HTML dashboard, while `/status` and
`/healthz` expose JSON snapshots describing the bot state, balance, and last
update time.

By default the server listens on `PORT=8000`; Railway will inject the correct
port via environment variables during deployment. The bot operates against the
Binance testnet unless you export `BOT_ENV=production` before launching the
process.

## Deployment Notes

Railway Postgres settings from the previous project are intentionally
untouched. The bot itself is stateless, but you can extend it to persist trades
and analytics to your existing Railway database service.

## Next Steps

1. Finish the authenticated order placement logic inside `TradeExecutor`.
2. Persist trades, metrics, and logs for daily review.
3. Add unit tests covering the strategy and indicator components.
4. Build a dashboard (CLI or web) to monitor latency, PnL, and connection
   health in real time.

> **Disclaimer:** This code is provided for educational purposes. Trading
> cryptocurrencies carries risk; run extensive paper trading before deploying
> real capital.
