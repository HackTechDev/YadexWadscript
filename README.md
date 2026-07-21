# wadscript

A small declarative DSL for describing Doom II level geometry
procedurally, compiled to a classic Doom-format single-level PWAD.
Standalone Python 3 tool, stdlib only — except for the optional GUI
editor (`editor.py`, see [GUI editor](#gui-editor)), which needs
[PySide6](https://pypi.org/project/PySide6/).

Originally developed inside [Yadex](https://github.com/farhaven/yadex),
a Doom/Doom II/Heretic/Hexen/Strife/ZDoom level editor for Unix/X11,
and extracted here as its own repository — wadscript itself is
unrelated to Yadex's C++ code or build, but Yadex remains a convenient
way to load and inspect the WAD files this tool produces (see
[Quick start](#quick-start) below), which is why the two are linked.

**Contents**: [Quick start](#quick-start) ·
[GUI editor](#gui-editor) ·
[The idea](#the-idea) ·
[Language reference](#language-reference) ·
[Advanced features](#advanced-features) ·
[How geometry is derived](#how-geometry-is-derived) ·
[Known v1 limitations](#known-v1-limitations) ·
[Larger examples](#larger-examples) ·
[Layout](#layout)

## Quick start

```sh
python3 wadscript.py examples/three_rooms.wsl -o /tmp/out.wad -m MAP01
/path/to/yadex/obj/0/yadex -g doom2 -pw /tmp/out.wad -map MAP01
```

(`obj/0/yadex` is Yadex's own build output — see
[github.com/farhaven/yadex](https://github.com/farhaven/yadex) for how
to build it; wadscript doesn't need Yadex installed to run, only to
visually inspect what it produces. `-map MAP01` loads that level
automatically at startup — without it, Yadex instead sits at its own
"yadex:" prompt, needing `e map01` typed by hand.)

`--dump-geometry` prints the resolved vertex/linedef/sidedef/sector/
thing tables instead of writing a WAD — useful for sanity-checking a
script before loading it anywhere:

```sh
python3 wadscript.py examples/three_rooms.wsl -o /tmp/out.wad --dump-geometry
```

`--check-textures <iwad>` warns (non-fatally — it still writes the
WAD) about `wall_texture`/`middle_texture`/flat names the script uses
that don't actually exist in that IWAD/PWAD, e.g. a typo'd
`"STARTAN"` instead of `"STARTAN3"`:

```sh
python3 wadscript.py examples/three_rooms.wsl -o /tmp/out.wad --check-textures /path/to/doom2.wad
```

`--seed <n>` makes `random(min,max)` (see "Random values" under
[Advanced features](#advanced-features)) reproducible — the same seed
always draws the same sequence. Irrelevant for a script that never
calls `random()`, which always compiles to the same output regardless.

**Important**: the WAD this tool produces has empty SEGS/SSECTORS/
NODES/REJECT/BLOCKMAP lumps (same "needs rebuilding" convention Yadex
itself uses for a level whose nodes are stale). Run an external
nodebuilder on the output before it's playable in vanilla `doom2.exe`
or most source ports — e.g.
[BSP 5.2](https://games.moria.org.uk/doom/bsp/), or ZenNode (not part
of this repo, `bsp <output>.wad -o <output>.wad` in place). Yadex
itself can open and edit a node-less level fine, which is why it's the
verification tool of choice here.

## GUI editor

`editor.py` is a small optional Qt text editor for `.wsl` scripts —
the only part of this repo that isn't stdlib-only, since it needs
[PySide6](https://pypi.org/project/PySide6/) (`pip install PySide6`):

```sh
python3 editor.py examples/three_rooms.wsl
```

Syntax highlighting (keywords, directions, strings, numbers, comments)
and line numbers, plus two actions that call the exact same
tokenize/parse/resolve pipeline `wadscript.py`'s CLI does — nothing
about the language or the compiler is reimplemented for the GUI:

- **Vérifier** (`Ctrl+Return`) runs the script and prints the resolved
  vertex/linedef/sidedef/sector/thing tables in the output pane at the
  bottom, the same as `--dump-geometry` — without writing anything.
- **Compiler vers .wad...** (`Ctrl+B`) runs the script and writes a WAD
  file (prompts for where). Needs the script saved to a real path
  first, the same way `include`'s relative paths need one. If a
  nodebuilder is configured (see below), it's then run on the WAD in
  place automatically — the exact `bsp <wad> -o <wad>` convention from
  [Quick start](#quick-start), just not a separate manual step anymore.
- **Lancer dans le moteur** (`Ctrl+R`) launches the configured Doom
  source port (see below) as `<engine> -file <wad>` on the most
  recently compiled WAD — plus `-iwad <iwad>` first, if an IWAD is
  configured.
- **Ouvrir dans l'éditeur de niveau** (`Ctrl+E`) launches the configured
  level editor (e.g. Yadex) as `<editor> -map <level> <wad>` on the
  most recently compiled WAD, `<level>` being the script's own `map
  "..."` name — Yadex's `-map` loads that level automatically at
  startup instead of leaving it to type `e <level_name>` itself at
  Yadex's own prompt (see [Quick start](#quick-start)). Plus `-g doom2
  -i2 <iwad>` first (Yadex's own flags for "game" and "Doom II/Final
  Doom iwad") if an IWAD is configured.

Either of the first two actions, on a `WsError`, prints
`file:line: error: message` (the same format the CLI uses) to the
output pane and jumps the editor to the offending line — the error's
line number is never guessed twice in two different places.

**Paramètres > Configurer...** sets four paths, persisted across runs
(via `QSettings`, e.g. `~/.config/wadscript/editor.conf` on Linux): the
nodebuilder binary (e.g. BSP, ZenNode), a Doom source port binary, a
level editor binary (e.g. Yadex), and an IWAD (e.g. `doom2.wad`). All
four are optional — leaving one blank just means "Compiler" skips the
automatic nodebuilder pass (same as before this existed), "Lancer..."/
"Ouvrir..." refuse with a clear message instead of launching nothing if
their own binary isn't set, and either launches without an explicit
IWAD if that one field alone is left blank (relying on whatever IWAD
the engine/editor defaults to on its own).

**Fichier > Fichiers récents** lists the last 10 scripts opened or
saved (most recent first, numbered `1` through `9` as mnemonics once
the submenu is open), also persisted via `QSettings` across runs. A
script whose file has since been moved or deleted is dropped from the
list the moment opening it actually fails, rather than left to fail
silently again on the next click; "Vider la liste" clears it outright.

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

## Language reference

```
script      := { statement } ;
statement   := map_stmt | defaults_stmt | texture_preset_stmt | const_stmt
             | include_stmt
             | sector_stmt | edge_stmt | thing_stmt | repeat_stmt ;

map_stmt      := "map" STRING ;                      -- required, exactly once

defaults_stmt := "defaults" "{" { default_field } "}" ;
default_field := "floor" INT | "ceiling" INT
                | "floor_flat" STRING | "ceiling_flat" STRING
                | "wall_texture" STRING | "middle_texture" STRING
                | "light" INT ;

texture_preset_stmt := "texture_preset" IDENT "{" { preset_field } "}" ;
preset_field  := "upper" STRING | "lower" STRING | "middle" STRING
                | "x_offset" INT | "y_offset" INT ;
                -- top-level only; see "Reusable texture presets" under
                   Advanced features

const_stmt    := "const" IDENT "=" expr ;
                -- top-level only; see "Named constants" under Advanced
                   features

include_stmt  := "include" STRING ;
                -- top-level only; the included file may itself only
                   contain defaults_stmt/texture_preset_stmt/const_stmt/
                   include_stmt -- see "Sharing conventions across
                   scripts (include)" under Advanced features

sector_stmt   := "sector" IDENT "{" { sector_field } "}" ;
sector_field  := "floor" expr | "ceiling" expr
                | "floor_flat" STRING | "ceiling_flat" STRING
                | "light" expr
                | "special" (IDENT | "raw" INT)
                | "tag" (INT | IDENT)
                | "points" "{" point { point } "}"
                | "holes" "{" { "{" point { point } "}" } "}"
                | "offset" (point | "relative_to" IDENT direction INT) ;
direction     := "east" | "west" | "north" | "south" ;
point         := "(" expr "," expr ")" ;

edge_stmt     := "edge" point "-" point "{" { edge_field } "}" ;
edge_field    := "special" (IDENT | "raw" INT)
                | "tag" (INT | IDENT)
                | "flags" "{" { IDENT } "}"
                | "texture" IDENT "{" { texture_field } "}" ;   -- IDENT = name of a bordering sector
texture_field := "upper" STRING | "lower" STRING | "middle" STRING
                | "x_offset" INT | "y_offset" INT
                | "preset" IDENT ;   -- name of a texture_preset; fields
                                        above still win over the preset,
                                        regardless of write order

thing_stmt    := "thing" (IDENT | "raw" INT) "at" point "angle" angle_expr
                  [ "flags" "{" { IDENT } "}" ] ;
angle_expr    := expr ;   -- but a bare `direction` is also a legal atom here
                             (unlike in a plain `expr`) -- see "Symbolic
                             directions" under Advanced features

repeat_stmt   := "repeat" IDENT INT "{" { sector_stmt | edge_stmt | thing_stmt | repeat_stmt } "}"
                  [ "rotate" expr "around" point ] ;
                 -- see "Repeated geometry (repeat)" and "Rotated repeats"
                    under Advanced features

expr          := term { ("+" | "-") term } ;
term          := unary { ("*" | "/" | "%") unary } ;
unary         := "-" unary | atom ;
atom          := INT | IDENT | "random" "(" expr "," expr ")" | "(" expr ")" ;
                 -- a bare IDENT is either a `const` name or (only inside a
                    repeat_stmt body) one of its loop variables; see
                    "Named constants" and "Random values" under Advanced
                    features
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

All numeric IDs below are cross-checked against
[`ygd/doom2.ygd`](https://github.com/farhaven/yadex/blob/master/ygd/doom2.ygd)
(Yadex's own Doom II/Final Doom game-definition file, not part of this
repo), not guessed.
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
`light_to_brightest_neighbor_walk_once`, etc.; see
[`examples/light_effects.wsl`](examples/light_effects.wsl)), exits
(2 — `exit_level`, `exit_secret`), teleporters (3 — `teleport`,
`teleport_switch`, `teleport_switch_once` `[Boom]`; see
[`examples/teleport.wsl`](examples/teleport.wsl) — like `lift`, a
tagged trigger, and the trigger edge itself must be a real two-sided
linedef, not a one-sided outer wall, for the player to walk across
it).

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
`not_sp`, `not_dm`, `not_coop`. Note that writing a thing's `flags{}`
block at all replaces the `easy|medium|hard` default rather than
adding to it — see [`examples/flags.wsl`](examples/flags.wsl).

**Edge flags** (`LINEDEF_FLAG_BITS`): `block_monsters`, `secret`,
`block_sound`, `hidden` (never on automap), `mapped` (always on
automap), `upper_unpegged`, `lower_unpegged`. `impassible` and
`two_sided` are reserved — computed automatically, never settable.
See [`examples/flags.wsl`](examples/flags.wsl) for both a thing's and
an edge's `flags{}` in the same script.

These tables only cover common cases; extend `tables.py` directly if
you need more (it's a plain Python dict), or use `raw <int>`.

## Advanced features

Everything below is opt-in — none of it is needed for the basic
sector/edge/thing scripts shown above.

### Checking textures against a real IWAD

Texture/flat names are otherwise just opaque strings to wadscript — a
truncation-to-8-characters check (`_check_name_len`), nothing more.
`--check-textures <iwad>` (see [Quick start](#quick-start)) closes
that gap: `texcheck.py` reads a WAD's `TEXTURE1`/`TEXTURE2` lumps
(each texture record starts with an 8-byte name — no need to
cross-reference `PNAMES` at all for just the names) and the lump names
between `F_START`/`FF_START` and `F_END`/`FF_END` (flats have no
lump-internal structure worth parsing — the lump name *is* the flat
name), then warns for every `wall_texture`/`middle_texture`/
upper/lower/middle/`floor_flat`/`ceiling_flat` the script uses that
isn't in either set. Non-fatal by design — a WAD referencing textures
supplied by a different PWAD than the one you happened to check
against is legitimate, so this is a linting aid, not a gate.

### Nested sectors (donuts)

A sector's `holes{}` block declares one or more extra closed loops
that are subtracted from its area — for a room with a pillar in the
middle, the room declares a `holes{}` loop with the pillar's exact
corner coordinates (in any point order — winding is normalized the
same way `points{}` is, just inverted), and the pillar itself is a
separate, ordinary sector. wadscript derives the shared boundary as a
normal two-sided wall, exactly as it would between two side-by-side
sectors — no special-casing needed on the pillar's side. See
[`examples/donut.wsl`](examples/donut.wsl).

A hole with no sector inside it is also valid: its edges just become
one-sided (impassible) walls facing into unrendered void, the same as
any other one-sided wall.

### Relative positioning (offset)

A sector's `points{}` (and `holes{}`) can be written in simple "local"
coordinates — a shape starting near `(0,0)` — and shifted into place
with an `offset` field, instead of hand-computing every absolute
coordinate:

- `offset (dx,dy)` — a plain translation.
- `offset relative_to <sector> <direction> <gap>` — computed
  automatically from an *already-declared* sector's bounding box:
  `direction` is `east`/`west`/`north`/`south`, `gap` is the distance
  between the two sectors' near edges (`0` places them flush, sharing
  a wall the same way two sectors declared with matching absolute
  coordinates would). See
  [`examples/offset_relative.wsl`](examples/offset_relative.wsl).

`relative_to` can only reference a sector declared earlier in the
script (its bounding box has to already be known) — referencing a
later or nonexistent sector is an error.

### Symbolic directions

A `thing`'s `angle` accepts the same `east`/`north`/`west`/`south`
vocabulary `offset relative_to` uses for directions, following Doom's
own convention (`east` = 0°, `north` = 90°, `west` = 180°,
`south` = 270°) — `thing zombieman at (64,64) angle north` instead of
having to remember that 0° faces east. A direction is a full
expression atom in this one spot, so it composes with arithmetic too:
`angle north + 45` is a diagonal facing, `angle west - 10` etc.

Directions are *only* recognized in `angle` — `points{}`, `offset`,
and every other expression context still treat `east`/`north`/`west`/
`south` as unknown names (an error), to avoid a stray direction word
silently meaning "0" in a coordinate. Inside a `repeat` whose loop
variable happens to be named `east` (or another direction word), the
loop variable wins — normal shadowing, not an error.

### Repeated geometry (repeat)

```
repeat <var> <count> {
  sector <name> { points { ... } }
  edge ... { ... }
  thing ... at (...) angle ...
  repeat <var2> <count2> { ... }   -- nesting is allowed
}
```

Runs its body `count` times, with `<var>` bound to `0, 1, ..., count-1`
each time. Inside the body (including a nested `repeat`'s own body),
`<var>` — and any enclosing `repeat`'s variable — can be used in
arithmetic expressions anywhere an `expr` is expected: a sector's
`points{}`/`holes{}`, `offset (dx,dy)`, and `floor`/`ceiling`/`light`;
an edge's endpoint points; or a thing's `at (x,y)` and `angle`.
Expressions support `+ - * / %`, `random(min,max)`, and parentheses,
e.g. `(i * 128, j * 128 + 16)` or `floor i * 8`.

`tag` and texture names stay plain literals, the same on every
iteration — a `tag` identifies a specific sector/edge pairing, so
letting it vary per iteration would defeat the point, and texture
names aren't numbers to begin with.

A `sector`'s name inside a `repeat` body automatically gets the
enclosing iteration index (or indices, for nested repeats) appended —
`sector cell { ... }` inside `repeat i 3 { repeat j 3 { ... } }`
produces `cell_0_0` through `cell_2_2` — since sector names must be
unique and the DSL has no string-interpolation syntax to build one by
hand. See [`examples/dungeon_grid.wsl`](examples/dungeon_grid.wsl) for
a 3x3 room grid generated (and auto-connected, via the usual
edge-sharing derivation) from one nested `repeat`.

**Lexer note**: because `-` is also the negative-number sign (maximal
munch, see `lexer.py`), write a space before a literal you're
subtracting inside an expression — `i - 1`, not `i-1`, which instead
lexes as the two tokens `i` and `-1` with no operator between them.

### Named constants

`const <name> = expr` declares a script-wide name for a value, resolved
immediately (it may reference an earlier `const`, but not a `repeat`
loop variable — none is in scope at the top level):

```
const HALL_WIDTH = 256
const HALF_WIDTH = HALL_WIDTH / 2

sector hall {
  points { (0,0) (HALL_WIDTH,0) (HALL_WIDTH,HALL_WIDTH) (0,HALL_WIDTH) }
}
```

A `const` is usable anywhere an `expr` is legal, including inside a
`repeat` body — but if a `repeat`'s own loop variable shares its name,
the loop variable wins (the same shadowing rule `angle north` already
follows for a same-named loop variable). `const` is also allowed inside
an `include`d file, alongside `defaults{}`/`texture_preset{}` — a
duplicate name anywhere across a script and everything it includes
(direct or nested) is an error, the same as a duplicate `defaults{}`.

### Division and modulo

`/` and `%` join `+ - *` in every `expr`. Both follow Python's own
integer semantics (there are no fractional values in this DSL, every
coordinate is an int): `/` truncates toward negative infinity, `%`
always has the same sign as its right operand, and `(a / b) * b + a %
b == a` always holds. Dividing or taking the modulo of anything by
zero is a clear error rather than a crash. `%` is the usual way to make
a `repeat` iteration alternate between two (or more) values, e.g.
`light 160 + (i % 2) * 40` for every other step lit brighter — see
[`examples/procedural.wsl`](examples/procedural.wsl).

### Random values

`random(min, max)` draws one integer from an inclusive range —
anywhere an `expr` is legal, not just inside a `repeat`:

```
thing imp at (128, random(32, 224)) angle west
```

By default every run of `wadscript.py` draws from a fresh,
non-reproducible seed, so a script using `random()` produces a
different level each time — that's the point. Pass `--seed <n>` to
make it reproducible (the same seed always draws the same sequence,
regardless of how many `random()` calls came before it or which file —
main script or `include`d — they're written in). **A script that never
calls `random()` is completely unaffected by `--seed`**: it always
compiles to byte-identical output, exactly as before this feature
existed.

`min > max` (e.g. `random(50, 10)`) is a clear error, not silently
swapped or clamped.

### Rotated repeats

A `repeat` can end with `rotate <angle> around <point>` to turn its
body into a rotationally-duplicated pattern instead of a purely
translated one — a star-shaped layout, spokes around a hub, that kind
of thing:

```
repeat i 4 {
  sector arm { points { ... } }
  thing imp at (...) angle west
} rotate 90 around (0,0)
```

Iteration `i`'s own contribution (every sector's points/holes, every
edge override's endpoints, every thing's position *and* facing angle)
is rotated `<angle> * i` degrees around `<point>` — iteration 0 is
never rotated, so it's exactly the geometry as written; iteration 1 is
turned `<angle>` degrees, iteration 2 is turned `<angle> * 2`, and so
on. Rotating a thing's facing angle by the same amount as its position
is what makes "face back toward the hub" (or any other relative
facing) come out correct on every arm without writing it out by hand
four times.

Rotations by an exact multiple of 90° are computed with exact integer
arithmetic (a 4-armed or 2-armed layout, the common case, never drifts
off the integer coordinate grid); any other angle is rounded to the
nearest map unit, same as any two adjacent sectors that don't happen to
land on exactly matching coordinates.

**A sector using `offset relative_to` cannot appear inside a rotated
`repeat`** — the anchor sector's bounding box isn't resolved until
`geometry.py` runs, well after rotation has already been applied here
in `parser.py` — a clear error is raised instead of silently ignoring
the rotation or the offset. A literal `offset (dx,dy)` works fine (it's
folded into the sector's points before rotating, same as if you'd
written the shifted coordinates by hand). Nesting is supported: a
nested `repeat` with no `rotate` of its own is rotated as a whole by
whichever enclosing `repeat` does have one.

See [`examples/procedural.wsl`](examples/procedural.wsl) for a
four-armed star dungeon combining this with `const`, `/`, `%`,
expression-valued `floor`/`ceiling`/`light`, and `random()` — every
feature in this section, in one script.

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

### Reusable texture presets

A top-level `texture_preset <name> { ... }` block declares a named set
of `upper`/`lower`/`middle`/`x_offset`/`y_offset` values, referenced
from a `texture{}` block with `preset <name>` instead of (or alongside)
writing the fields out directly:

```
texture_preset door_frame {
  upper "BIGDOOR2"
  middle "-"
  lower "-"
}

edge (256,0)-(256,192) {
  special door_use
  texture start { preset door_frame }
  texture hall  { preset door_frame }
}
```

A preset only fills whatever a `texture{}` block leaves unspecified —
any `upper`/`lower`/`middle`/`x_offset`/`y_offset` written explicitly
in the same block always wins over the preset, **regardless of which
comes first in the source** (`texture hall { preset door_frame upper
"BIGDOOR1" }` and `texture hall { upper "BIGDOOR1" preset door_frame }`
resolve identically). A `texture_preset` can be declared anywhere in
the script relative to the edges that use it — unlike `offset
relative_to`, there's no "must come first" ordering rule, since a
preset never depends on anything else being resolved yet.

See [`examples/three_rooms.wsl`](examples/three_rooms.wsl), whose door
edge uses exactly this to avoid repeating the same texture block twice
(previously the most common copy-paste-drift spot in a script — the
two sides of a door easily end up with subtly different textures if
edited by hand).

### Sharing conventions across scripts (include)

`include "path.wsl"` reads another `.wsl` file and merges its
`defaults{}` and `texture_preset{}` declarations into the current
script, as if they'd been written out at that point — the standard way
to keep several level scripts visually consistent (same default
textures, same door frame preset) without copy-pasting the same block
into every one of them:

```
# common.wsl
defaults {
  wall_texture "STARTAN3"
  light 160
}
texture_preset door_frame {
  upper "BIGDOOR2"
  middle "-"
  lower "-"
}
```

```
# level1.wsl
map "MAP01"
include "common.wsl"
sector room { points { ... } }
...
```

The path is resolved relative to the *including* file's own directory
(not the current working directory), so `include` chains work
regardless of where `wadscript.py` is invoked from. Nested `include`s
are allowed; a cycle is a clear error rather than an infinite loop.

**An included file may only contain `defaults{}`, `texture_preset{}`,
and (nested) `include` statements** — no `map`, `sector`, `edge`,
`thing`, or `repeat`. This is deliberate, not a v1 shortcut: it keeps
`include` doing exactly one job (sharing conventions), so merge order
never has to matter — unlike a sector's `offset relative_to`, which
depends on declaration order, a `defaults{}`/`texture_preset{}` can be
resolved regardless of where its `include` sits in the file. Exactly
one `defaults{}` may exist across a script and everything it includes
(direct or nested) — declaring it twice, whether both in `include`d
files or split between an include and the main script, is an error,
same as declaring it twice in one file.

See [`examples/common.wsl`](examples/common.wsl), shared by
[`examples/shared_level_a.wsl`](examples/shared_level_a.wsl) and
[`examples/shared_level_b.wsl`](examples/shared_level_b.wsl) — two
different layouts using the same defaults and door texture preset.

## How geometry is derived

Two passes happen before any of this, in `parser.py`, entirely outside
`geometry.py`'s view: every `repeat` is expanded into concrete
`sector`/`edge`/`thing` statements (loop variables substituted, sector
names suffixed with the iteration index, `rotate` applied to each
iteration's own contribution), and every `expr` — including a sector's
`floor`/`ceiling`/`light`, a `const` reference, or a `random()` call —
is evaluated to a plain int. `geometry.py` never sees a `repeat`, a
`const`, an unevaluated expression, or a rotation, only ordinary
int-valued AST nodes — as if the script had been written out longhand.

1. **Offset, then validation + winding normalization.** A sector's
   `offset` (a literal translation, or one computed from an
   already-processed sector's bounding box for `relative_to`) is
   applied to its `points{}`/`holes{}` first. Each resulting closed
   point loop is then checked for at least 3 points, no zero-length
   edges, non-zero area, and no self-intersection (two non-adjacent
   edges of the same loop crossing or overlapping) — then reordered
   clockwise internally (via the shoelace signed-area formula),
   inverted for a hole loop, so a one-sided wall always has its owning
   sector on the correct side. You never have to think about point
   order when writing a script.
2. **Vertex table.** All (deduplicated) points across every sector's
   loops become the WAD's VERTEXES lump, in first-seen order.
3. **Edge grouping.** Every loop contributes one directed edge per
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
6. **Things** resolve their symbolic kind to a doomednum and their
   `flags` the same way a linedef `special` does, then a point-in-
   polygon check (against every sector's already-resolved loops,
   holes included) warns — non-fatally — if a thing doesn't actually
   fall inside any sector. A hole with nothing declared inside it
   counts as outside every sector, same as true unbounded void.

## Known v1 limitations

Self-intersecting polygons are rejected with a clear error (checked
per loop — a sector's `points{}` or any of its `holes{}`), and nested
"donut" sectors are supported via `holes{}` (see above) — both were
v1 gaps, now closed. Still not validated or supported: cross-loop
overlap (a sector's own `holes{}` loop overlapping its outer boundary,
or two different sectors' loops overlapping without sharing exact
edges) is not detected — only each individual loop's self-intersection
is checked.

## Larger examples

Every example above isolates one feature at a time; these two chain
several together into a small, actually-connected level, closer to
what a real script looks like in practice:

- [`examples/combat_arena.wsl`](examples/combat_arena.wsl) — a door
  (texture preset), a donut room (cover pillar) with a `repeat`-
  generated firing line of monsters, a direct-trigger crusher, a
  staircase, and an exit. Demonstrates mixing plain absolute
  coordinates (needed for the donut room and its pillar, which must
  match exactly) with `offset relative_to` chaining for everything
  after it, where that exact-match constraint doesn't apply.
- [`examples/vault_complex.wsl`](examples/vault_complex.wsl) — a
  locked door (`door_use_blue_key`) opening onto a `secret` vault, a
  symbolically-tagged lift descending into a `damage_10pct` hazard,
  and an exit. Entirely `offset relative_to`-chained except for the
  edge `special`/`tag` overrides, which always target absolute
  coordinates regardless of how the bordering sectors got theirs.
- [`examples/relay_station.wsl`](examples/relay_station.wsl) — a
  tagged `teleport` linking two rooms with no shared geometry at all,
  an `offset relative_to`-chained corridor of `ambush`-flagged monsters
  under a continuous `light_flicker_random` (plus a one-shot
  `light_to_max_walk_once` on the way in), a `door_use_yellow_key`
  vault branch, and an `exit_secret` trigger carrying its own
  `flags { secret }`. Combines every feature `teleport.wsl`,
  `light_effects.wsl`, and `flags.wsl` isolate on their own into one
  connected level, the same way `combat_arena.wsl`/`vault_complex.wsl`
  do for the features before them.
- [`examples/procedural.wsl`](examples/procedural.wsl) — a four-armed
  star dungeon: one arm (a rising staircase built with expression-
  valued `floor`, a `random()`-jittered ambush guard, and a landing)
  written out once and turned into four with `repeat ... rotate`.
  Every feature under "Génération procédurale" in one script: `const`,
  `/` and `%`, expression-valued `floor`/`ceiling`/`light`, `random()`,
  and a rotated `repeat`.

All four were verified the same way as every other example in this
folder: `--dump-geometry` to check the resolved specials/tags/things
by hand, loaded in Yadex, and node-built with BSP 5.2 — zero
warnings, zero errors.

## Layout

```
wadscript.py     CLI entrypoint
editor.py        optional Qt (PySide6) GUI editor for .wsl scripts
lexer.py         source text -> tokens
parser.py        tokens -> AST (also expands `repeat`, evaluates expressions,
                 and resolves `include`)
tables.py        curated symbol tables
geometry.py      AST -> LevelData (offset, winding, vertex dedup, edge derivation, texturing)
wadwriter.py     LevelData -> WAD bytes
texcheck.py      reads TEXTURE1/TEXTURE2/flat names from a real IWAD, for --check-textures
errors.py        WsParseError / WsValidationError, with source line numbers
examples/        single_room.wsl, three_rooms.wsl, lift.wsl, lift_symbolic_tag.wsl,
                 stairs.wsl, crusher.wsl, secret_and_hazard.wsl, donut.wsl,
                 dungeon_grid.wsl, offset_relative.wsl, teleport.wsl,
                 light_effects.wsl, flags.wsl -- each isolates one feature;
                 combat_arena.wsl, vault_complex.wsl, relay_station.wsl, and
                 procedural.wsl chain several together into a small level
                 (see below); common.wsl + shared_level_a.wsl/shared_level_b.wsl
                 demonstrate `include`
tests/           empty for now -- future pytest coverage would go here:
                  golden-byte tests for wadwriter.py, hand-computed
                  AST->LevelData cases for geometry.py
IMPROVEMENTS.md  backlog of not-yet-implemented ideas
CHANGELOG.md     history of what was implemented from that backlog, and why
TUTORIAL.md      step-by-step guide (French)
```

Implementation history (what's been added since v1 and why) lives in
[`CHANGELOG.md`](CHANGELOG.md) — this README only documents current
behavior, not how it got here. Future work (not yet implemented) is
tracked in [`IMPROVEMENTS.md`](IMPROVEMENTS.md).
