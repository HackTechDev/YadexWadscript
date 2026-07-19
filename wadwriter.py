"""LevelData -> Doom-format single-level PWAD bytes.

Knows nothing about the DSL -- only about LevelData (plain tuples) and
the on-disk WAD layout, verified against Yadex's own writer
(src/levels.cc SaveLevelData(), src/wads.cc, src/wstructs.h):

  header (12B): "PWAD", int32 LE lump count, int32 LE directory offset
  directory entry (16B): int32 LE start, int32 LE size, 8-byte name

A single level is exactly 11 consecutive directory entries, in this
fixed order: label, THINGS, LINEDEFS, SIDEDEFS, VERTEXES, SEGS,
SSECTORS, NODES, SECTORS, REJECT, BLOCKMAP. SEGS/SSECTORS/NODES/
REJECT/BLOCKMAP are written zero-length -- an external nodebuilder
(ZenNode, BSP, ...) is expected to fill them in afterwards, same
convention Yadex itself uses for a level whose nodes need rebuilding.
"""

import struct

THING_FMT = "<hhhhh"        # x, y, angle, type, flags               (10 bytes)
LINEDEF_FMT = "<hhhhhhh"    # start_v, end_v, flags, special, tag, sd1, sd2  (14 bytes)
SIDEDEF_FMT = "<hh8s8s8sh"  # xoff, yoff, upper, lower, middle, sector (30 bytes)
VERTEX_FMT = "<hh"          # x, y                                    (4 bytes)
SECTOR_FMT = "<hh8s8shhh"   # floor, ceil, ffl, cfl, light, special, tag (26 bytes)

LUMP_NAMES = ["THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES",
              "SEGS", "SSECTORS", "NODES", "SECTORS", "REJECT", "BLOCKMAP"]


def _pack_name(name):
    """Uppercase, NUL-padded/truncated to exactly 8 bytes (matches
    Yadex's file_write_name(): only the first 8 chars are kept)."""
    return name.upper().encode("ascii")[:8].ljust(8, b"\0")


def write_wad(path, level):
    with open(path, "wb") as f:
        f.write(b"PWAD")
        f.write(struct.pack("<i", 11))
        dir_offset_pos = f.tell()
        f.write(struct.pack("<i", 0))  # patched below

        entries = []  # (name, start, size)

        # Label lump: zero-length marker carrying the map name.
        entries.append((level.map_name, f.tell(), 0))

        start = f.tell()
        for (x, y, angle, doomednum, flags) in level.things:
            f.write(struct.pack(THING_FMT, x, y, angle, doomednum, flags))
        entries.append(("THINGS", start, f.tell() - start))

        start = f.tell()
        for (sv, ev, flags, special, tag, sd1, sd2) in level.linedefs:
            f.write(struct.pack(LINEDEF_FMT, sv, ev, flags, special, tag, sd1, sd2))
        entries.append(("LINEDEFS", start, f.tell() - start))

        start = f.tell()
        for (xoff, yoff, upper, lower, middle, sector) in level.sidedefs:
            f.write(struct.pack(SIDEDEF_FMT, xoff, yoff,
                                 _pack_name(upper), _pack_name(lower), _pack_name(middle), sector))
        entries.append(("SIDEDEFS", start, f.tell() - start))

        start = f.tell()
        for (x, y) in level.vertices:
            f.write(struct.pack(VERTEX_FMT, x, y))
        entries.append(("VERTEXES", start, f.tell() - start))

        for name in ("SEGS", "SSECTORS", "NODES"):
            entries.append((name, f.tell(), 0))

        start = f.tell()
        for (floor, ceil, ffl, cfl, light, special, tag) in level.sectors:
            f.write(struct.pack(SECTOR_FMT, floor, ceil, _pack_name(ffl), _pack_name(cfl),
                                 light, special, tag))
        entries.append(("SECTORS", start, f.tell() - start))

        for name in ("REJECT", "BLOCKMAP"):
            entries.append((name, f.tell(), 0))

        assert len(entries) == 11, f"expected 11 directory entries, built {len(entries)}"

        dir_offset = f.tell()
        for (name, start, size) in entries:
            f.write(struct.pack("<ii", start, size))
            f.write(_pack_name(name))

        f.seek(dir_offset_pos)
        f.write(struct.pack("<i", dir_offset))
