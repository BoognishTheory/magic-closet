"""
game/run_manager.py
Core dungeon node resolution engine. No Discord imports.
Takes a run + node + choice + player, rolls outcome, returns result dict.

Stats affect encounter outcomes:
  Brawn   — combat encounter success rolls (+2.5% per point)
  Charm   — social encounter success rolls (+2.5% per point)
  Arcana  — spell attack rolls: 1d6 + floor(Arcana x 0.5) vs monster Agility
  Fortune — defense rolls against monster attacks (+2.5% per point)

Fresh DB read of player stats at resolution time — never cached stale values.
"""

import random
import json
import math
from config import STARTING_STATS

with open("data/loot_tables.json", "r") as f:
    LOOT_TABLES = json.load(f)

with open("data/items.json", "r") as f:
    ITEMS_DATA = json.load(f)["items"]
ITEMS_BY_ID = {i["id"]: i for i in ITEMS_DATA}

with open("data/weapons.json", "r") as f:
    WEAPONS_DATA = json.load(f)["weapons"]
WEAPONS_BY_ID = {w["id"]: w for w in WEAPONS_DATA}

with open("data/spells.json", "r") as f:
    SPELLS_DATA = json.load(f)["spells"]
SPELLS_BY_ID = {s["id"]: s for s in SPELLS_DATA}

with open("data/dungeons.json", "r") as f:
    DUNGEONS_DATA = json.load(f)["dungeons"]
DUNGEONS_BY_ID = {d["id"]: d for d in DUNGEONS_DATA}

with open("data/node_templates.json", "r") as f:
    NODES_DATA = json.load(f)["nodes"]
NODES_BY_ID = {n["id"]: n for n in NODES_DATA}

MAX_STRIKES        = 3
BASE_SUCCESS_CHANCE = 65
SUCCESS_CHANCE_CAP  = 90
STAT_BONUS_PER_POINT = 2.5   # % per stat point — calibrate during playtesting

# Node types that use each stat
COMBAT_NODE_TYPES  = {"combat"}
SOCIAL_NODE_TYPES  = {"social", "npc_encounter"}
SPELL_NODE_TYPES   = {"supernatural"}


# ---------------------------------------------------------------------------
# Stat helpers — read from player object, fall back to starting defaults
# ---------------------------------------------------------------------------

def get_stat(player, stat: str) -> int:
    """Safe stat read — falls back to STARTING_STATS if column not yet populated."""
    if player is None:
        return STARTING_STATS.get(stat, 1)
    return getattr(player, stat, None) or STARTING_STATS.get(stat, 1)


def stat_bonus_pct(stat_value: int) -> int:
    """Convert a stat value to a percentage bonus. floor(stat x 2.5)"""
    return math.floor(stat_value * STAT_BONUS_PER_POINT)


# ---------------------------------------------------------------------------
# Loadout bonus — weapon/spell modifier from equipped items
# ---------------------------------------------------------------------------

def get_loadout_bonus(run, choice: str) -> int:
    """
    Returns bonus from equipped weapon or spell based on choice type.
    Fight → weapon damage_bonus
    Flee  → spell escape_bonus
    """
    choice_lower = choice.lower()
    if "fight" in choice_lower or choice_lower == "a":
        weapon = WEAPONS_BY_ID.get(run.weapon_slot or "")
        return weapon.get("damage_bonus", 0) if weapon else 0
    elif "flee" in choice_lower:
        spell = SPELLS_BY_ID.get(run.spell_slot or "")
        return spell.get("escape_bonus", 0) if spell else 0
    return 0


# ---------------------------------------------------------------------------
# Spell attack roll — Arcana-powered
# ---------------------------------------------------------------------------

def roll_spell_attack(player) -> dict:
    """
    Spell attack: 1d6 + floor(Arcana x 0.5) vs monster Agility (fixed at 4).
    Returns dict with roll, bonus, total, hit, and flavor.
    """
    arcana      = get_stat(player, "arcana")
    roll        = random.randint(1, 6)
    bonus       = math.floor(arcana * 0.5)
    total       = roll + bonus
    monster_agi = 4   # baseline — scales with enemy tier in future
    hit         = total >= monster_agi

    stat_boosted = arcana > STARTING_STATS["arcana"]
    if hit and stat_boosted:
        flavor = f"Your arcane focus sharpens the spell. It strikes true. ({roll} + {bonus} = {total})"
    elif hit:
        flavor = f"The spell connects. ({roll} + {bonus} = {total})"
    else:
        flavor = f"The spell dissipates before it lands. ({roll} + {bonus} = {total} vs {monster_agi})"

    return {"roll": roll, "bonus": bonus, "total": total, "hit": hit, "flavor": flavor}


