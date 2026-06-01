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

# Maximum XP earnable from the shop phase in a single day.
# Achieved by perfect performance (14/14 score) across all customers served.
# Calibrate during VS playtesting.
SHOP_XP_MAX = 5

# Bonus XP awarded per Huge Profit outcome.
# Rewards genuine excellence without making rarity tier the primary driver.
HUGE_PROFIT_BONUS = 1

# Maximum Huge Profit bonus XP earnable per day.
# Prevents a player from stacking bonuses across many customers.
HUGE_PROFIT_BONUS_CAP = 2

# ---------------------------------------------------------------------------
# Dungeon XP — per-node tranche system
# ---------------------------------------------------------------------------

# XP awarded per successful node resolution, by tranche.
# Tier 1: low-risk social/NPC nodes
# Tier 2: environmental/puzzle/cursed object nodes
# Tier 3: high-risk combat/trap/supernatural nodes
DUNGEON_NODE_XP = {
    "tier1": 1,   # Social, NPC Encounter
    "tier2": 2,   # Environmental, Puzzle, Cursed Object
    "tier3": 3,   # Combat, Trap, Supernatural
}

# Node type to tranche mapping — used by explore.py at resolution time
NODE_TRANCHE_MAP = {
    "social":        "tier1",
    "npc_encounter": "tier1",
    "environmental": "tier2",
    "puzzle":        "tier2",
    "cursed_object": "tier2",
    "combat":        "tier3",
    "trap":          "tier3",
    "supernatural":  "tier3",
    "discovery":     None,   # Discovery nodes award loot only — no XP
    "opening":       None,   # Opening node is atmospheric — no XP
}

# ---------------------------------------------------------------------------
# Shop Level XP thresholds
# ---------------------------------------------------------------------------

# XP required to advance from level N to level N+1.
# Level 1→2 = 30 XP (confirmed design decision).
# Day 1 target: ~9 XP total (shop ~4 + dungeon ~5) = "canon almost-level" moment.
# Calibrate full curve during VS playtesting.
SHOP_LEVEL_THRESHOLDS = {
    1:  30,    # Level 1 → 2  (roughly 3-4 days of daily play)
    2:  45,    # Level 2 → 3
    3:  60,    # Level 3 → 4
    4:  80,    # Level 4 → 5
    5:  100,   # Level 5 → 6
    6:  125,   # Level 6 → 7
    7:  150,   # Level 7 → 8
    8:  180,   # Level 8 → 9
    9:  210,   # Level 9 → 10
    10: 999,   # Level 10+ — post-VS calibration
}
