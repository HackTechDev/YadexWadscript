# wadscript

A small declarative DSL for describing Doom II level geometry
procedurally, compiled to a classic Doom-format single-level PWAD.
Standalone Python 3 tool, stdlib only, unrelated to Yadex's own C++
code or build — it just lives in this repo because Yadex is a
convenient way to load and inspect the WAD files it produces.

## Quick start

```sh
python3 wadscript.py examples/three_rooms.wsl -o /tmp/out.wad -m MAP01
../obj/0/yadex -g doom2 -pw /tmp/out.wad
# at the "yadex:" prompt: e map01
```

`--dump-geometry` prints the resolved vertex/linedef/sidedef/sector/
thing tables instead of writing a WAD — useful for sanity-checking a
script before loading it anywhere:

```sh
python3 wadscript.py examples/three_rooms.wsl -o /tmp/out.wad --dump-geometry
```

**Important**: the WAD this tool produces has empty SEGS/SSECTORS/
NODES/REJECT/BLOCKMAP lumps (same "needs rebuilding" convention Yadex
itself uses for a level whose nodes are stale). Run an external
nodebuilder (e.g. ZenNode, BSP — not part of this repo) on the output
before it's playable in vanilla `doom2.exe` or most source ports. Yadex
itself can open and edit a node-less level fine, which is why it's the
verification tool of choice here.

## The idea

The primary authoring unit is a **sector**: a closed polygon of (x,y)
points plus floor/ceiling attributes. Vertices and linedefs are
**derived automatically** from the polygons' edges:

- An edge that belongs to only one sector's polygon becomes a
  one-sided (impassible) wall.
- An edge shared by two sectors' polygons (same two endpoints) becomes
  a two-sided linedef, with front/back sidedefs assigned to the right
  sectors and upper/lower step textures inferred automatically from
  floor/ceiling height differences.

You never declare a vertex or a linedef directly. To attach a trigger
(a door, a switch, a teleport...) or custom textures to one specific
wall, target it by its two corner coordinates with an `edge{}` block —
the point order doesn't need to match how either sector declared it.

## Grammar

```
script      := { statement } ;
statement   := map_stmt | defaults_stmt | sector_stmt | edge_stmt | thing_stmt ;

map_stmt      := "map" STRING ;                      -- required, exactly once

defaults_stmt := "defaults" "{" { default_field } "}" ;
default_field := "floor" INT | "ceiling" INT
                | "floor_flat" STRING | "ceiling_flat" STRING
                | "wall_texture" STRING | "middle_texture" STRING
                | "light" INT ;

sector_stmt   := "sector" IDENT "{" { sector_field } "}" ;
sector_field  := "floor" INT | "ceiling" INT
                | "floor_flat" STRING | "ceiling_flat" STRING
                | "light" INT
                | "special" (IDENT | "raw" INT)
                | "tag" INT
                | "points" "{" point { point } "}" ;
point         := "(" INT "," INT ")" ;

edge_stmt     := "edge" point "-" point "{" { edge_field } "}" ;
edge_field    := "special" (IDENT | "raw" INT)
                | "tag" INT
                | "flags" "{" { IDENT } "}"
                | "texture" IDENT "{" { texture_field } "}" ;   -- IDENT = name of a bordering sector
texture_field := "upper" STRING | "lower" STRING | "middle" STRING
                | "x_offset" INT | "y_offset" INT ;

thing_stmt    := "thing" (IDENT | "raw" INT) "at" point "angle" INT
                  [ "flags" "{" { IDENT } "}" ] ;
```

Comments start with `#` and run to end of line. Points may be listed in
either winding order for a sector's `points{}` block — the geometry
pass normalizes it automatically.

### Escape hatch

Anywhere a symbolic name is expected (a linedef `special`, a `thing`
kind), `raw <int>` bypasses the curated table entirely, e.g.
`special raw 130` or `thing raw 3005 at (64,64) angle 0`.

### Defaults

`defaults{}` is optional; every field inside it is optional. Baseline
fallbacks if a field (or the whole block) is absent:

| Field | Fallback |
|---|---|
| `floor` | 0 |
| `ceiling` | 128 |
| `floor_flat` | `"FLOOR4_8"` |
| `ceiling_flat` | `"CEIL3_5"` |
| `wall_texture` | `"STARTAN3"` |
| `middle_texture` | `"-"` |
| `light` | 160 |

