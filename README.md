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
- **Logging & Simulation** – Persistent logging helper plus an interactive
  backtesting engine surfaced through the deployment dashboard.

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
root path (`GET /`) renders an interactive HTML dashboard with:

- Real-time bot status cards showing balance, last price, and environment.
- A historical simulation form that lets you choose a start/end window (up to
  seven days), tweak risk parameters, and launch a backtest directly from the
  browser.
- Tabular trade logs and JSON exports for each simulation run, allowing you to
  review entry/exit timing, PnL, and drawdowns.

Programmatic probes remain available via `/status` (JSON snapshot) and
`/healthz` (liveness). The latest simulation result can be fetched from
`/simulation.json`.

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
4. Persist simulation results to disk or a database for longitudinal analysis
   and comparison across parameter sweeps.

> **Disclaimer:** This code is provided for educational purposes. Trading
> cryptocurrencies carries risk; run extensive paper trading before deploying
> real capital.
