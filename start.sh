#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.12 or 3.13 is required." >&2
  exit 1
fi
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
echo "Keep this terminal open. Visit the local address printed below."
exec .venv/bin/python run.py