A `sector{}` block falls back to `defaults{}` for any field it omits.
A `thing`'s `flags` default to `easy|medium|hard` (appears on all
skills, all game modes) when omitted.

### Curated symbol tables

**Linedef specials** (`wadscript/tables.py::LINEDEF_SPECIALS`, verified
against `ygd/doom2.ygd`): `door_use` (1, DR, repeatable), `door_walk_once`
(4, W1), `lift` (88, WR, repeatable), `exit_level` (11, S-),
`exit_secret` (51, S-), `teleport` (39, W1).

**Thing types** (`tables.py::THING_TYPES`): `player1_start`..`player4_start`
(1-4), `deathmatch_start` (11), `zombieman` (3004), `shotgun_guy` (9),
`imp` (3001), `demon` (3002), `shotgun` (2001), `chaingun` (2002),
`rocket_launcher` (2003), `chainsaw` (2005), `clip` (2007), `shell`
(2008), `soulsphere` (2013), `health_bonus` (2014), `armor_bonus`
(2015), `medikit` (2012), `stimpack` (2011), `blue_keycard` (5),
`yellow_keycard` (6), `red_keycard` (13).

**Sector types** are not curated in v1 — `special` on a `sector{}`
block only accepts `raw <int>` (e.g. `special raw 9` for a secret
sector); a bare name always errors.

**Thing flags** (`THING_FLAG_BITS`): `easy`, `medium`, `hard`, `ambush`,
`not_sp`, `not_dm`, `not_coop`.

**Edge flags** (`LINEDEF_FLAG_BITS`): `block_monsters`, `secret`,
`block_sound`, `hidden` (never on automap), `mapped` (always on
automap), `upper_unpegged`, `lower_unpegged`. `impassible` and
`two_sided` are reserved — computed automatically, never settable.

Both tables only cover common cases; extend `tables.py` directly if you
need more, or use `raw <int>`.

## How geometry is derived

1. **Winding normalization.** Each sector's point list is reordered
   clockwise internally (via the shoelace signed-area formula) so a
   one-sided wall always has its owning sector on the correct side —
   you never have to think about point order when writing a script.
2. **Vertex table.** All (deduplicated) points across every sector
   become the WAD's VERTEXES lump, in first-seen order.
3. **Edge grouping.** Every sector contributes one directed edge per
   consecutive pair of its (normalized) points. Edges are grouped by
   their two (unordered) endpoints: one contributor → one-sided wall;
   two contributors (necessarily walked in opposite directions) →
   two-sided linedef, front = whichever sector was declared first in
   the script; more than two, or two contributors walked in the *same*
   direction (overlapping geometry) → a validation error.
4. **`edge{}` overrides** are matched to a derived edge by its two
   corner coordinates and merge their `special`/`tag`/`flags`/textures
   in. An override that doesn't match any real wall segment is an
   error, not a silent no-op.
5. **Texture defaulting** fills in whatever an override left
   unspecified: a one-sided wall gets `middle_texture` on `middle`; a
   two-sided one gets `middle_texture` on `middle` and `wall_texture`
   on `upper`/`lower` only where the two sectors' ceiling/floor heights
   actually differ (a step needs a texture, a flush opening doesn't).

## Known v1 limitations

Not validated or supported yet: level/thing bounds beyond int16 range
(this part *is* checked), self-intersecting polygons, nested "donut"
sectors (an interior island sector inside another, e.g. a pillar) —
the edge-derivation algorithm only understands simple polygon
adjacency, not enclosure.

## Layout

```
wadscript.py     CLI entrypoint
lexer.py         source text -> tokens
parser.py        tokens -> AST
tables.py        curated symbol tables
geometry.py      AST -> LevelData (winding, vertex dedup, edge derivation, texturing)
wadwriter.py     LevelData -> WAD bytes
errors.py        WsParseError / WsValidationError, with source line numbers
examples/        single_room.wsl, three_rooms.wsl
tests/           empty for now -- future pytest coverage would go here:
                  golden-byte tests for wadwriter.py, hand-computed
                  AST->LevelData cases for geometry.py
```
