#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium

echo
echo "Setup complete. Activate the venv with:"
echo "  source .venv/bin/activate"
echo
echo "Then copy .env.example to .env and fill in your credentials:"
echo "  cp .env.example .env"
