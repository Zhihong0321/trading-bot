#!/usr/bin/env bash
set -euo pipefail

# Ensure we are in project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

VENV_DIR="${PROJECT_ROOT}/.venv"

# Create a local virtual environment for dependencies if it does not exist.
if [ ! -d "${VENV_DIR}" ]; then
  python3 -m venv "${VENV_DIR}"
fi

# Activate the virtual environment.
# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

# Upgrade pip and install Poetry inside the virtual environment.
pip install --upgrade pip
pip install "poetry>=1.7,<1.9"

# Install application dependencies into the same virtual environment.
poetry config virtualenvs.create false
poetry install --no-root --without dev --no-interaction --no-ansi
