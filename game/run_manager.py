import json
import random

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

MAX_STRIKES = 3


def get_loadout_bonus(run, choice: str) -> int:
    """Apply weapon/spell bonuses to success chance."""
    bonus = 0
    weapon = WEAPONS_BY_ID.get(run.weapon_slot, {})
    spell = SPELLS_BY_ID.get(run.spell_slot, {})

    if choice == "Fight":
        bonus += weapon.get("damage_bonus", 0)
        if spell.get("effect") == "combat_bonus":
            bonus += spell.get("modifier", 0)
    if choice == "Flee":
        if spell.get("effect") == "escape_bonus":
            bonus += spell.get("modifier", 0)

    return bonus


def resolve_node(run, node: dict, choice: str) -> dict:
    """
    Resolve a node choice. Returns outcome dict with:
    - success: bool
    - strike: bool
    - loot_item: str or None
    - message: str
    """
    dungeon = DUNGEONS_BY_ID.get(run.dungeon_id, {})
    tier = f"tier{dungeon.get('tier', 1)}"

    base_success_chance = 65
    bonus = get_loadout_bonus(run, choice)
    final_chance = min(base_success_chance + (bonus * 5), 90)

    roll = random.randint(1, 100)
    success = roll <= final_chance

    strike = False
    loot_item = None
    message = ""

    if success:
        message = node["outcomes"][choice]["success"]
        # Chance to find loot on success
        if random.random() < 0.4:
            loot_pool = LOOT_TABLES.get(tier, {})
            rarities = ["common", "uncommon", "rare", "epic"]
            weights = [60, 25, 12, 3]
            rarity = random.choices(rarities, weights=weights, k=1)[0]
            pool = loot_pool.get(rarity, [])
            if pool:
                loot_item = random.choice(pool)
    else:
        failure_msg = node["outcomes"][choice].get("failure", "")
        if failure_msg:
            message = failure_msg
            strike = True
        else:
            message = node["outcomes"][choice]["success"]

    return {
        "success": success,
        "strike": strike,
        "loot_item": loot_item,
        "message": message
    }


def roll_death_save() -> bool:
    """On third strike, roll death save. True = survive."""
    return random.randint(1, 100) <= 35