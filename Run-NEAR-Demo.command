#!/bin/zsh
set -eu
cd -- "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  print 'Python environment missing. Follow the clean-checkout setup in NEAR_DEMO.md.'
  exit 1
fi
export PYTHONPATH="$PWD"
exec .venv/bin/python -m privacy_layer.demo_server --port 0 --state "$PWD/.near-demo" "$@"
