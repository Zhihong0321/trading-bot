#!/usr/bin/env bash
set -euo pipefail

# Ensure we are in project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

VENV_DIR="${PROJECT_ROOT}/.venv"

# Create a local virtual environment for dependencies if it does not exist.
if [ ! -d "${VENV_DIR}" ]; then
  if ! command -v virtualenv >/dev/null 2>&1; then
    echo "virtualenv is required but not available in PATH" >&2
    exit 1
  fi
  virtualenv --python=python3 "${VENV_DIR}"
fi

# Activate the virtual environment.
# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

# Upgrade pip and install Poetry inside the virtual environment.
pip install --upgrade pip
pip install "poetry>=1.7,<1.9"

# Install application dependencies into the same virtual environment.
export POETRY_VIRTUALENVS_CREATE=false
poetry install --no-root --without dev --no-interaction --no-ansi
