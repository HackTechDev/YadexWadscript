# wadscript changelog

History of features implemented from `IMPROVEMENTS.md`'s backlog, in
the order they landed. `IMPROVEMENTS.md` stays focused on what's
*not* done yet; this file is where a finished entry's detail moves to.
See `README.md` for current behavior — this file explains how it got
there, not how to use it.

## Vocabulaire / tables curatées (`tables.py`)

`SECTOR_SPECIALS` (15 entries, verified against `ygd/doom2.ygd`),
`LINEDEF_SPECIALS` expanded (6 → 44 entries: full door set, lifts,
stairs, crushers, light effects, switch variants), `THING_TYPES`
expanded (~24 → 100 entries: every Doom II monster not specific to a
source port, remaining armor/ammo, decorations, obstacles), and
symbolic tags (`tag lift_ouest`, auto-assigned and kept consistent
between a `sector{}` and an `edge{}`, with a warning if a name is only
referenced once in the script — a likely typo). See README.md
("Curated symbol tables", "Symbolic tags") and
`examples/lift_symbolic_tag.wsl`, `examples/stairs.wsl`,
`examples/crusher.wsl`, `examples/secret_and_hazard.wsl`.

## Validation

Self-intersecting polygons detected (segment-vs-segment test, applied
to each loop independently — a sector's `points{}` and each of its
`holes{}` — with a clear error naming the two crossing edges), and
nested "donut" sectors supported via a new `holes{}` field on
`sector{}` (one more closed loop, subtracted from the sector's area;
its winding is normalized in the opposite direction from a normal
`points{}` loop, so it automatically comes out anti-parallel to the
enclosed island sector's own boundary — nothing special needed on the
island's side). Verified with a real nodebuilder (BSP 5.2), not just
`--dump-geometry` and Yadex. See README.md ("Nested sectors (donuts)")
and `examples/donut.wsl`.

Remaining gap, documented in README.md's "Known v1 limitations":
cross-loop overlap (a loop overlapping another without sharing exact
edges) isn't detected — only each individual loop's self-intersection
is.

**Thing outside any sector** (added after the above): every `thing`'s
`(x,y)` is now checked with a point-in-polygon test against every
sector's already-resolved loops (holes correctly subtracted -- a
point inside a hole with nothing declared there is outside every
sector, same as true unbounded void), and a non-fatal warning is
printed if it doesn't land inside any of them -- catches a stray
coordinate that would otherwise silently place a thing in the void.
See README.md ("How geometry is derived", step 6).

## Ergonomie du langage

