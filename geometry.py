"""AST -> LevelData: winding normalization, vertex dedup, edge
derivation from sector polygons, override application, texture
defaulting.

See wadscript/README.md ("How geometry is derived") for the narrative
version of the algorithm implemented here.
"""

import sys
from dataclasses import dataclass, field

import tables
from errors import WsValidationError

INT16_MIN, INT16_MAX = -32768, 32767


# ------------------------------------------------------------ output ----

@dataclass
class LevelData:
    map_name: str
    vertices: list = field(default_factory=list)   # [(x,y), ...]
    linedefs: list = field(default_factory=list)    # [(start_v,end_v,flags,special,tag,sd1,sd2), ...]
    sidedefs: list = field(default_factory=list)     # [(xoff,yoff,upper,lower,middle,sector_idx), ...]
    sectors: list = field(default_factory=list)       # [(floor,ceil,ffl,cfl,light,special,tag), ...]
    things: list = field(default_factory=list)         # [(x,y,angle,doomednum,flags), ...]

    def dump(self, out=sys.stdout):
        print(f"map {self.map_name!r}", file=out)
        print(f"vertices ({len(self.vertices)}):", file=out)
        for i, v in enumerate(self.vertices):
            print(f"  {i}: {v}", file=out)
        print(f"sectors ({len(self.sectors)}):", file=out)
        for i, s in enumerate(self.sectors):
            print(f"  {i}: floor={s[0]} ceil={s[1]} floor_flat={s[2]!r} ceil_flat={s[3]!r} "
                  f"light={s[4]} special={s[5]} tag={s[6]}", file=out)
        print(f"sidedefs ({len(self.sidedefs)}):", file=out)
        for i, sd in enumerate(self.sidedefs):
            print(f"  {i}: xoff={sd[0]} yoff={sd[1]} upper={sd[2]!r} lower={sd[3]!r} "
                  f"middle={sd[4]!r} sector={sd[5]}", file=out)
        print(f"linedefs ({len(self.linedefs)}):", file=out)
        for i, ld in enumerate(self.linedefs):
            print(f"  {i}: v{ld[0]}->v{ld[1]} flags=0x{ld[2]:04x} special={ld[3]} tag={ld[4]} "
                  f"sd1={ld[5]} sd2={ld[6]}", file=out)
        print(f"things ({len(self.things)}):", file=out)
        for i, t in enumerate(self.things):
            print(f"  {i}: x={t[0]} y={t[1]} angle={t[2]} type={t[3]} flags=0x{t[4]:04x}", file=out)


# ------------------------------------------------------------- helpers ---

def _check_range(v, lo, hi, what, line):
    if not (lo <= v <= hi):
        raise WsValidationError(f"{what} {v} out of range [{lo},{hi}]", line)


def _check_name_len(s, what, line):
    if s is not None and len(s) > 8:
        raise WsValidationError(
            f"{what} {s!r} is longer than 8 characters and would be silently truncated in the WAD",
            line)


def _resolve_special_ref(ref, table, what, line):
    if ref is None:
        return 0
    if ref.kind == "raw":
        return ref.value
    if ref.value not in table:
        raise WsValidationError(
            f"unknown {what} {ref.value!r} (use 'raw <int>' for a value not in the curated table)",
            line)
    return table[ref.value]


def _resolve_flag_set(names, allowed_bits, reserved_bits, what, line):
    bits = 0
    for name in names:
        if name in reserved_bits:
            raise WsValidationError(
                f"{what} flag {name!r} is computed automatically and cannot be set explicitly", line)
        if name not in allowed_bits:
            raise WsValidationError(f"unknown {what} flag {name!r}", line)
        bits |= allowed_bits[name]
    return bits


class _TagResolver:
    """Resolves `tag` fields (int literal or symbolic str name) to final
    ints. A symbolic name gets one auto-assigned integer, consistent for
    every sector{}/edge{} in the script that uses that same name -- and
    never collides with an integer any part of the script used literally."""

    def __init__(self, script):
        self._used = set()
        for s in script.sectors:
            if isinstance(s.tag, int):
                self._used.add(s.tag)
        for e in script.edges:
            if isinstance(e.tag, int):
                self._used.add(e.tag)
        self._names = {}
        self._counts = {}
        self._next = 1

    def resolve(self, value):
        if isinstance(value, int):
            return value
        self._counts[value] = self._counts.get(value, 0) + 1
        if value in self._names:
            return self._names[value]
        while self._next in self._used:
            self._next += 1
        n = self._next
        self._names[value] = n
        self._used.add(n)
        self._next += 1
        return n

    def warn_unpaired(self):
        """A symbolic tag used only once total (in only one sector{} or
        edge{}, never linking the two) is almost certainly a typo on one
        side of what should have been a matching pair -- the exact
        copy-paste mistake symbolic tags are meant to catch."""
        for name, count in self._counts.items():
            if count == 1:
                print(
                    f"warning: tag {name!r} is only referenced once in the whole "
                    f"script -- a matching sector{{}} and edge{{}} both usually "
                    f"reference the same tag; check for a typo",
                    file=sys.stderr)


