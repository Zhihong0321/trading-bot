# trading-bot

Prototype backend for the EUR/USD 30-second signal simulator described in the project spec.

## Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/) for dependency management

## Setup

```bash
poetry install
```

## Running the API locally

```bash
poetry run uvicorn backend.app.main:app --reload
```

The API will be available at <http://127.0.0.1:8000>. Open <http://127.0.0.1:8000/docs> to interact with the automatically generated Swagger UI.

## Tests

```bash
poetry run pytest
```

## Railway deployment

The repository ships with infrastructure files that keep Railway deployments deterministic:

- [`nixpacks.toml`](nixpacks.toml) overrides the default Python plan so Nixpacks skips its preliminary `pip install .` (which expects a distributable package) and defers dependency resolution to Poetry.
- [`railway.toml`](railway.toml) declares Railway’s builder, build, and start commands.
- [`scripts/railway_build.sh`](scripts/railway_build.sh) provisions an in-project virtual environment, installs Poetry inside it, and resolves runtime dependencies there during the build.
- [`scripts/railway_start.sh`](scripts/railway_start.sh) activates the pre-built virtual environment before starting Uvicorn on Railway’s provided `PORT`.

To deploy the service:

1. In Railway, create a new project (or open an existing one) and add an empty service linked to this repository. Railway will automatically read `railway.toml` and wire up the build/start commands above.
2. (Optional, but recommended) Add a managed Postgres database to the project so the simulator can persist state in future milestones. No application configuration is required yet because the current prototype is stateless.
3. Trigger a deploy. Railway’s logs will show the virtual environment creation, dependency installation via Poetry, and the FastAPI startup message.

If you need to customise environment variables or scaling, edit `railway.toml` so the repo remains the source of truth for deployment settings.

## Configuration

Default simulator configuration, cost presets, and risk limits are stored in [`config/defaults.toml`](config/defaults.toml). Update this file to change the seed values that the API surfaces.
