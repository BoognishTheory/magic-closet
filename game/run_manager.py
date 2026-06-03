"""
game/run_manager.py
Core dungeon node resolution engine. No Discord imports.

Three paths for combat nodes:
  FIGHT — multi-round (5 round cap). Player and enemy exchange attacks.
           Player HP drains on enemy hit. Enemy HP drains on player hit.
           Enemy retreats with bad excuse at round cap.
           Player death = run over, portal rescue, random loot dropped.

  TALK  — compressed social path (3 stages, -1 disposition start).
           Charm modifier applies. Enemy-specific outcomes.
           High success = item reward. Low success = enemy stands down.
           Failure = transitions to Fight, player auto-attacked first.

  FLEE  — opposed agility check. Player d20 + Fortune vs enemy d20 + Agility.
           Player wins ties.
           Success = clean escape, all loot kept.
           Failure = enemy hits once (HP damage), player escapes anyway.

Non-combat nodes (social, environmental, puzzle, etc.) use single-roll resolution.
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

with open("data/enemies.json", "r") as f:
    ENEMIES_DATA = json.load(f)["enemies"]
ENEMIES_BY_ID = {e["id"]: e for e in ENEMIES_DATA}

with open("data/node_templates.json", "r") as f:
    NODES_DATA = json.load(f)["nodes"]
NODES_BY_ID = {n["id"]: n for n in NODES_DATA}

MAX_STRIKES         = 3
BASE_SUCCESS_CHANCE  = 65
SUCCESS_CHANCE_CAP   = 90
STAT_BONUS_PER_POINT = 2.5
COMBAT_ROUND_CAP     = 5

# Talk path constants
TALK_STAGES          = 3          # Compressed vs 7 in shop
TALK_DISPOSITION_START = -1       # Combat context penalty
TALK_MAX_SCORE       = TALK_STAGES * 2   # 6 total
TALK_HIGH_THRESHOLD  = 5          # High success — enemy yields item
TALK_LOW_THRESHOLD   = 3          # Low success — enemy stands down

COMBAT_NODE_TYPES  = {"combat"}
SOCIAL_NODE_TYPES  = {"social", "npc_encounter"}
SPELL_NODE_TYPES   = {"supernatural"}


# ---------------------------------------------------------------------------
# Stat helpers
# ---------------------------------------------------------------------------

def get_stat(player, stat: str) -> int:
    if player is None:
        return STARTING_STATS.get(stat, 1)
    return getattr(player, stat, None) or STARTING_STATS.get(stat, 1)


def stat_bonus_pct(stat_value: int) -> int:
    return math.floor(stat_value * STAT_BONUS_PER_POINT)


def calc_hp(vitality: int) -> int:
    """HP formula used by both player and enemy."""
    return 3 + math.floor(vitality * 0.75)


# ---------------------------------------------------------------------------
# Loadout bonus
# ---------------------------------------------------------------------------

def get_loadout_bonus(run, choice: str) -> int:
    choice_lower = choice.lower()
    if "fight" in choice_lower:
        weapon = WEAPONS_BY_ID.get(run.weapon_slot or "")
        return weapon.get("damage_bonus", 0) if weapon else 0
    elif "flee" in choice_lower:
        spell = SPELLS_BY_ID.get(run.spell_slot or "")
        return spell.get("escape_bonus", 0) if spell else 0
    return 0


# ---------------------------------------------------------------------------
# Combat resolution — multi-round Fight path
# ---------------------------------------------------------------------------

def resolve_fight_round(player_hp: int, enemy_hp: int, player, enemy: dict) -> dict:
    """
    Resolve one round of combat.
    Player attacks first.
    Returns updated HP values, hit results, and flavor lines.
    """
    brawn   = get_stat(player, "brawn")
    fortune = get_stat(player, "fortune")

    # Player attacks enemy
    player_roll    = random.randint(1, 20)
    player_bonus   = math.floor(brawn * 0.5)
    player_total   = player_roll + player_bonus
    enemy_defense  = enemy.get("agility", 3)
    player_hit     = player_total >= enemy_defense

    if player_hit:
        damage_to_enemy = max(1, math.floor(brawn * 0.75))
        enemy_hp       -= damage_to_enemy
        enemy_hp        = max(0, enemy_hp)
        player_attack_line = (
            f"You strike. ({player_roll} + {player_bonus} = {player_total} "
            f"vs defense {enemy_defense}) **-{damage_to_enemy} HP**"
        )
    else:
        player_attack_line = (
            f"You miss. ({player_roll} + {player_bonus} = {player_total} "
            f"vs defense {enemy_defense})"
        )

    # Enemy attacks player (only if still alive)
    enemy_hit = False
    damage_to_player = 0
    enemy_attack_line = ""

    if enemy_hp > 0:
        enemy_roll    = random.randint(1, 20)
        enemy_brawn   = enemy.get("brawn", 2)
        enemy_bonus   = math.floor(enemy_brawn * 0.5)
        enemy_total   = enemy_roll + enemy_bonus
        player_defense = math.floor(fortune * 0.5) + 8   # base 8 + Fortune modifier
        enemy_hit     = enemy_total >= player_defense

        if enemy_hit:
            damage_to_player = max(1, math.floor(enemy_brawn * 0.5))
            player_hp       -= damage_to_player
            player_hp        = max(0, player_hp)
            enemy_attack_line = (
                f"{enemy['name']} strikes back. ({enemy_roll} + {enemy_bonus} = {enemy_total} "
                f"vs your defense {player_defense}) **-{damage_to_player} HP**"
            )
        else:
            enemy_attack_line = (
                f"{enemy['name']} swings and misses. ({enemy_roll} + {enemy_bonus} = {enemy_total} "
                f"vs your defense {player_defense})"
            )

    return {
        "player_hp":          player_hp,
        "enemy_hp":           enemy_hp,
        "player_hit":         player_hit,
        "enemy_hit":          enemy_hit,
        "damage_to_enemy":    damage_to_enemy if player_hit else 0,
        "damage_to_player":   damage_to_player,
        "player_attack_line": player_attack_line,
        "enemy_attack_line":  enemy_attack_line,
    }


def start_combat(node: dict, player) -> dict:
    """
    Initialize combat state from node and player.
    Returns initial combat state dict.
    """
    enemy_id  = node.get("enemy_id", "goblin")
    enemy     = ENEMIES_BY_ID.get(enemy_id, ENEMIES_BY_ID.get("goblin"))
    player_vit = get_stat(player, "vitality")
    enemy_vit  = enemy.get("vitality", 2)

    return {
        "enemy":      enemy,
        "enemy_id":   enemy_id,
        "enemy_hp":   calc_hp(enemy_vit),
        "enemy_max":  calc_hp(enemy_vit),
        "player_hp":  calc_hp(player_vit),
        "player_max": calc_hp(player_vit),
        "round":      1,
    }


# ---------------------------------------------------------------------------
# Talk path — compressed social resolution
# ---------------------------------------------------------------------------

TALK_STAGE_DEMEANORS = [
    ["empathetic",   "direct",      "humorous"],   # Stage 1 — Opening
    ["deferential",  "empathetic",  "direct"],      # Stage 2 — Middle
    ["empathetic",   "humorous",    "deferential"], # Stage 3 — Close
]

TALK_STAGE_LABELS = [
    "Opening",
    "Negotiation",
    "Close",
]

CHOICE_INDEX = {"a": 0, "b": 1, "c": 2}


def get_talk_stage_description(stage: int, enemy: dict) -> str:
    name = enemy.get("name", "It")
    stages = [
        f"**{name}** is still in combat stance. You want to talk your way out of this.\n\n"
        f"**A) [Empathetic]** Acknowledge its territory and apologize for the intrusion\n"
        f"**B) [Direct]** State plainly that fighting benefits neither of you\n"
        f"**C) [Humorous]** Make a disarming comment to break the tension",

        f"{name} hasn't attacked. It's listening — barely.\n\n"
        f"**A) [Deferential]** Offer something — passage, information, respect\n"
        f"**B) [Empathetic]** Show that you understand why it's guarding this space\n"
        f"**C) [Direct]** Make your ask clearly and without embellishment",

        f"This is the moment. {name} is weighing you up.\n\n"
        f"**A) [Empathetic]** Give it an out — a reason to let you pass with dignity intact\n"
        f"**B) [Humorous]** One last light touch to close on a good note\n"
        f"**C) [Deferential]** Step back and let it make the call",
    ]
    return stages[stage]


def score_talk_choice(stage: int, choice: str, enemy: dict) -> int:
    """Score a talk choice against enemy's preferred demeanor."""
    choice_idx   = CHOICE_INDEX.get(choice.lower(), 0)
    demeanor     = TALK_STAGE_DEMEANORS[stage][choice_idx]
    enemy_likes  = enemy.get("talk_demeanor", "direct")

    if demeanor == enemy_likes:
        return 2
    elif demeanor in ["empathetic", "deferential"]:  # broadly non-threatening
        return 1
    else:
        return 0