def _shoelace_area2(points):
    """Twice the signed area (avoids fractions); >0 = CCW, <0 = CW."""
    total = 0
    n = len(points)
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        total += x0 * y1 - x1 * y0
    return total


# -------------------------------------------------------- edge derivation

class _ResolvedEdge:
    __slots__ = ("key", "two_sided", "start_v", "end_v",
                 "front_sector", "back_sector",
                 "flags", "special", "tag",
                 "front_tex", "back_tex")

    def __init__(self, key):
        self.key = key
        self.two_sided = False
        self.start_v = None
        self.end_v = None
        self.front_sector = None
        self.back_sector = None
        self.flags = 0
        self.special = 0
        self.tag = 0
        self.front_tex = {"upper": None, "lower": None, "middle": None, "x_offset": 0, "y_offset": 0}
        self.back_tex = None


def _derive_edges(sector_points_by_name, sector_order, line_by_name):
    """Group directed candidate edges into resolved (1- or 2-sided) edges."""
    groups = {}  # frozenset({p1,p2}) -> [(sector_name, start, end), ...] in file order
    for name in sector_order:
        pts = sector_points_by_name[name]
        n = len(pts)
        for i in range(n):
            p0, p1 = pts[i], pts[(i + 1) % n]
            if p0 == p1:
                raise WsValidationError(
                    f"sector {name!r} has a zero-length edge at {p0}", line_by_name[name])
            key = frozenset((p0, p1))
            groups.setdefault(key, []).append((name, p0, p1))

    resolved = []
    for key, contributions in groups.items():
        e = _ResolvedEdge(key)
        if len(contributions) == 1:
            name, p0, p1 = contributions[0]
            e.two_sided = False
            e.start_v, e.end_v = p0, p1
            e.front_sector = name
            e.flags = tables.LINEDEF_IMPASSIBLE
            resolved.append(e)
        elif len(contributions) == 2:
            (nameA, p0A, p1A), (nameB, p0B, p1B) = contributions
            if p0A == p0B and p1A == p1B:
                raise WsValidationError(
                    f"sectors {nameA!r} and {nameB!r} both declare the edge "
                    f"{p0A}-{p1A} in the same direction (overlapping geometry?)",
                    line_by_name[nameA])
            # anti-parallel is guaranteed by construction (both directed
            # edges connect the same two points, and they differ, so they
            # must be reversed of one another) -- nothing else to check.
            e.two_sided = True
            e.start_v, e.end_v = p0A, p1A
            e.front_sector, e.back_sector = nameA, nameB
            e.flags = tables.LINEDEF_TWO_SIDED
            e.back_tex = {"upper": None, "lower": None, "middle": None, "x_offset": 0, "y_offset": 0}
            resolved.append(e)
        else:
            names = ", ".join(repr(c[0]) for c in contributions)
            raise WsValidationError(
                f"edge {tuple(key)} is shared by more than 2 sectors ({names}) -- not supported",
                line_by_name[contributions[0][0]])
    return resolved


# ------------------------------------------------------------- resolve ---

