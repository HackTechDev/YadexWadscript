"""Curated symbol -> numeric-ID tables for the wadscript DSL.

Values below are not guesses: they were cross-checked against
ygd/doom2.ygd (Yadex's own Doom II/Final Doom game-definition file) at
the time this tool was written. Anything not in these tables can still
be reached with the `raw <int>` escape hatch in the DSL. Entries are
only included if ygd/doom2.ygd lists them without an [EDGE]/[MBF]/
source-port-specific tag -- i.e. they work in vanilla doom2.exe or any
source port, which matches this tool's "classic Doom/Doom II" target.
A few entries are tagged [Boom]: they need a Boom-compatible source
port (nearly all modern ones are), not strict vanilla doom2.exe -- kept
because the WAD binary layout is identical either way, only the
in-game interpretation of the special number differs.
"""

# ---------------------------------------------------------- linedef specials
# Trigger-method prefixes, as in ygd/doom2.ygd and Doom modding lore:
#   D = push/use, once, stays open   S = switch, once     W = walk, once
#   DR = push/use, repeatable        SR = switch, repeat   WR = walk, repeat
LINEDEF_SPECIALS = {
    # -- doors --
    "door_use": 1,                    # DR - open, wait, close; repeatable, use-triggered
    "door_walk_once": 4,              # W1 - open, wait, close; walk-triggered, once
    "door_open_stay_walk_once": 2,    # W1 - open, stays open
    "door_close_walk_once": 3,        # W1 - close
    "door_close_30s_walk_once": 16,   # W1 - close, reopens itself after 30s
    "door_open_switch_once": 29,      # S1 - open, wait, close
    "door_open_stay_switch_once": 103,  # S1 - open, stays open
    "door_close_switch_once": 50,     # S1 - close
    "door_switch": 63,                # SR - open, wait, close; repeatable
    "door_open_stay_switch": 61,      # SR - open, stays open
    "door_close_switch": 42,          # SR - close
    "door_walk": 90,                  # WR - open, wait, close; repeatable
    "door_open_stay_walk": 86,        # WR - open, stays open
    "door_close_walk": 75,            # WR - close
    "door_close_30s_walk": 76,        # WR - close, reopens itself after 30s
    "door_use_blue_key": 26,          # DR - requires the blue keycard/skull key
    "door_use_yellow_key": 27,        # DR - requires the yellow keycard/skull key
    "door_use_red_key": 28,           # DR - requires the red keycard/skull key

    # -- lifts --
    "lift": 88,               # WR - lower lift, wait, raise; repeatable, walk-triggered
    "lift_switch_once": 21,   # S1 - lower lift, wait, raise; once
    "lift_switch": 62,        # SR - lower lift, wait, raise; repeatable

    # -- stairs (raise the tagged staircase sectors one step at a time) --
    "stairs_walk_once": 8,           # W1 - raise stairs (8-unit steps)
    "stairs_switch_once": 7,         # S1 - raise stairs (8-unit steps)
    "stairs_turbo_walk_once": 100,   # W1 - raise stairs, 16-unit steps, crushing
    "stairs_turbo_switch_once": 127,  # S1 - raise stairs, 16-unit steps, crushing

    # -- crushing ceilings --
    "crusher_start_walk_once": 6,   # W1 - start fast crushing, fast damage
    "crusher_start_walk": 77,       # WR - start fast crushing, fast damage; repeatable
    "crusher_start_slow_walk": 73,  # WR - start slow crushing, slow damage; repeatable
    "crusher_stop_walk_once": 57,   # W1& - stop a crusher on the tagged sector
    "crusher_stop_walk": 74,        # WR& - stop a crusher; repeatable

    # -- light effects --
    "light_blink_walk_once": 17,                    # W1 - start blinking lights
    "light_to_max_walk_once": 13,                    # W1 - light level to 255
    "light_to_max_walk": 81,                          # WR - light level to 255
    "light_to_max_switch": 138,                       # SR - light level to 255
    "light_to_dim_walk_once": 35,                     # W1 - light level to 35
    "light_to_dim_walk": 79,                          # WR - light level to 35
    "light_to_dark_switch": 139,                      # SR - light level to 0
    "light_to_brightest_neighbor_walk_once": 12,      # W1 - light to brightest neighbouring sector
    "light_to_darkest_neighbor_walk_once": 104,       # W1 - light to darkest neighbouring sector

    # -- exits --
    "exit_level": 11,       # S- - end level, go to next map
    "exit_secret": 51,      # S- - end level, go to secret map

    # -- teleporters --
    "teleport": 39,               # W1 - teleport to another sector; walk-triggered, once
    "teleport_switch_once": 174,  # S1 - teleport to another sector [Boom]
    "teleport_switch": 195,       # SR - teleport to another sector; repeatable [Boom]
}

