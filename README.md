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

### Direct triggers vs. tagged triggers

Two different trigger patterns show up in Doom levels, and both work
the same way here:

- **Direct**: the trigger linedef's own special acts on the sector it
  borders (or the sector it moves *into*, for a door). No `tag`
  needed — see `door_use` in `examples/three_rooms.wsl`.
- **Tagged**: the trigger linedef's special acts on whichever
  sector(s) share its `tag`, which may not be the sector the trigger
  linedef itself borders. Give the target sector a `tag` field, and
  put the same `tag` on the `edge{}` override carrying the `special`.
  `examples/lift.wsl` shows this for a `lift` special: the trigger
  edge is the entrance to the platform, tagged to match the platform
  sector so walking in lowers *that* sector, not the entrance's.

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
                | "tag" (INT | IDENT)
                | "points" "{" point { point } "}" ;
point         := "(" INT "," INT ")" ;

edge_stmt     := "edge" point "-" point "{" { edge_field } "}" ;
edge_field    := "special" (IDENT | "raw" INT)
                | "tag" (INT | IDENT)
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

### Symbolic tags

`tag` (on a `sector{}` or an `edge{}`) accepts either a literal integer
or an identifier, e.g. `tag 5` or `tag lift_ouest`. A name is
auto-assigned one integer, the first time it's seen, guaranteed not to
collide with any integer literal used elsewhere as a tag in the same
script; every later `tag <same name>` anywhere in the script — sector
or edge — reuses that same integer. See
[`examples/lift_symbolic_tag.wsl`](examples/lift_symbolic_tag.wsl).

This exists to catch a specific copy-paste mistake: a tag typo'd on
one side (the sector that should move, or the edge that triggers it)
silently compiles to a WAD where the trigger does nothing, because the
two integers just don't happen to match. A name makes that kind of
mismatch easier to *see*, and wadscript adds one more layer: if a
symbolic tag name is used only once in the entire script — meaning
nothing else in the script shares it — that's almost certainly a typo
on the other side, so a warning is printed (not a hard error, since a
one-off named tag isn't strictly invalid, just unusual).

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

All numeric IDs below are cross-checked against `ygd/doom2.ygd`
(Yadex's own Doom II/Final Doom game-definition file), not guessed.
Entries tagged `[Boom]` need a Boom-compatible source port (nearly all
modern ones are) rather than strict vanilla `doom2.exe` — the WAD
binary layout is identical either way, only which port interprets the
special number differs. The full, authoritative list with every name
is `wadscript/tables.py` — read it directly rather than this summary
when you need an exact name; use `raw <int>` for anything it doesn't
cover.

**Linedef specials** (`tables.py::LINEDEF_SPECIALS`, 44 entries):
doors (18 — `door_use`, `door_walk_once`, open/close/stay-open in every
trigger-method combination, plus `door_use_blue_key`/`_yellow_key`/
`_red_key`), lifts (3 — `lift`, `lift_switch`, `lift_switch_once`),
stairs (4 — `stairs_walk_once`, `stairs_switch_once`, and turbo
variants; see [`examples/stairs.wsl`](examples/stairs.wsl)), crushers
(5 — `crusher_start_walk_once`/`_walk`/`_start_slow_walk`,
`crusher_stop_walk_once`/`_walk`; see
[`examples/crusher.wsl`](examples/crusher.wsl)), light effects
(9 — `light_blink_walk_once`, `light_to_max_*`, `light_to_dim_*`,
`light_to_brightest_neighbor_walk_once`, etc.), exits (2 —
`exit_level`, `exit_secret`), teleporters (3 — `teleport`,
`teleport_switch`, `teleport_switch_once` `[Boom]`).

**Thing types** (`tables.py::THING_TYPES`, 100 entries): players/
markers (6, including `teleport_exit`), monsters (21 — every Doom II
monster except the source-port-specific mkII sprites, e.g.
`spectre`, `cacodemon`, `baron_of_hell`, `revenant`, `arch_vile`,
`cyberdemon`, `spider_mastermind`), weapons (7), ammo (9), health &
armor (8), keys (6, including skull keys), misc. bonus items (8),
decorations & obstacles (14 — pillars, torches' bases, barrels,
`commander_keen`...), corpses/gore (9), light sources (12 — lamps,
candles, torches).

**Sector types** (`tables.py::SECTOR_SPECIALS`, 15 entries): `secret`;
damaging floors `damage_5pct`/`_10pct`/`_20pct`/`_20pct_strobe`/
`_20pct_end_level`; light effects `light_blink_random`,
`light_strobe_fast`/`_slow` (and `_sync` variants), `light_glow`,
`light_flicker_random`; timed ceiling movement `door_close_30s`,
`door_open_300s`. Set directly on the `sector{}` block, not on a
trigger edge — see
[`examples/secret_and_hazard.wsl`](examples/secret_and_hazard.wsl).

**Thing flags** (`THING_FLAG_BITS`): `easy`, `medium`, `hard`, `ambush`,
`not_sp`, `not_dm`, `not_coop`.

**Edge flags** (`LINEDEF_FLAG_BITS`): `block_monsters`, `secret`,
`block_sound`, `hidden` (never on automap), `mapped` (always on
automap), `upper_unpegged`, `lower_unpegged`. `impassible` and
`two_sided` are reserved — computed automatically, never settable.

These tables only cover common cases; extend `tables.py` directly if
you need more (it's a plain Python dict), or use `raw <int>`.

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
examples/        single_room.wsl, three_rooms.wsl, lift.wsl, lift_symbolic_tag.wsl,
                 stairs.wsl, crusher.wsl, secret_and_hazard.wsl
tests/           empty for now -- future pytest coverage would go here:
                  golden-byte tests for wadwriter.py, hand-computed
                  AST->LevelData cases for geometry.py
```
