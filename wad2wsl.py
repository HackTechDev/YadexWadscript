#!/usr/bin/env python3
"""wad2wsl - decompile a single-level Doom/Doom II PWAD back into a
wadscript .wsl source file (the reverse of wadscript.py).

Usage:
    python3 wad2wsl.py input.wad -o output.wsl [--map MAP01]

How a sector's polygon is recovered
------------------------------------
A WAD only stores LINEDEFS (two vertex indices + a front sidedef, and
optionally a back sidedef) and SIDEDEFS (which sector each belongs to).
wadscript's own geometry.py derives that structure the other way around
(sector polygon -> edges), so reversing it means reconstructing, for
each sector index, the closed polygon loop(s) whose boundary is exactly
the set of linedefs that reference it.

Each linedef contributes one directed edge per side: `v1 -> v2` to the
front sidedef's sector (Doom's own convention: a sidedef's sector lies
to the right of that direction), and `v2 -> v1` to the back sidedef's
sector, if any. Grouping those directed edges by sector and tracing
closed loops (at a branching vertex, always taking the next edge in
clockwise order from the one just arrived on -- the standard
"rightmost turn" rule for extracting faces from a planar edge set)
recovers exactly the polygon(s) wadscript would have produced as that
sector's `points{}` (plus one loop per `holes{}` entry, if any).

A sector whose loops are disjoint rather than nested (multiple wholly
separate pieces sharing one Doom sector number -- legal WAD data, but
not what a single `sector{}` block with `points{}`/`holes{}` can
express) is split into several `sector{}` blocks with identical
attributes (`s<N>`, `s<N>b`, `s<N>c`, ...); see `classify_sector_loops`.
"""

import argparse
import math
import struct
import sys
from collections import defaultdict

import tables

THING_FMT = "<hhhhh"
LINEDEF_FMT = "<hhhhhhh"
SIDEDEF_FMT = "<hh8s8s8sh"
VERTEX_FMT = "<hh"
SECTOR_FMT = "<hh8s8shhh"

LEVEL_LUMPS = ["THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES",
               "SEGS", "SSECTORS", "NODES", "SECTORS", "REJECT", "BLOCKMAP"]

_SECTOR_SPECIAL_NAMES = {v: k for k, v in tables.SECTOR_SPECIALS.items()}
_LINEDEF_SPECIAL_NAMES = {v: k for k, v in tables.LINEDEF_SPECIALS.items()}
_THING_TYPE_NAMES = {v: k for k, v in tables.THING_TYPES.items()}


# --------------------------------------------------------------- WAD reader

def _cstr(b):
    """Doom reads these as C strings: stop at the first NUL, ignore
    whatever garbage bytes (if any) follow it within the fixed field."""
    return b.split(b"\x00", 1)[0].decode("ascii", errors="replace")


def read_wad_directory(data):
    magic = data[0:4]
    if magic not in (b"PWAD", b"IWAD"):
        raise ValueError(f"not a WAD file (magic {magic!r})")
    numlumps, diroff = struct.unpack_from("<ii", data, 4)
    lumps = []
    for i in range(numlumps):
        off = diroff + i * 16
        lump_off, lump_size = struct.unpack_from("<ii", data, off)
        name = _cstr(data[off + 8:off + 16])
        lumps.append((name, lump_off, lump_size))
    return lumps


def find_level(lumps, map_name=None):
    """Locate a level marker lump immediately followed by the 10 standard
    level lumps in order, returning (map_name, {lump_name: (offset, size)})."""
    for i, (name, _off, size) in enumerate(lumps):
        if map_name is not None and name != map_name:
            continue
        following = [n for (n, _o, _s) in lumps[i + 1:i + 1 + len(LEVEL_LUMPS)]]
        if following == LEVEL_LUMPS:
            table = {n: (o, s) for (n, o, s) in lumps[i + 1:i + 1 + len(LEVEL_LUMPS)]}
            return name, table
    raise ValueError("no level found in this WAD" + (f" named {map_name!r}" if map_name else ""))