# ------------------------------------------------------------------- things
# Thing types (doomednum). Names favor common colloquial usage over
# Yadex's own terse sprite-based labels (e.g. "zombieman" not "Trooper").
THING_TYPES = {
    # -- players / special markers --
    "player1_start": 1,
    "player2_start": 2,
    "player3_start": 3,
    "player4_start": 4,
    "deathmatch_start": 11,
    "teleport_exit": 14,       # marks a teleporter's destination spot

    # -- monsters --
    "zombieman": 3004,         # Trooper
    "shotgun_guy": 9,          # Sergeant
    "imp": 3001,
    "demon": 3002,
    "spectre": 58,
    "baron_of_hell": 3003,
    "hell_knight": 69,
    "cacodemon": 3005,
    "pain_elemental": 71,
    "lost_soul": 3006,
    "revenant": 66,
    "mancubus": 67,
    "arachnotron": 68,
    "arch_vile": 64,
    "cyberdemon": 16,
    "spider_mastermind": 7,
    "wolfenstein_ss": 84,
    "heavy_weapon_dude": 65,
    "boss_brain": 88,
    "boss_shooter": 89,
    "spawn_spot": 87,

    # -- weapons --
    "shotgun": 2001,
    "super_shotgun": 82,
    "chaingun": 2002,
    "rocket_launcher": 2003,
    "plasma_gun": 2004,
    "chainsaw": 2005,
    "bfg9000": 2006,

    # -- ammo --
    "clip": 2007,
    "box_of_bullets": 2048,
    "shell": 2008,              # 4 shotgun shells
    "box_of_shells": 2049,
    "rocket": 2010,
    "box_of_rockets": 2046,
    "energy_cell": 2047,
    "energy_cell_pack": 17,
    "backpack": 8,

    # -- health & armor --
    "soulsphere": 2013,         # Supercharge
    "health_bonus": 2014,
    "armor_bonus": 2015,
    "medikit": 2012,
    "stimpack": 2011,
    "armor": 2018,
    "megaarmor": 2019,
    "megasphere": 83,

    # -- keys --
    "blue_keycard": 5,
    "yellow_keycard": 6,
    "red_keycard": 13,
    "blue_skull_key": 40,
    "yellow_skull_key": 39,
    "red_skull_key": 38,

    # -- misc. bonus items --
    "radiation_suit": 2025,
    "computer_map": 2026,
    "partial_invisibility": 2024,
    "berserk": 2023,
    "invulnerability": 2022,
    "light_amp_visor": 2045,
    "evil_sceptre": 2016,       # Final Doom / Plutonia
    "unholy_bible": 2017,       # Final Doom / Plutonia

    # -- decorations & obstacles --
    "barrel": 2035,             # explodes when shot
    "commander_keen": 72,
    "technical_column": 48,
    "tall_green_pillar": 30,
    "tall_red_pillar": 32,
    "short_green_pillar": 31,
    "short_red_pillar": 33,
    "pillar_with_heart": 36,
    "red_pillar_with_skull": 37,
    "evil_eye": 41,
    "floating_skulls": 42,
    "brown_stub": 47,
    "brown_tree": 54,
    "grey_tree": 43,

    # -- corpses / gore decorations --
    "dead_player": 15,
    "dead_trooper": 18,
    "dead_sergeant": 19,
    "dead_imp": 20,
    "dead_demon": 21,
    "dead_cacodemon": 22,
    "pool_of_blood": 24,
    "impaled_body": 25,
    "pole_with_skull": 27,

    # -- light sources --
    "lamp": 2028,
    "tall_mercury_lamp": 85,
    "short_mercury_lamp": 86,
    "candle": 34,
    "candelabra": 35,
    "tall_blue_torch": 44,
    "tall_green_torch": 45,
    "tall_red_torch": 46,
    "short_blue_torch": 55,
    "short_green_torch": 56,
    "short_red_torch": 57,
    "burning_barrel": 70,
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

# Sector types (special).
SECTOR_SPECIALS = {
    "secret": 9,                    # counts toward the secrets tally

    # -- damaging floors --
    "damage_5pct": 7,                # -2/5% health per tic
    "damage_10pct": 5,               # -5/10% health per tic
    "damage_20pct": 16,              # -10/20% health per tic
    "damage_20pct_strobe": 4,        # -10/20% health per tic, fast-strobing light
    "damage_20pct_end_level": 11,    # -10/20% health; ends the level at <=10% health

    # -- light effects --
    "light_blink_random": 1,
    "light_strobe_fast": 2,          # flashes 2 Hz
    "light_strobe_slow": 3,          # flashes 1 Hz
    "light_strobe_slow_sync": 12,    # flashes 1 Hz, synchronized with other such sectors
    "light_strobe_fast_sync": 13,    # flashes 2 Hz, synchronized with other such sectors
    "light_glow": 8,                 # oscillates smoothly
    "light_flicker_random": 17,

    # -- timed door-like ceiling movement --
    "door_close_30s": 10,     # ceiling closes like a door, 30s after level start
    "door_open_300s": 14,     # ceiling opens like a door, 300s after level start
}
