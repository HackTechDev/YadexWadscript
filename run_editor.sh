#!/bin/bash
# run_editor.sh -- launch the wadscript editor (editor.py).
#
# Usage: ./run_editor.sh [args...]
#   args  forwarded as-is to "python3 editor.py"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

exec python3 editor.py "$@"
