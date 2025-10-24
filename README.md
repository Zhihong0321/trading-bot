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

## Configuration

Default simulator configuration, cost presets, and risk limits are stored in [`config/defaults.toml`](config/defaults.toml). Update this file to change the seed values that the API surfaces.
