#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
if [[ ! -f samples/cedar_ridge_sld_demo.pdf ]]; then
  .venv/bin/python samples/generate_sample_sld.py
fi
export PYTHONPATH=.
echo "GridPilot → http://127.0.0.1:${PORT:-8000}/app  (demo@gridpilot.dev / gridpilot)"
exec .venv/bin/uvicorn backend.app.main:app --reload --host 0.0.0.0 --port "${PORT:-8000}"
