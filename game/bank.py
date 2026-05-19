"""
game/bank.py
Data layer for /bank and /inventory commands.
Reads from BankItem table (SQLAlchemy) and items.json for item metadata.
All functions are read-only.
"""

import json
import os
from db.database import get_session
from db.models import Player, BankItem, Quest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RARITY_ORDER = {
    "Wondrous":  0,
    "Legendary": 1,
    "Very Rare": 2,
    "Rare":      3,
    "Uncommon":  4,
    "Common":    5,
}

# Normalize rarity strings from items.json to display labels
RARITY_NORMALIZE = {
    "common":    "Common",
    "uncommon":  "Uncommon",
    "rare":      "Rare",
    "epic":      "Very Rare",
    "legendary": "Legendary",
    "wondrous":  "Wondrous",
    "Common":    "Common",
    "Uncommon":  "Uncommon",
    "Rare":      "Rare",
    "Very Rare": "Very Rare",
    "Legendary": "Legendary",
    "Wondrous":  "Wondrous",
}

RARITY_EMOJI = {
    "Common":    "⚪",
    "Uncommon":  "🟢",
    "Rare":      "🔵",
    "Very Rare": "🟣",
    "Legendary": "🟠",
    "Wondrous":  "✨",
}

CATEGORIES = [
    "Pranks",
    "Remedies",
    "Magical Supplies",
    "Conveniences",
    "Wonder Items",
    "Practical Magic",
]

CATEGORY_EMOJI = {
    "Pranks":           "🎭",
    "Remedies":         "💊",
    "Magical Supplies": "🧪",
    "Conveniences":     "✨",
    "Wonder Items":     "🎁",
    "Practical Magic":  "⚔️",
}

# Placeholder: map item type → bank category until full catalog is written
TYPE_TO_CATEGORY = {
    "weapon":      "Practical Magic",
    "armor":       "Practical Magic",
    "consumable":  "Remedies",
    "material":    "Magical Supplies",
    "treasure":    "Wonder Items",
    "prank":       "Pranks",
    "convenience": "Conveniences",
    "remedy":      "Remedies",
}

PAGE_SIZE = 10


# ---------------------------------------------------------------------------
# Items catalog loader
# ---------------------------------------------------------------------------

_ITEMS_CACHE: dict = {}


def _load_items() -> dict:
    """Load items.json into a dict keyed by item id. Cached after first load."""
    global _ITEMS_CACHE
    if _ITEMS_CACHE:
        return _ITEMS_CACHE

    candidates = [
        "items.json",
        "data/items.json",
        "game/items.json",
        os.path.join(os.path.dirname(__file__), "items.json"),
        os.path.join(os.path.dirname(__file__), "../items.json"),
        os.path.join(os.path.dirname(__file__), "../data/items.json"),
    ]

    for path in candidates:
        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
            _ITEMS_CACHE = {item["id"]: item for item in data.get("items", [])}
            return _ITEMS_CACHE

    return {}


def get_item_meta(item_id: str) -> dict:
    """Returns item metadata from items.json. Falls back gracefully."""
    items = _load_items()
    item  = items.get(item_id)
    if item:
        return {
            "name":       item.get("name", item_id),
            "category":   TYPE_TO_CATEGORY.get(item.get("type", ""), "Wonder Items"),
            "sell_value": item.get("sell_value", 0),
            "rarity":     RARITY_NORMALIZE.get(item.get("rarity", "common"), "Common"),
        }
    return {
        "name":       item_id,
        "category":   "Wonder Items",
        "sell_value": 0,
        "rarity":     "Common",
    }


# ---------------------------------------------------------------------------
# Player lookup
# ---------------------------------------------------------------------------

def get_player_by_discord_id(discord_id: int):
    """Returns Player ORM object or None. discord_id stored as Text."""
    session = get_session()
    try:
        return session.query(Player).filter(
            Player.discord_id == str(discord_id)
        ).first()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# category_summary → dict
# ---------------------------------------------------------------------------