def parse_things(data, off, size):
    things = []
    for i in range(size // 10):
        x, y, angle, doomednum, flags = struct.unpack_from(THING_FMT, data, off + i * 10)
        things.append(dict(x=x, y=y, angle=angle, doomednum=doomednum, flags=flags))
    return things


def parse_linedefs(data, off, size):
    linedefs = []
    for i in range(size // 14):
        v1, v2, flags, special, tag, sd1, sd2 = struct.unpack_from(LINEDEF_FMT, data, off + i * 14)
        linedefs.append(dict(v1=v1, v2=v2, flags=flags, special=special, tag=tag, sd1=sd1, sd2=sd2))
    return linedefs


def parse_sidedefs(data, off, size):
    sidedefs = []
    for i in range(size // 30):
        xoff, yoff, upper, lower, middle, sector = struct.unpack_from(SIDEDEF_FMT, data, off + i * 30)
        sidedefs.append(dict(xoff=xoff, yoff=yoff, upper=_cstr(upper), lower=_cstr(lower),
                              middle=_cstr(middle), sector=sector))
    return sidedefs


def parse_vertexes(data, off, size):
    return [struct.unpack_from(VERTEX_FMT, data, off + i * 4) for i in range(size // 4)]


def parse_sectors(data, off, size):
    sectors = []
    for i in range(size // 26):
        floor, ceil, ffl, cfl, light, special, tag = struct.unpack_from(SECTOR_FMT, data, off + i * 26)
        sectors.append(dict(floor=floor, ceil=ceil, floor_flat=_cstr(ffl), ceiling_flat=_cstr(cfl),
                             light=light, special=special, tag=tag))
    return sectors


# --------------------------------------------------------- polygon recovery

def build_sector_loops(linedefs, sidedefs, vertices, n_sectors):
    """sector_idx -> list of loops; a loop is a list of edge-dicts
    {"a", "b", "ld_idx", "side"} walked in trace order, `a` being that
    edge's start point (the loop's own point list is [e["a"] for e in loop])."""
    edges_by_sector = defaultdict(list)
    for ld_idx, ld in enumerate(linedefs):
        v1, v2 = vertices[ld["v1"]], vertices[ld["v2"]]
        front_sector = sidedefs[ld["sd1"]]["sector"]
        edges_by_sector[front_sector].append(dict(a=v1, b=v2, ld_idx=ld_idx, side="front"))
        if ld["sd2"] != -1:
            back_sector = sidedefs[ld["sd2"]]["sector"]
            edges_by_sector[back_sector].append(dict(a=v2, b=v1, ld_idx=ld_idx, side="back"))

    return {idx: _trace_loops(edges_by_sector.get(idx, []), idx) for idx in range(n_sectors)}


def _trace_loops(edges, sector_idx):
    adjacency = defaultdict(list)
    for idx, e in enumerate(edges):
        adjacency[e["a"]].append(idx)

    visited = [False] * len(edges)
    loops = []
    for start_idx in range(len(edges)):
        if visited[start_idx]:
            continue
        start_vertex = edges[start_idx]["a"]
        loop_edges = []
        cur_idx = start_idx
        while True:
            visited[cur_idx] = True
            e = edges[cur_idx]
            loop_edges.append(e)
            prev_vertex, cur_vertex = e["a"], e["b"]
            if cur_vertex == start_vertex:
                break
            candidates = [i for i in adjacency[cur_vertex] if not visited[i]]
            if not candidates:
                raise ValueError(
                    f"sector {sector_idx}: dead end tracing its boundary at vertex "
                    f"{cur_vertex} (non-manifold sector geometry near linedef #{e['ld_idx']})")
            cur_idx = candidates[0] if len(candidates) == 1 else \
                _pick_rightmost_turn(prev_vertex, cur_vertex, edges, candidates)
        loops.append(loop_edges)
    return loops


def _pick_rightmost_turn(prev_vertex, at_vertex, edges, candidate_indices):
    """At a branching vertex, keep the sector's interior on the right by
    taking the next outgoing edge in clockwise order from the one we just
    arrived on -- the standard face-tracing rule for a planar edge set."""
    back_ang = math.atan2(prev_vertex[1] - at_vertex[1], prev_vertex[0] - at_vertex[0])
    best_idx, best_delta = None, None
    for idx in candidate_indices:
        v = edges[idx]["b"]
        ang = math.atan2(v[1] - at_vertex[1], v[0] - at_vertex[0])
        delta = (back_ang - ang) % (2 * math.pi)
        if best_delta is None or delta < best_delta:
            best_delta, best_idx = delta, idx
    return best_idx


def _loop_points(loop_edges):
    return [e["a"] for e in loop_edges]


def _shoelace_area2(points):
    total = 0
    n = len(points)
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        total += x0 * y1 - x1 * y0
    return total


def _point_in_polygon(px, py, poly):
    inside = False
    n = len(poly)
    x1, y1 = poly[-1]
    for i in range(n):
        x2, y2 = poly[i]
        if (y1 > py) != (y2 > py):
            x_intersect = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if px < x_intersect:
                inside = not inside
        x1, y1 = x2, y2
    return inside


def classify_sector_loops(loops):
    """Groups a sector's traced loops into pieces of (outer, [holes]).
    More than one piece means the Doom sector's geometry is disjoint,
    non-nested regions -- not expressible as a single `points{}` +
    `holes{}` block (see module docstring)."""
    if len(loops) <= 1:
        return [(loops[0], [])] if loops else []

    points = [_loop_points(loop) for loop in loops]
    areas = [abs(_shoelace_area2(p)) for p in points]
    n = len(loops)
    contains = [[False] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j and _point_in_polygon(points[j][0][0], points[j][0][1], points[i]):
                contains[i][j] = True

    parent = [None] * n
    for j in range(n):
        candidates = [i for i in range(n) if contains[i][j]]
        if candidates:
            parent[j] = min(candidates, key=lambda i: areas[i])

    tops = [i for i in range(n) if parent[i] is None]
    pieces = [(loops[t], [loops[j] for j in range(n) if parent[j] == t]) for t in tops]
    # A loop nested two-or-more levels deep (a hole inside a hole of the
    # *same* sector) can't be expressed either -- promote it to its own piece.
    for j in range(n):
        if parent[j] is not None and parent[j] not in tops:
            pieces.append((loops[j], []))
    return pieces


# -------------------------------------------------------------- text output

def _quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _fmt_point(p):
    return f"({p[0]},{p[1]})"


def _special_text(value, names_by_value):
    if value == 0:
        return None
    name = names_by_value.get(value)
    return name if name is not None else f"raw {value}"


def _thing_flags_text(flags):
    if flags == tables.THING_FLAGS_DEFAULT:
        return None
    names, remaining = [], flags
    for name, bit in tables.THING_FLAG_BITS.items():
        if flags & bit:
            names.append(name)
            remaining &= ~bit
    if remaining:
        print(f"warning: thing flags 0x{flags:04x} has unrecognized bit(s) "
              f"0x{remaining:04x} -- dropped", file=sys.stderr)
    return names


def _edge_flags_text(flags, two_sided):
    reserved = tables.LINEDEF_TWO_SIDED if two_sided else tables.LINEDEF_IMPASSIBLE
    extra, remaining = flags & ~reserved, flags & ~reserved
    if extra == 0:
        return None
    names = []
    for name, bit in tables.LINEDEF_FLAG_BITS.items():
        if extra & bit:
            names.append(name)
            remaining &= ~bit
    if remaining:
        print(f"warning: linedef flags has unrecognized bit(s) 0x{remaining:04x} -- dropped",
              file=sys.stderr)
    return names


def decompile(data, map_name=None):
    lumps = read_wad_directory(data)
    map_name, table = find_level(lumps, map_name)

    things = parse_things(data, *table["THINGS"])
    linedefs = parse_linedefs(data, *table["LINEDEFS"])
    sidedefs = parse_sidedefs(data, *table["SIDEDEFS"])
    vertices = parse_vertexes(data, *table["VERTEXES"])
    sectors = parse_sectors(data, *table["SECTORS"])

    n_sectors = len(sectors)
    loops_by_sector = build_sector_loops(linedefs, sidedefs, vertices, n_sectors)

    out = [f'# decompiled by wad2wsl.py -- {sum(len(v) for v in loops_by_sector.values())} '
           f'boundary loop(s) across {n_sectors} sector(s)', "", f"map {_quote(map_name)}", ""]

    piece_names_by_sector = {}   # sector_idx -> [piece_name, ...]
    edge_owner = {}              # (ld_idx, "front"|"back") -> piece_name

    suffixes = "abcdefghijklmnopqrstuvwxyz"
    for idx in range(n_sectors):
        pieces = classify_sector_loops(loops_by_sector[idx])
        names = [f"s{idx}" if len(pieces) == 1 else f"s{idx}{suffixes[p]}" for p in range(len(pieces))]
        piece_names_by_sector[idx] = names
        if len(pieces) > 1:
            print(f"warning: sector {idx} has {len(pieces)} disjoint piece(s) "
                  f"({', '.join(names)}) -- split into separate sector{{}} blocks, "
                  f"sharing that sector's attributes", file=sys.stderr)
        for name, (outer, holes) in zip(names, pieces):
            for e in outer:
                edge_owner[(e["ld_idx"], e["side"])] = name
            for hole in holes:
                for e in hole:
                    edge_owner[(e["ld_idx"], e["side"])] = name

    for idx in range(n_sectors):
        sec = sectors[idx]
        pieces = classify_sector_loops(loops_by_sector[idx])
        for name, (outer, holes) in zip(piece_names_by_sector[idx], pieces):
            out.append(f"sector {name} {{")
            out.append(f"  floor {sec['floor']}")
            out.append(f"  ceiling {sec['ceil']}")
            out.append(f"  floor_flat {_quote(sec['floor_flat'])}")
            out.append(f"  ceiling_flat {_quote(sec['ceiling_flat'])}")
            out.append(f"  light {sec['light']}")
            special = _special_text(sec["special"], _SECTOR_SPECIAL_NAMES)
            if special is not None:
                out.append(f"  special {special}")
            if sec["tag"] != 0:
                out.append(f"  tag {sec['tag']}")
            out.append("  points {")
            for p in _loop_points(outer):
                out.append(f"    {_fmt_point(p)}")
            out.append("  }")
            if holes:
                out.append("  holes {")
                for hole in holes:
                    pts = " ".join(_fmt_point(p) for p in _loop_points(hole))
                    out.append(f"    {{ {pts} }}")
                out.append("  }")
            out.append("}")
            out.append("")

    for ld_idx, ld in enumerate(linedefs):
        v1, v2 = vertices[ld["v1"]], vertices[ld["v2"]]
        two_sided = ld["sd2"] != -1
        front_name = edge_owner[(ld_idx, "front")]
        back_name = edge_owner.get((ld_idx, "back")) if two_sided else None

        out.append(f"edge {_fmt_point(v1)}-{_fmt_point(v2)} {{")
        special = _special_text(ld["special"], _LINEDEF_SPECIAL_NAMES)
        if special is not None:
            out.append(f"  special {special}")
        if ld["tag"] != 0:
            out.append(f"  tag {ld['tag']}")
        flag_names = _edge_flags_text(ld["flags"], two_sided)
        if flag_names is not None:
            out.append(f"  flags {{ {' '.join(flag_names)} }}")

        for side, name in (("front", front_name), ("back", back_name)):
            if name is None:
                continue
            sd = sidedefs[ld["sd1"] if side == "front" else ld["sd2"]]
            out.append(f"  texture {name} {{")
            out.append(f"    upper {_quote(sd['upper'])}")
            out.append(f"    lower {_quote(sd['lower'])}")
            out.append(f"    middle {_quote(sd['middle'])}")
            if sd["xoff"] != 0:
                out.append(f"    x_offset {sd['xoff']}")
            if sd["yoff"] != 0:
                out.append(f"    y_offset {sd['yoff']}")
            out.append("  }")
        out.append("}")
        out.append("")

    for t in things:
        kind = _THING_TYPE_NAMES.get(t["doomednum"])
        kind_text = kind if kind is not None else f"raw {t['doomednum']}"
        line = f"thing {kind_text} at {_fmt_point((t['x'], t['y']))} angle {t['angle']}"
        flag_names = _thing_flags_text(t["flags"])
        if flag_names is not None:
            line += f" flags {{ {' '.join(flag_names)} }}"
        out.append(line)

    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wad2wsl", description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="path to a single-level Doom/Doom II .wad file")
    ap.add_argument("-o", "--output", required=True, help="path to the .wsl file to write")
    ap.add_argument("--map", dest="map_name", default=None,
                     help="which level to decompile if the WAD holds more than one "
                          "(default: the only one, or an error if there's more than one)")
    args = ap.parse_args(argv)

    with open(args.input, "rb") as f:
        data = f.read()

    try:
        script_text = decompile(data, map_name=args.map_name)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(script_text)
    print(f"wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