Relative coordinates via a new `offset` field on `sector{}`
(`offset (dx,dy)` for a direct translation, or `offset relative_to
<sector> <direction> <gap>` computed from an already-declared
sector's bounding box — `gap 0` places two sectors flush, sharing a
wall exactly as if the coordinates had been computed by hand);
repeated geometry via `repeat <var> <count> { ... }` (nestable, loop
variable(s) usable in coordinate expressions with `+ - *` — points,
`offset`, `thing at`/`angle` — sector names auto-suffixed with the
iteration index/indices); texture/flat validation via `--check-textures
<iwad>`, which reads TEXTURE1/TEXTURE2 and the F_START..F_END lumps
directly out of a real IWAD/PWAD (`texcheck.py`, new module) and warns
(without blocking the write) for any name not found there. Verified
against a real `doom2.wad` (428 textures, 153 flats): all ten examples
in the folder pass with zero warnings. See README.md ("Relative
positioning (offset)", "Repeated geometry (repeat)", "Checking
textures against a real IWAD") and `examples/offset_relative.wsl`,
`examples/dungeon_grid.wsl`.

Deliberate restriction: only coordinates are expression-capable (not
`floor`/`ceiling`/`tag`/textures), so `repeat` stays a geometry-layout
tool rather than a general templating language.

**Symbolic directions for `angle`** (added after the above): a
`thing`'s `angle` now accepts `east`/`north`/`west`/`south` (0°/90°/
180°/270°, Doom's own convention), the same vocabulary `offset
relative_to` already used for directions -- and composes with
arithmetic (`angle north + 45`). Deliberately scoped to `angle` only:
every other expression context (`points{}`, `offset`, tags...) still
treats those four words as unknown names, so a stray direction can't
silently mean "0" in a coordinate. Inside a `repeat` whose loop
variable shares a direction's name, the loop variable wins (normal
shadowing). See README.md ("Symbolic directions").

**Reusable texture presets** (added after the above): a top-level
`texture_preset <name> { upper/lower/middle/x_offset/y_offset }`
block, referenced from a `texture{}` block with `preset <name>`. A
preset only fills a field the `texture{}` block itself left
unspecified -- any explicit field always wins over the preset,
regardless of write order within the block (verified both ways).
Presets can be declared anywhere relative to the edges using them (no
`relative_to`-style ordering rule, since a preset never depends on
other script state). `examples/three_rooms.wsl`'s door -- previously
the same three-line texture block repeated once per side, the exact
copy-paste-drift risk this closes -- now uses `preset door_frame` on
both sides; confirmed byte-for-byte identical resolved output
(`--dump-geometry` diff) before/after the change. See README.md
("Reusable texture presets").

**`include "path.wsl"`** (added after the above): merges another
file's `defaults{}`/`texture_preset{}`/(nested) `include` statements
into the current script, resolved relative to the *including* file's
own directory. Implemented in parser.py by recursively tokenizing and
parsing the included file with a `restricted=True` flag on
`parse_script()` that rejects anything else (`map`/`sector`/`edge`/
`thing`/`repeat`) with a clear error -- deliberately scoped to sharing
conventions only, not general-purpose inclusion, so merge order never
has to matter (unlike `offset relative_to`, which does depend on
declaration order). Exactly one `defaults{}` may exist across a script
and everything it includes; a second one anywhere is an error, same as
today. Cycle detection via a stack of resolved include paths. Verified
error paths: duplicate `defaults{}` (either direction), a disallowed
statement inside an included file, a missing file, and a circular
include -- all produce clear, nested `file:line` messages. See
README.md ("Sharing conventions across scripts (include)") and
`examples/common.wsl` + `examples/shared_level_a.wsl`/
`shared_level_b.wsl` (two different levels sharing one `common.wsl`).

## Génération procédurale

Five additions, all landing together since they share the same
underlying mechanism (`parser.py`'s materialization step, which already
turns `repeat` + `expr` into concrete int-valued AST nodes before
`geometry.py` ever runs):

**`/` and `%`** join `+ - *` in every `expr` (`parse_term`), with
Python's own integer semantics -- `/` truncates toward negative
infinity, `%` matches the sign of its right operand, division/modulo
by zero is a clear `WsParseError` instead of a crash.

**`const <name> = expr`**, a new top-level statement (also legal inside
an `include`d file, alongside `defaults{}`/`texture_preset{}`),
resolved immediately and then usable anywhere an `expr` is legal
exactly like a plain integer literal -- a `repeat` loop variable of the
same name still shadows it, same precedence a same-named direction
word already had. Duplicate detection spans the whole include tree,
the same as a duplicate `defaults{}`.

**`floor`/`ceiling`/`light` are now `expr`-valued** on a `sector{}`
(still plain `INT` on `defaults{}`, which has no `repeat` context to
speak of), closing the one gap `repeat`'s original "only coordinates
are expression-capable" restriction left: a `repeat`-generated
staircase can now write `floor s * 8` once instead of hand-duplicating
one near-identical sector per step, the way `stairs.wsl` still does.

**`random(min, max)`**, a new expression atom (`parse_atom`, recognized
by the `(` immediately following `random` so it never shadows a
same-named `const`/loop variable used without a call), draws one
inclusive integer from the script's shared RNG -- shared across an
entire `include` chain (the same `random.Random` instance is threaded
through every `_Parser`, top-level and included), so the draw sequence
only depends on `--seed` and call order, never on which file a
`random()` happens to be written in. `min > max` is a clear error, not
a silent swap or clamp. New `wadscript.py` flag `--seed <n>` seeds it;
omitted, every run draws from a fresh, non-reproducible seed. A script
that never calls `random()` is completely unaffected either way --
verified by diffing `--dump-geometry` output across repeated runs of
every existing example with no `random()` call, byte-identical every
time.

**`repeat ... rotate <angle> around <point>`**: iteration `i`'s own
contribution (every sector's points/holes, every edge override's
endpoints, every thing's position *and* facing angle) is rotated
`<angle> * i` degrees around `<point>` after that iteration's own body
is fully materialized (including any nested `repeat`, rotated or not,
resolved first) -- iteration 0 is always left exactly as written.
Multiples of 90 degrees use exact integer rotation (`dx, dy = -dy, dx`
per quarter-turn) so the common 4-fold/2-fold case never drifts off
the integer coordinate grid; any other angle rounds to the nearest map
unit. A sector using `offset relative_to` inside a rotated `repeat` is
a clear error (its anchor's bounding box isn't resolved until
`geometry.py` runs, well after rotation already happened here) -- a
literal `offset (dx,dy)` is folded into the sector's points before
rotating instead, so `geometry.py` never has to know rotation exists
at all.

See README.md ("Named constants", "Division and modulo", "Random
values", "Rotated repeats") and
[`examples/procedural.wsl`](examples/procedural.wsl) -- a four-armed
star dungeon combining all five: `const`/`/` for a shared, halved
corridor width, a `repeat`-built rising staircase with `expr`-valued
`floor` and `%`-alternating `light`, a `random()`-jittered ambush guard
and soulsphere per arm, and the whole arm turned into four with
`rotate 90 around (0,0)`. Verified the same way as every other example
in this folder: `--dump-geometry` (including a `--seed`-reproducibility
check), `--check-textures` against a real `doom2.wad`, BSP 5.2 node-
building, and a Yadex load -- zero warnings, zero errors.