# ---------------------------------------------------------------------------
# Core resolution
# ---------------------------------------------------------------------------

def resolve_node(run, node: dict, choice: str, player=None) -> dict:
    """
    Resolve a dungeon node. Returns outcome dict:
      success: bool
      strike:  bool
      loot_item: str | None
      message: str
      stat_boosted: bool  — True if a stat meaningfully affected the outcome
      xp_tranche: str | None
    """
    node_type     = node.get("type", "").lower()
    loadout_bonus = get_loadout_bonus(run, choice)

    # --- Determine stat modifier based on node type ---
    stat_modifier = 0
    stat_name     = None

    if node_type in COMBAT_NODE_TYPES:
        brawn         = get_stat(player, "brawn")
        stat_modifier = stat_bonus_pct(brawn)
        stat_name     = "brawn"
    elif node_type in SOCIAL_NODE_TYPES:
        charm         = get_stat(player, "charm")
        stat_modifier = stat_bonus_pct(charm)
        stat_name     = "charm"
    elif node_type in SPELL_NODE_TYPES:
        arcana        = get_stat(player, "arcana")
        stat_modifier = stat_bonus_pct(arcana)
        stat_name     = "arcana"

    # --- Roll ---
    final_chance = min(
        BASE_SUCCESS_CHANCE + (loadout_bonus * 5) + stat_modifier,
        SUCCESS_CHANCE_CAP
    )
    roll    = random.randint(1, 100)
    success = roll <= final_chance

    # Did the stat make a meaningful difference?
    baseline_chance = min(BASE_SUCCESS_CHANCE + (loadout_bonus * 5), SUCCESS_CHANCE_CAP)
    stat_boosted    = (
        stat_modifier > 0
        and success
        and roll > baseline_chance
        and roll <= final_chance
    )

    # --- Strike ---
    strike = not success and node.get("failure_text") is not None

    # --- Loot ---
    loot_item = None
    if success:
        loot_item = _roll_loot(run.dungeon_id, node_type)

    # --- Message ---
    message = _build_message(node, success, choice, stat_boosted, stat_name, player)

    return {
        "success":      success,
        "strike":       strike,
        "loot_item":    loot_item,
        "message":      message,
        "stat_boosted": stat_boosted,
        "stat_name":    stat_name,
    }


# ---------------------------------------------------------------------------
# Loot rolling
# ---------------------------------------------------------------------------

def _roll_loot(dungeon_id: str, node_type: str) -> str | None:
    """
    40% chance to drop loot on success.
    Discovery nodes always drop. Other nodes 40%.
    """
    if node_type == "discovery":
        drop_chance = 100
    else:
        drop_chance = 40

    if random.randint(1, 100) > drop_chance:
        return None

    dungeon   = DUNGEONS_BY_ID.get(dungeon_id, {})
    tier      = dungeon.get("tier", 1)
    tier_key  = f"tier{tier}"
    pool      = LOOT_TABLES.get(tier_key, [])

    if not pool:
        return None

    weights = []
    for item_id in pool:
        item = ITEMS_BY_ID.get(item_id, {})
        rarity = item.get("rarity", "common")
        w = {"common": 60, "uncommon": 25, "rare": 12, "epic": 3}.get(rarity, 10)
        weights.append(w)

    chosen = random.choices(pool, weights=weights, k=1)
    return chosen[0] if chosen else None


# ---------------------------------------------------------------------------
# Message building
# ---------------------------------------------------------------------------

def _build_message(node: dict, success: bool, choice: str, stat_boosted: bool, stat_name: str | None, player) -> str:
    """
    Build outcome message. Stat-boosted successes get alternate flavor line.
    """
    if success:
        base_msg = node.get("success_text", "You succeed.")

        if stat_boosted and stat_name:
            stat_val = get_stat(player, stat_name)
            boost_lines = {
                "brawn":  f"\n\n*Your strength carries you through. (Brawn {stat_val}/10)*",
                "charm":  f"\n\n*Your natural charm wins them over. (Charm {stat_val}/10)*",
                "arcana": f"\n\n*Your arcane attunement sharpens the outcome. (Arcana {stat_val}/10)*",
            }
            base_msg += boost_lines.get(stat_name, "")

        return base_msg
    else:
        return node.get("failure_text", "You fail.")


# ---------------------------------------------------------------------------
# Death save
# ---------------------------------------------------------------------------

def roll_death_save() -> bool:
    """35% chance to survive at MAX_STRIKES."""
    return random.randint(1, 100) <= 35
