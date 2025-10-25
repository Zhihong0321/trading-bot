#!/usr/bin/env bash
set -euo pipefail

# Ensure pip is up to date before installing Poetry.
python3 -m pip install --upgrade pip

# Install Poetry if it is not already available in the image.
if ! command -v poetry >/dev/null 2>&1; then
  python3 -m pip install "poetry>=1.7,<1.9"
fi

# Configure Poetry to install into the system environment so Railway can execute commands directly.
poetry config virtualenvs.create false

# Install the application dependencies without developer tooling for lean deploy images.
poetry install --no-root --without dev --no-interaction --no-ansi
