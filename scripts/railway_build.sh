#!/usr/bin/env bash
set -euo pipefail

# Ensure user-local binaries are on PATH for subsequent commands.
export PATH="${HOME}/.local/bin:${PATH}"

# Ensure pip is available in the user environment before installing Poetry.
if ! python3 -m pip --version >/dev/null 2>&1; then
  python3 -m ensurepip --upgrade --default-pip --user
fi
python3 -m pip install --upgrade --user pip

# Install Poetry into the user environment if it is not already available.
if ! command -v poetry >/dev/null 2>&1; then
  python3 -m pip install --user "poetry>=1.7,<1.9"
fi

# Create isolated virtual environments for dependencies inside the project directory.
poetry config virtualenvs.in-project true

# Install the application dependencies without developer tooling for lean deploy images.
poetry install --no-root --without dev --no-interaction --no-ansi