def resolve(script, map_name_override=None):
    map_name = map_name_override or script.map_name
    if not map_name:
        raise WsValidationError("no map name given (missing 'map \"...\"' statement, and no -m override)")
    _check_name_len(map_name, "map name", script.map_line)

    if not script.sectors:
        raise WsValidationError("script defines no sectors")

    tag_resolver = _TagResolver(script)

    d = script.defaults
    default_floor = d.floor if d and d.floor is not None else 0
    default_ceiling = d.ceiling if d and d.ceiling is not None else 128
    default_floor_flat = d.floor_flat if d and d.floor_flat is not None else "FLOOR4_8"
    default_ceiling_flat = d.ceiling_flat if d and d.ceiling_flat is not None else "CEIL3_5"
    default_wall_texture = d.wall_texture if d and d.wall_texture is not None else "STARTAN3"
    default_middle_texture = d.middle_texture if d and d.middle_texture is not None else "-"
    default_light = d.light if d and d.light is not None else 160
    for name, val, what in (
        ("floor_flat", default_floor_flat, "default floor_flat"),
        ("ceiling_flat", default_ceiling_flat, "default ceiling_flat"),
        ("wall_texture", default_wall_texture, "default wall_texture"),
        ("middle_texture", default_middle_texture, "default middle_texture"),
    ):
        _check_name_len(val, what, d.line if d else None)

    # -- sectors: validate polygons, normalize winding, resolve attrs --
    seen_names = set()
    sector_order = []
    sector_points_by_name = {}
    line_by_name = {}
    sector_attrs_by_name = {}

    for s in script.sectors:
        if s.name in seen_names:
            raise WsValidationError(f"duplicate sector name {s.name!r}", s.line)
        seen_names.add(s.name)

        if len(s.points) < 3:
            raise WsValidationError(f"sector {s.name!r} needs at least 3 points, got {len(s.points)}", s.line)
        for (x, y) in s.points:
            _check_range(x, INT16_MIN, INT16_MAX, "x coordinate", s.line)
            _check_range(y, INT16_MIN, INT16_MAX, "y coordinate", s.line)
        n = len(s.points)
        for i in range(n):
            if s.points[i] == s.points[(i + 1) % n]:
                raise WsValidationError(
                    f"sector {s.name!r} has two consecutive identical points {s.points[i]}", s.line)

        area2 = _shoelace_area2(s.points)
        if area2 == 0:
            raise WsValidationError(f"sector {s.name!r} is degenerate (zero area / collinear points)", s.line)
        points = list(reversed(s.points)) if area2 > 0 else list(s.points)

        sector_order.append(s.name)
        sector_points_by_name[s.name] = points
        line_by_name[s.name] = s.line

        floor = s.floor if s.floor is not None else default_floor
        ceiling = s.ceiling if s.ceiling is not None else default_ceiling
        floor_flat = s.floor_flat if s.floor_flat is not None else default_floor_flat
        ceiling_flat = s.ceiling_flat if s.ceiling_flat is not None else default_ceiling_flat
        light = s.light if s.light is not None else default_light
        special = _resolve_special_ref(s.special, tables.SECTOR_SPECIALS, "sector special", s.line)
        tag = tag_resolver.resolve(s.tag)
        _check_name_len(floor_flat, f"sector {s.name!r} floor_flat", s.line)
        _check_name_len(ceiling_flat, f"sector {s.name!r} ceiling_flat", s.line)
        _check_range(floor, INT16_MIN, INT16_MAX, "floor height", s.line)
        _check_range(ceiling, INT16_MIN, INT16_MAX, "ceiling height", s.line)
        _check_range(light, 0, 255, "light level", s.line)
        _check_range(special, INT16_MIN, INT16_MAX, "sector special", s.line)
        _check_range(tag, INT16_MIN, INT16_MAX, "sector tag", s.line)
        sector_attrs_by_name[s.name] = (floor, ceiling, floor_flat, ceiling_flat, light, special, tag)

    sector_index_by_name = {name: i for i, name in enumerate(sector_order)}

    # -- global (deduped) vertex table, built from normalized polygons --
    vertex_index = {}
    vertices = []
    for name in sector_order:
        for p in sector_points_by_name[name]:
            if p not in vertex_index:
                vertex_index[p] = len(vertices)
                vertices.append(p)

    # -- derive one/two-sided edges from sector polygon edges --
    resolved_edges = _derive_edges(sector_points_by_name, sector_order, line_by_name)
    edges_by_key = {e.key: e for e in resolved_edges}

    # -- apply `edge {}` overrides --
    for ov in script.edges:
        key = frozenset((ov.p1, ov.p2))
        e = edges_by_key.get(key)
        if e is None:
            raise WsValidationError(
                f"edge override {ov.p1}-{ov.p2} does not match any wall segment derived from the sectors",
                ov.line)
        if ov.special is not None:
            e.special = _resolve_special_ref(ov.special, tables.LINEDEF_SPECIALS, "linedef special", ov.line)
            _check_range(e.special, INT16_MIN, INT16_MAX, "linedef special", ov.line)
        if ov.tag is not None:
            e.tag = tag_resolver.resolve(ov.tag)
            _check_range(e.tag, INT16_MIN, INT16_MAX, "linedef tag", ov.line)
        if ov.flags:
            e.flags |= _resolve_flag_set(
                ov.flags, tables.LINEDEF_FLAG_BITS, tables.LINEDEF_FLAG_RESERVED, "linedef", ov.line)
        for sector_name, tex in ov.textures.items():
            if sector_name == e.front_sector:
                slot = e.front_tex
            elif e.two_sided and sector_name == e.back_sector:
                slot = e.back_tex
            else:
                borders = [n for n in (e.front_sector, e.back_sector) if n]
                raise WsValidationError(
                    f"sector {sector_name!r} does not border edge {ov.p1}-{ov.p2} "
                    f"(bordering sector(s): {', '.join(repr(b) for b in borders)})",
                    tex.line)
            for field_name in ("upper", "lower", "middle"):
                val = getattr(tex, field_name)
                if val is not None:
                    _check_name_len(val, f"texture {field_name}", tex.line)
                    slot[field_name] = val
            if tex.x_offset is not None:
                slot["x_offset"] = tex.x_offset
            if tex.y_offset is not None:
                slot["y_offset"] = tex.y_offset

    # -- texture defaulting for anything an override didn't set --
    for e in resolved_edges:
        if not e.two_sided:
            if e.front_tex["middle"] is None:
                e.front_tex["middle"] = default_wall_texture
            if e.front_tex["upper"] is None:
                e.front_tex["upper"] = "-"
            if e.front_tex["lower"] is None:
                e.front_tex["lower"] = "-"
        else:
            front_attrs = sector_attrs_by_name[e.front_sector]
            back_attrs = sector_attrs_by_name[e.back_sector]
            front_floor, front_ceil = front_attrs[0], front_attrs[1]
            back_floor, back_ceil = back_attrs[0], back_attrs[1]
            if e.front_tex["middle"] is None:
                e.front_tex["middle"] = default_middle_texture
            if e.back_tex["middle"] is None:
                e.back_tex["middle"] = default_middle_texture
            if e.front_tex["upper"] is None:
                e.front_tex["upper"] = default_wall_texture if front_ceil != back_ceil else "-"
            if e.front_tex["lower"] is None:
                e.front_tex["lower"] = default_wall_texture if front_floor != back_floor else "-"
            if e.back_tex["upper"] is None:
                e.back_tex["upper"] = default_wall_texture if back_ceil != front_ceil else "-"
            if e.back_tex["lower"] is None:
                e.back_tex["lower"] = default_wall_texture if back_floor != front_floor else "-"

    # -- build final SIDEDEFS + LINEDEFS lists --
    sidedefs = []
    linedefs = []
    for e in resolved_edges:
        front_idx = len(sidedefs)
        ft = e.front_tex
        sidedefs.append((ft["x_offset"], ft["y_offset"], ft["upper"], ft["lower"], ft["middle"],
                          sector_index_by_name[e.front_sector]))
        if e.two_sided:
            back_idx = len(sidedefs)
            bt = e.back_tex
            sidedefs.append((bt["x_offset"], bt["y_offset"], bt["upper"], bt["lower"], bt["middle"],
                              sector_index_by_name[e.back_sector]))
        else:
            back_idx = -1
        linedefs.append((
            vertex_index[e.start_v], vertex_index[e.end_v],
            e.flags, e.special, e.tag, front_idx, back_idx,
        ))

    # -- things --
    things = []
    has_player1_start = False
    for t in script.things:
        doomednum = _resolve_special_ref(t.kind_ref, tables.THING_TYPES, "thing type", t.line)
        if t.kind_ref.kind == "name" and t.kind_ref.value == "player1_start":
            has_player1_start = True
        _check_range(t.x, INT16_MIN, INT16_MAX, "thing x", t.line)
        _check_range(t.y, INT16_MIN, INT16_MAX, "thing y", t.line)
        _check_range(t.angle, 0, 359, "thing angle", t.line)
        flag_bits = (
            tables.THING_FLAGS_DEFAULT if t.flags is None
            else _resolve_flag_set(t.flags, tables.THING_FLAG_BITS, {}, "thing", t.line)
        )
        things.append((t.x, t.y, t.angle, doomednum, flag_bits))

    if not has_player1_start:
        print(f"warning: script has no 'thing player1_start ...' -- the level has no player 1 start",
              file=sys.stderr)
    tag_resolver.warn_unpaired()

    sectors = [sector_attrs_by_name[name] for name in sector_order]

    return LevelData(
        map_name=map_name,
        vertices=vertices,
        linedefs=linedefs,
        sidedefs=sidedefs,
        sectors=sectors,
        things=things,
    )
