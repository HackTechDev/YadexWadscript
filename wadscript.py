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
import texcheck


def _check_textures(level, iwad_path):
    """Warn (to stderr, non-fatal) about texture/flat names the script
    uses that don't exist in the given IWAD/PWAD -- almost always a
    typo. "-" (no texture) is always skipped."""
    try:
        textures, flats = texcheck.load_texture_and_flat_names(iwad_path)
    except (OSError, ValueError) as e:
        print(f"warning: --check-textures {iwad_path}: {e}", file=sys.stderr)
        return
    seen = set()
    for sd in level.sidedefs:
        for name in (sd[2], sd[3], sd[4]):
            if name != "-" and name not in textures and name not in seen:
                seen.add(name)
                print(f"warning: texture {name!r} not found in {iwad_path}", file=sys.stderr)
    for s in level.sectors:
        for name in (s[2], s[3]):
            if name not in flats and name not in seen:
                seen.add(name)
                print(f"warning: flat {name!r} not found in {iwad_path}", file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wadscript", description=__doc__)
    ap.add_argument("input", help="path to a .wsl source file")
    ap.add_argument("-o", "--output", required=True, help="path to the .wad file to write")
    ap.add_argument("-m", "--map", dest="map_name", default=None,
                     help="override the map lump name (default: from the script's `map` statement)")
    ap.add_argument("--dump-geometry", action="store_true",
                     help="print the resolved vertex/linedef/sidedef/sector/thing tables and exit "
                          "without writing a WAD")
    ap.add_argument("--check-textures", metavar="IWAD", default=None,
                     help="warn (non-fatal) about texture/flat names not found in this IWAD/PWAD's "
                          "TEXTURE1/TEXTURE2 and F_START..F_END lumps")
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

    if args.check_textures:
        _check_textures(level, args.check_textures)

    if args.dump_geometry:
        level.dump(sys.stdout)
        return 0

    write_wad(args.output, level)
    print(f"wrote {args.output}: {len(level.vertices)} vertices, {len(level.linedefs)} linedefs, "
          f"{len(level.sidedefs)} sidedefs, {len(level.sectors)} sectors, {len(level.things)} things")
    return 0


if __name__ == "__main__":
    sys.exit(main())
