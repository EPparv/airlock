#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  PYTHON_BIN="$(command -v python3.12 || command -v python3 || true)"
  if [ -z "$PYTHON_BIN" ]; then
    echo 'Install Python 3.12 or later, then open this launcher again.'
    read -r -p 'Press Return to close.'
    exit 1
  fi
  "$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12 or later is required"'
  "$PYTHON_BIN" -m venv .venv
  .venv/bin/python -m pip install -r requirements.lock
fi
export PYTHONPATH=.
exec .venv/bin/python -m privacy_layer.memory_demo "$@"
