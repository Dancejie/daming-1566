#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! python3 -c "import openai" >/dev/null 2>&1; then
  echo "Installing Python dependency: openai"
  python3 -m pip install -r requirements.txt
fi

python3 server.py
