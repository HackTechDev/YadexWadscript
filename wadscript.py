#!/usr/bin/env python3
"""wadscript - compile a small declarative DSL into a Doom-format PWAD.

Usage:
    python3 wadscript.py input.wsl -o output.wad [-m MAP01] [--dump-geometry]
"""

import argparse
import sys

from errors import WsError
from lexer import tokenize
from parser import parse
from geometry import resolve
from wadwriter import write_wad


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wadscript", description=__doc__)
    ap.add_argument("input", help="path to a .wsl source file")
    ap.add_argument("-o", "--output", required=True, help="path to the .wad file to write")
    ap.add_argument("-m", "--map", dest="map_name", default=None,
                     help="override the map lump name (default: from the script's `map` statement)")
    ap.add_argument("--dump-geometry", action="store_true",
                     help="print the resolved vertex/linedef/sidedef/sector/thing tables and exit "
                          "without writing a WAD")
    args = ap.parse_args(argv)

    with open(args.input, "r", encoding="utf-8") as f:
        source = f.read()

    try:
        tokens = tokenize(source)
        script = parse(tokens)
        level = resolve(script, map_name_override=args.map_name)
    except WsError as e:
        print(e.format(args.input), file=sys.stderr)
        return 1

    if args.dump_geometry:
        level.dump(sys.stdout)
        return 0

    write_wad(args.output, level)
    print(f"wrote {args.output}: {len(level.vertices)} vertices, {len(level.linedefs)} linedefs, "
          f"{len(level.sidedefs)} sidedefs, {len(level.sectors)} sectors, {len(level.things)} things")
    return 0


if __name__ == "__main__":
    sys.exit(main())
