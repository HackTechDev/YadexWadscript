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