def resolve_talk_outcome(total_score: int, disposition: int, enemy: dict) -> dict:
    """
    Resolve final Talk outcome based on cumulative score + starting disposition.
    Returns outcome dict with success level, message, and optional item reward.
    """
    final_score = total_score + disposition   # disposition starts at -1

    if final_score >= TALK_HIGH_THRESHOLD:
        return {
            "success":     True,
            "high_success": True,
            "message":     enemy.get("talk_success_max", "It yields."),
            "item_reward": enemy.get("talk_item_reward"),
        }
    elif final_score >= TALK_LOW_THRESHOLD:
        return {
            "success":     True,
            "high_success": False,
            "message":     enemy.get("talk_success_min", "It stands aside."),
            "item_reward": None,
        }
    else:
        return {
            "success":     False,
            "high_success": False,
            "message":     f"{enemy.get('name', 'It')} stops listening. This is about to get physical.",
            "item_reward": None,
        }


# ---------------------------------------------------------------------------
# Flee path — opposed agility check
# ---------------------------------------------------------------------------

def resolve_flee(player, enemy: dict) -> dict:
    """
    Opposed agility check.
    Player: d20 + Fortune modifier
    Enemy:  d20 + Agility
    Player wins ties.
    """
    fortune        = get_stat(player, "fortune")
    player_roll    = random.randint(1, 20)
    player_bonus   = math.floor(fortune * 0.5)
    player_total   = player_roll + player_bonus

    enemy_roll    = random.randint(1, 20)
    enemy_agility = enemy.get("agility", 3)
    enemy_total   = enemy_roll + enemy_agility

    success = player_total >= enemy_total   # player wins ties

    damage = 0
    if not success:
        enemy_brawn = enemy.get("brawn", 2)
        damage      = max(1, math.floor(enemy_brawn * 0.5))

    return {
        "success":      success,
        "player_total": player_total,
        "player_roll":  player_roll,
        "player_bonus": player_bonus,
        "enemy_total":  enemy_total,
        "enemy_roll":   enemy_roll,
        "enemy_agility":enemy_agility,
        "damage":       damage,
    }