def category_summary(player_id: int) -> dict:
    """
    Returns item count per bank category for Root view button labels.
    player_id is Player.id (integer PK). Excludes floor items.
    """
    session = get_session()
    try:
        rows = session.query(BankItem).filter(
            BankItem.player_id == player_id,
            BankItem.on_floor  == False,
        ).all()
    finally:
        session.close()

    summary = {cat: 0 for cat in CATEGORIES}
    for row in rows:
        meta = get_item_meta(row.item_id)
        cat  = meta["category"]
        if cat in summary:
            summary[cat] += 1
    return summary


# ---------------------------------------------------------------------------
# bank_browse_category → dict
# ---------------------------------------------------------------------------

def bank_browse_category(
    player_id: int,
    category:  str,
    sort:      str,
    page:      int,
) -> dict:
    session = get_session()
    try:
        rows = session.query(BankItem).filter(
            BankItem.player_id == player_id,
            BankItem.on_floor  == False,
        ).all()
    finally:
        session.close()

    items = []
    for row in rows:
        meta = get_item_meta(row.item_id)
        if meta["category"] != category:
            continue
        rarity = RARITY_NORMALIZE.get(row.rarity, meta["rarity"])
        name   = meta["name"]
        if len(name) > 40:
            name = name[:37] + "..."
        items.append({
            "name":       name,
            "rarity":     rarity,
            "sell_value": meta["sell_value"],
        })

    if sort == "rarity":
        items.sort(key=lambda x: RARITY_ORDER.get(x["rarity"], 99))
    elif sort == "value":
        items.sort(key=lambda x: x["sell_value"], reverse=True)

    total       = len(items)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page        = max(1, min(page, total_pages))
    start       = (page - 1) * PAGE_SIZE
    page_items  = items[start: start + PAGE_SIZE]

    return {
        "items":        page_items,
        "total":        total,
        "page":         page,
        "total_pages":  total_pages,
        "has_wondrous": any(i["rarity"] == "Wondrous" for i in items),
    }


# ---------------------------------------------------------------------------
# bank_summary → dict
# ---------------------------------------------------------------------------

def bank_summary(player_id: int) -> dict:
    session = get_session()
    try:
        rows = session.query(BankItem).filter(
            BankItem.player_id == player_id,
            BankItem.on_floor  == False,
        ).all()
    finally:
        session.close()

    by_rarity = {r: 0 for r in RARITY_EMOJI}
    for row in rows:
        rarity = RARITY_NORMALIZE.get(row.rarity, "Common")
        if rarity in by_rarity:
            by_rarity[rarity] += 1

    return {
        "total":     sum(by_rarity.values()),
        "by_rarity": by_rarity,
    }


# ---------------------------------------------------------------------------
# floor_items → list
# ---------------------------------------------------------------------------

def floor_items(player_id: int) -> list:
    session = get_session()
    try:
        rows = session.query(BankItem).filter(
            BankItem.player_id == player_id,
            BankItem.on_floor  == True,
        ).all()
    finally:
        session.close()

    result = []
    for row in rows:
        meta   = get_item_meta(row.item_id)
        rarity = RARITY_NORMALIZE.get(row.rarity, meta["rarity"])
        result.append({"name": meta["name"], "rarity": rarity})
    return result


# ---------------------------------------------------------------------------
# has_wondrous → bool
# ---------------------------------------------------------------------------

def has_wondrous(player_id: int, category: str) -> bool:
    session = get_session()
    try:
        rows = session.query(BankItem).filter(
            BankItem.player_id == player_id,
            BankItem.on_floor  == False,
            BankItem.rarity.in_(["wondrous", "Wondrous"]),
        ).all()
    finally:
        session.close()

    return any(get_item_meta(r.item_id)["category"] == category for r in rows)


# ---------------------------------------------------------------------------
# active_quests_count → int
# ---------------------------------------------------------------------------

def active_quests_count(player_id: int) -> int:
    session = get_session()
    try:
        return session.query(Quest).filter(
            Quest.player_id == player_id,
            Quest.status    == "active",
        ).count()
    except Exception:
        return 0
    finally:
        session.close()
