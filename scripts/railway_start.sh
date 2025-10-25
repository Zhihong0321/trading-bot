#!/usr/bin/env bash
set -euo pipefail

# Railway provides the listening port via the PORT environment variable.
PORT="${PORT:-8000}"

# Ensure user-local Poetry installs are available on PATH.
export PATH="${HOME}/.local/bin:${PATH}"

exec poetry run uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT}"