# ---------------------------------------------------------------------------
# Non-combat node resolution (single roll)
# ---------------------------------------------------------------------------

def resolve_node(run, node: dict, choice: str, player=None) -> dict:
    """
    Resolve a non-combat dungeon node.
    Combat nodes are handled by the combat view in explore.py.
    Returns outcome dict.
    """
    node_type     = node.get("type", "").lower()
    loadout_bonus = get_loadout_bonus(run, choice)

    stat_modifier = 0
    stat_name     = None

    if node_type in SOCIAL_NODE_TYPES:
        charm         = get_stat(player, "charm")
        stat_modifier = stat_bonus_pct(charm)
        stat_name     = "charm"
    elif node_type in SPELL_NODE_TYPES:
        arcana        = get_stat(player, "arcana")
        stat_modifier = stat_bonus_pct(arcana)
        stat_name     = "arcana"

    final_chance    = min(BASE_SUCCESS_CHANCE + (loadout_bonus * 5) + stat_modifier, SUCCESS_CHANCE_CAP)
    roll            = random.randint(1, 100)
    success         = roll <= final_chance
    baseline_chance = min(BASE_SUCCESS_CHANCE + (loadout_bonus * 5), SUCCESS_CHANCE_CAP)
    stat_boosted    = (
        stat_modifier > 0
        and success
        and roll > baseline_chance
        and roll <= final_chance
    )

    strike    = not success and node.get("failure_text") is not None
    loot_item = _roll_loot(run.dungeon_id, node_type) if success else None
    message   = _build_message(node, success, choice, stat_boosted, stat_name, player)

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
    drop_chance = 100 if node_type == "discovery" else 40
    if random.randint(1, 100) > drop_chance:
        return None

    dungeon  = DUNGEONS_BY_ID.get(dungeon_id, {})
    tier     = dungeon.get("tier", 1)
    pool     = LOOT_TABLES.get(f"tier{tier}", [])
    if not pool:
        return None

    weights = []
    for item_id in pool:
        rarity = ITEMS_BY_ID.get(item_id, {}).get("rarity", "common")
        w      = {"common": 60, "uncommon": 25, "rare": 12, "epic": 3}.get(rarity, 10)
        weights.append(w)

    chosen = random.choices(pool, weights=weights, k=1)
    return chosen[0] if chosen else None


def roll_loot_public(dungeon_id: str, node_type: str) -> str | None:
    """Public wrapper for loot rolling — used by explore.py combat resolution."""
    return _roll_loot(dungeon_id, node_type)


# ---------------------------------------------------------------------------
# Message building
# ---------------------------------------------------------------------------

def _build_message(node: dict, success: bool, choice: str, stat_boosted: bool, stat_name: str | None, player) -> str:
    if success:
        base_msg = node.get("success_text", "You succeed.")
        if stat_boosted and stat_name:
            stat_val    = get_stat(player, stat_name)
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
    return random.randint(1, 100) <= 35
