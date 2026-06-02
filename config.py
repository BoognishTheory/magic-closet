import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# ---------------------------------------------------------------------------
# Cycle
# ---------------------------------------------------------------------------

CYCLE_DURATION_HOURS = 24

# ---------------------------------------------------------------------------
# Shop XP
# ---------------------------------------------------------------------------

SHOP_XP_MAX           = 5
HUGE_PROFIT_BONUS     = 1
HUGE_PROFIT_BONUS_CAP = 2

# ---------------------------------------------------------------------------
# Dungeon XP — per-node tranche system
# ---------------------------------------------------------------------------

DUNGEON_NODE_XP = {
    "tier1": 1,   # Social, NPC Encounter
    "tier2": 2,   # Environmental, Puzzle, Cursed Object
    "tier3": 3,   # Combat, Trap, Supernatural
}

NODE_TRANCHE_MAP = {
    "social":        "tier1",
    "npc_encounter": "tier1",
    "environmental": "tier2",
    "puzzle":        "tier2",
    "cursed_object": "tier2",
    "combat":        "tier3",
    "trap":          "tier3",
    "supernatural":  "tier3",
    "discovery":     None,
    "opening":       None,
}

# ---------------------------------------------------------------------------
# Shop Level XP thresholds
# ---------------------------------------------------------------------------

SHOP_LEVEL_THRESHOLDS = {
    1:  30,
    2:  45,
    3:  60,
    4:  80,
    5:  100,
    6:  125,
    7:  150,
    8:  180,
    9:  210,
    10: 999,
}

# ---------------------------------------------------------------------------
# Character Level win thresholds
# Wins required to advance from level N to level N+1.
# 1 win = 1 char_xp unit (combat win OR social win).
#
# Curve design:
#   Levels  1-5:  5 wins  (~1 level per day of active play early game)
#   Levels  6-10: 8 wins  (settling in)
#   Levels 11-15: 12 wins (invested player)
#   Levels 16-20: 17 wins
#   Levels 21-25: 23 wins
#   Levels 26-30: 30 wins
#   Levels 31-35: 38 wins
#   Levels 36-41: 47 wins
#   Level  42:    cap — no further progression
#
# Calibrate during VS playtesting. Target: ~7 wins/day, ~1 level/week early.
# ---------------------------------------------------------------------------

CHAR_LEVEL_THRESHOLDS = {
    # Levels 1-5: 5 wins each
    1: 5, 2: 5, 3: 5, 4: 5, 5: 5,
    # Levels 6-10: 8 wins each
    6: 8, 7: 8, 8: 8, 9: 8, 10: 8,
    # Levels 11-15: 12 wins each
    11: 12, 12: 12, 13: 12, 14: 12, 15: 12,
    # Levels 16-20: 17 wins each
    16: 17, 17: 17, 18: 17, 19: 17, 20: 17,
    # Levels 21-25: 23 wins each
    21: 23, 22: 23, 23: 23, 24: 23, 25: 23,
    # Levels 26-30: 30 wins each
    26: 30, 27: 30, 28: 30, 29: 30, 30: 30,
    # Levels 31-35: 38 wins each
    31: 38, 32: 38, 33: 38, 34: 38, 35: 38,
    # Levels 36-41: 47 wins each
    36: 47, 37: 47, 38: 47, 39: 47, 40: 47, 41: 47,
    # Level 42: cap — no further progression
    42: 999,
}

CHAR_LEVEL_CAP = 42

# Starting stats — used as display defaults until stat columns are added in Character Level Up
STARTING_STATS = {
    "vitality": 3,
    "brawn":    3,
    "charm":    2,
    "arcana":   3,
    "fortune":  3,
}
