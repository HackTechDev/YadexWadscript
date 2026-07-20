#!/bin/bash
# compileWad.sh -- compile a wadscript .wsl file, build its BSP nodes,
# and drop the result into the gzdoom test directory for quick
# in-game testing.
#
# Usage: ./compileWad.sh [name]
#   name  a script under examples/, without the .wsl extension
#         (default: dungeon_grid)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GZDOOM_DIR="/home/util01/JEUX/DOOM/gzdoom-g4.11.3"
NAME="${1:-dungeon_grid}"
SRC="examples/${NAME}.wsl"
OUT="${NAME}.wad"

if [ ! -f "$SRC" ]; then
  echo "compileWad.sh: no such script: $SRC" >&2
  echo "usage: $0 [name]   (name = a .wsl file under examples/, without extension)" >&2
  exit 1
fi

if ! command -v bsp >/dev/null; then
  echo "compileWad.sh: 'bsp' not found in PATH (need a Doom nodebuilder, e.g. https://games.moria.org.uk/doom/bsp/)" >&2
  exit 1
fi

TMP_WAD="$(mktemp --suffix=.wad)"
trap 'rm -f "$TMP_WAD"' EXIT

echo "==> compiling $SRC"
python3 wadscript.py "$SRC" -o "$TMP_WAD" -m MAP01

echo "==> building nodes -> $OUT"
bsp "$TMP_WAD" -o "$OUT" -q

if [ -d "$GZDOOM_DIR" ]; then
  cp "$OUT" "$GZDOOM_DIR/"
  echo "==> copied $OUT to $GZDOOM_DIR"
else
  echo "compileWad.sh: warning: $GZDOOM_DIR not found, skipping copy" >&2
fi

echo "done: $OUT"
