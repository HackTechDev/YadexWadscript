"""Curated symbol -> numeric-ID tables for the wadscript DSL.

Values below are not guesses: they were cross-checked against
ygd/doom2.ygd (Yadex's own Doom II game-definition file) at the time
this tool was written. Anything not in these tables can still be
reached with the `raw <int>` escape hatch in the DSL.
"""

# Linedef specials (trigger type + action). Doom II numbering.
LINEDEF_SPECIALS = {
    "door_use": 1,          # DR - open, wait, close; repeatable, use-triggered
    "door_walk_once": 4,    # W1 - open, wait, close; walk-triggered, once
    "lift": 88,             # WR - lower lift, wait, raise; repeatable, walk-triggered
    "exit_level": 11,       # S- - end level, go to next map
    "exit_secret": 51,      # S- - end level, go to secret map
    "teleport": 39,         # W1 - teleport to another sector; walk-triggered, once
}

# Thing types (doomednum). Names favor common colloquial usage over
# Yadex's own terse sprite-based labels (e.g. "zombieman" not "Trooper").
THING_TYPES = {
    "player1_start": 1,
    "player2_start": 2,
    "player3_start": 3,
    "player4_start": 4,
    "deathmatch_start": 11,
    "zombieman": 3004,        # Trooper
    "shotgun_guy": 9,         # Sergeant
    "imp": 3001,
    "demon": 3002,
    "shotgun": 2001,
    "chaingun": 2002,
    "rocket_launcher": 2003,
    "chainsaw": 2005,
    "clip": 2007,
    "shell": 2008,             # 4 shotgun shells
    "soulsphere": 2013,        # Supercharge
    "health_bonus": 2014,
    "armor_bonus": 2015,
    "medikit": 2012,
    "stimpack": 2011,
    "blue_keycard": 5,
    "yellow_keycard": 6,
    "red_keycard": 13,
}

# Thing spawn-flags bits (WAD THINGS record, last field).
THING_FLAG_BITS = {
    "easy": 0x0001,
    "medium": 0x0002,
    "hard": 0x0004,
    "ambush": 0x0008,
    "not_sp": 0x0010,
    "not_dm": 0x0020,
    "not_coop": 0x0040,
}
THING_FLAGS_DEFAULT = THING_FLAG_BITS["easy"] | THING_FLAG_BITS["medium"] | THING_FLAG_BITS["hard"]

# Linedef flags bits (WAD LINEDEFS record). "impassible" and "two_sided"
# are computed by the geometry pass and may never be set by the user.
LINEDEF_FLAG_BITS = {
    "block_monsters": 0x0002,
    "upper_unpegged": 0x0008,
    "lower_unpegged": 0x0010,
    "secret": 0x0020,
    "block_sound": 0x0040,
    "hidden": 0x0080,   # never shown on the automap
    "mapped": 0x0100,   # always shown on the automap
}
LINEDEF_FLAG_RESERVED = {"impassible": 0x0001, "two_sided": 0x0004}

LINEDEF_IMPASSIBLE = 0x0001
LINEDEF_TWO_SIDED = 0x0004

# Sector types (special). Not curated for v1 -- no entry was verified
# against ygd/doom2.ygd yet, so a bare name always fails; use
# `special raw <int>` (e.g. `special raw 9` for a secret sector).
SECTOR_SPECIALS = {}
