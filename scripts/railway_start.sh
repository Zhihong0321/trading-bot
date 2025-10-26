#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"

if [ ! -d "${VENV_DIR}" ]; then
  echo "Virtual environment not found at ${VENV_DIR}. Did the build step run?" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

PORT="${PORT:-8000}"

exec uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT}"
