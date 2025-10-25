#!/usr/bin/env bash
set -euo pipefail

# Railway provides the listening port via the PORT environment variable.
PORT="${PORT:-8000}"

exec poetry run uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT}"
