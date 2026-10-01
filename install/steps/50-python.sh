#!/bin/bash
# Python environment for the federates, the experiment API and the tools.
# Usage: 50-python.sh <requirements.txt>
source "$(dirname "$0")/common.sh"
req=${1:?requirements.txt}
log "Python environment in $PREFIX/venv"
[ -x "$PREFIX/venv/bin/python" ] || python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --no-cache-dir --upgrade pip >/dev/null
"$PREFIX/venv/bin/pip" install --no-cache-dir -r "$req"
