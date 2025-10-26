# trading-bot

Prototype backend for the EUR/USD 30-second signal simulator described in the project spec.

## Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/) for dependency management
- (Optional, required for Dukascopy imports) Install the [`duka`](https://pypi.org/project/duka/) CLI in your environment via `pip install duka==0.2.3`. The package is not pinned in Poetry because it currently lacks Python 3.12 wheels, so install it manually anywhere you plan to run backfills.

## Setup

```bash
poetry install
```

## Running the API locally

```bash
poetry run uvicorn backend.app.main:app --reload
```

The API will be available at <http://127.0.0.1:8000>. Visiting the root path now renders an interactive dashboard where you can:

- launch simulations with the configured defaults (or ad-hoc parameters),
- choose the replay cadence (step mode through 20× fast-forward) via the new speed selector and quick buttons,
- watch the synthetic EUR/USD bid/ask feed, aggregate signal, and confidence update every bar,
- monitor equity, drawdown, and open-position state as trades are generated, and
- download the in-memory trade log.

The current prototype replays a deterministic sample dataset so the clock, prices, signal breakdown, and trades advance consistently—useful for validating dashboards and deployment plumbing before wiring in real market data.

Quick links to the generated docs remain available from the dashboard header.

### Historical data ingestion UI

Navigate to `/data-import` to drive Dukascopy backfills directly from the web UI:

- set the import window, volume aggregation policy, and whether to run a dry run or persist immediately;
- trigger the Dukascopy download/resample workflow, which validates the 30-second bars before optionally storing them in Postgres;
- inspect a rolling summary of the stored dataset; and
- re-run validation against a chosen slice of previously ingested candles.

> **Note:** The Dukascopy workflow depends on the [`duka`](https://pypi.org/project/duka/) CLI. Install it in the runtime environment with `pip install duka==0.2.3` before triggering an import; the UI surfaces the same reminder and the API will return a 503 with installation instructions if the CLI is missing.

The page surfaces detailed success/error messaging so failed imports can be diagnosed quickly. If the `duka` CLI is missing, the API will respond with a `503 Service Unavailable` error that explains how to install it; add the package to your local environment or Railway build step before retrying.

To enable persistence you **must** expose a Postgres connection string via `DATABASE_URL` (e.g. `postgresql+psycopg://user:pass@host:port/dbname`). When unset, imports operate in dry-run mode only. Local development can point `DATABASE_URL` at a temporary SQLite database (`sqlite:///./eurusd.db`) if Postgres is unavailable, but Railway deploys should use the managed Postgres instance you provision.

## Tests

```bash
poetry run pytest
```

## Railway deployment

The repository ships with infrastructure files that keep Railway deployments deterministic:

- [`nixpacks.toml`](nixpacks.toml) overrides the default Python plan so Nixpacks skips its preliminary `pip install .` (which expects a distributable package) and defers dependency resolution to Poetry. The setup phase brings in `python3Packages.virtualenv` so the build script can safely create a project-local virtualenv even on Nix-based images.
- [`railway.toml`](railway.toml) declares Railway’s builder, build, and start commands.
- [`scripts/railway_build.sh`](scripts/railway_build.sh) provisions an in-project virtual environment with `virtualenv`, installs Poetry inside it, and resolves runtime dependencies there during the build.
- [`scripts/railway_start.sh`](scripts/railway_start.sh) activates the pre-built virtual environment before starting Uvicorn on Railway’s provided `PORT`.

To deploy the service:

1. In Railway, create a new project (or open an existing one) and add an empty service linked to this repository. Railway will automatically read `railway.toml` and wire up the build/start commands above.
2. Provision a managed Postgres database (or connect to an existing one) and set the `DATABASE_URL` environment variable on the service. The data import UI and future persistence features rely on this connection string during deploys.
3. Trigger a deploy. Railway’s logs will show the virtual environment creation, dependency installation via Poetry, and the FastAPI startup message.

If you need to customise environment variables or scaling, edit `railway.toml` so the repo remains the source of truth for deployment settings.

## Configuration

Default simulator configuration, cost presets, and risk limits are stored in [`config/defaults.toml`](config/defaults.toml). Update this file to change the seed values that the API surfaces.
