"""Reads texture and flat names directly out of a real IWAD/PWAD, for
`wadscript.py --check-textures <iwad>` to catch typos (e.g. "STARTAN"
instead of "STARTAN3") against. Pure WAD-directory/lump reading --
unrelated to the wadscript DSL itself.

Texture names come from the TEXTURE1/TEXTURE2 lumps: each is a small
header (int32 count, then count int32 offsets into the same lump),
followed at each offset by a record starting with an 8-byte name --
that's all we need, the rest of the record (patch composition) is
irrelevant here. Flat names are just the lump names between the
F_START/FF_START and F_END/FF_END markers in the WAD directory --
flats have no lump-internal structure worth parsing.
"""

import struct


def read_directory(path):
    """Returns [(name, offset, size), ...] for every lump in the WAD."""
    with open(path, "rb") as f:
        header = f.read(12)
        if len(header) < 12:
            raise ValueError(f"{path}: too small to be a WAD file")
        magic = header[0:4]
        if magic not in (b"IWAD", b"PWAD"):
            raise ValueError(f"{path}: not a WAD file (bad magic {magic!r})")
        numlumps, dirofs = struct.unpack_from("<ii", header, 4)
        f.seek(dirofs)
        raw = f.read(16 * numlumps)
    if len(raw) < 16 * numlumps:
        raise ValueError(f"{path}: truncated directory")
    entries = []
    for i in range(numlumps):
        off, size, name = struct.unpack_from("<ii8s", raw, i * 16)
        name = name.split(b"\x00", 1)[0].decode("ascii", "replace").upper()
        entries.append((name, off, size))
    return entries


def read_lump_bytes(path, entries, name):
    """First lump named `name`, or None if there isn't one."""
    for lname, off, size in entries:
        if lname == name:
            with open(path, "rb") as f:
                f.seek(off)
                return f.read(size)
    return None


def parse_texture_names(data):
    if len(data) < 4:
        return set()
    (numtextures,) = struct.unpack_from("<i", data, 0)
    names = set()
    for i in range(numtextures):
        (off,) = struct.unpack_from("<i", data, 4 + 4 * i)
        name = data[off:off + 8].split(b"\x00", 1)[0].decode("ascii", "replace").upper()
        names.add(name)
    return names


def flat_names(entries):
    names = set()
    in_flats = False
    for name, off, size in entries:
        if name in ("F_START", "FF_START"):
            in_flats = True
        elif name in ("F_END", "FF_END"):
            in_flats = False
        elif in_flats:
            names.add(name)
    return names


def load_texture_and_flat_names(path):
    """Returns (texture_names, flat_names), both sets of str, read
    directly from the given IWAD/PWAD file."""
    entries = read_directory(path)
    textures = set()
    for lump_name in ("TEXTURE1", "TEXTURE2"):
        data = read_lump_bytes(path, entries, lump_name)
        if data:
            textures |= parse_texture_names(data)
    return textures, flat_names(entries)
