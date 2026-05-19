"""
game/bank.py
Data layer for /bank and /inventory commands.
All functions read from BankItem table. No writes happen here.
"""

import sqlite3
from typing import Optional

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

PAGE_SIZE = 10


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

def _get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# category_summary(player_id) → dict
# Returns item count per category for the Root view button labels.
# Excludes items currently on the floor (on_floor=TRUE).
# ---------------------------------------------------------------------------

def category_summary(player_id: int, db_path: str) -> dict:
    """
    Returns:
        {
            "Pranks": 3,
            "Remedies": 0,
            "Magical Supplies": 8,
            ...
        }
    """
    conn = _get_db(db_path)
    try:
        rows = conn.execute(
            """
            SELECT i.category, COUNT(*) as cnt
            FROM bankitem bi
            JOIN item i ON bi.item_id = i.id
            WHERE bi.player_id = ? AND bi.on_floor = FALSE
            GROUP BY i.category
            """,
            (player_id,),
        ).fetchall()
    finally:
        conn.close()

    summary = {cat: 0 for cat in CATEGORIES}
    for row in rows:
        if row["category"] in summary:
            summary[row["category"]] = row["cnt"]
    return summary


# ---------------------------------------------------------------------------
# bank_browse_category(player_id, category, sort, page) → dict
# Returns paginated item list for the Branch view.
# Excludes floor items.
# ---------------------------------------------------------------------------

def bank_browse_category(
    player_id: int,
    category: str,
    sort: str,          # "rarity" | "value"
    page: int,
    db_path: str,
) -> dict:
    """
    Returns:
        {
            "items": [
                {"name": str, "rarity": str, "sell_value": int},
                ...
            ],
            "total":       int,   # total items in this category
            "page":        int,   # current page (1-indexed)
            "total_pages": int,
            "has_wondrous": bool,
        }
    """
    conn = _get_db(db_path)
    try:
        rows = conn.execute(
            """
            SELECT i.name, i.rarity, i.sell_value
            FROM bankitem bi
            JOIN item i ON bi.item_id = i.id
            WHERE bi.player_id = ? AND i.category = ? AND bi.on_floor = FALSE
            """,
            (player_id, category),
        ).fetchall()
    finally:
        conn.close()

    items = [dict(r) for r in rows]

    # Sort
    if sort == "rarity":
        items.sort(key=lambda x: RARITY_ORDER.get(x["rarity"], 99))
    elif sort == "value":
        items.sort(key=lambda x: x["sell_value"], reverse=True)

    total = len(items)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))

    start = (page - 1) * PAGE_SIZE
    page_items = items[start : start + PAGE_SIZE]

    has_wondrous = any(i["rarity"] == "Wondrous" for i in items)

    # Truncate long names
    for item in page_items:
        if len(item["name"]) > 40:
            item["name"] = item["name"][:37] + "..."

    return {
        "items":       page_items,
        "total":       total,
        "page":        page,
        "total_pages": total_pages,
        "has_wondrous": has_wondrous,
    }


# ---------------------------------------------------------------------------
# bank_summary(player_id) → dict
# Returns total count and per-rarity breakdown for /inventory Bank section.
# Excludes floor items.
# ---------------------------------------------------------------------------

def bank_summary(player_id: int, db_path: str) -> dict:
    """
    Returns:
        {
            "total": 12,
            "by_rarity": {
                "Common":    8,
                "Uncommon":  3,
                "Rare":      1,
                "Very Rare": 0,
                "Legendary": 0,
                "Wondrous":  0,
            }
        }
    """
    conn = _get_db(db_path)
    try:
        rows = conn.execute(
            """
            SELECT i.rarity, COUNT(*) as cnt
            FROM bankitem bi
            JOIN item i ON bi.item_id = i.id
            WHERE bi.player_id = ? AND bi.on_floor = FALSE
            GROUP BY i.rarity
            """,
            (player_id,),
        ).fetchall()
    finally:
        conn.close()

    by_rarity = {r: 0 for r in RARITY_EMOJI}
    for row in rows:
        if row["rarity"] in by_rarity:
            by_rarity[row["rarity"]] = row["cnt"]

    return {
        "total":     sum(by_rarity.values()),
        "by_rarity": by_rarity,
    }


# ---------------------------------------------------------------------------
# floor_items(player_id) → list
# Returns items currently on the shop floor (on_floor=TRUE).
# ---------------------------------------------------------------------------

def floor_items(player_id: int, db_path: str) -> list:
    """
    Returns:
        [
            {"name": str, "rarity": str},
            ...
        ]
    """
    conn = _get_db(db_path)
    try:
        rows = conn.execute(
            """
            SELECT i.name, i.rarity
            FROM bankitem bi
            JOIN item i ON bi.item_id = i.id
            WHERE bi.player_id = ? AND bi.on_floor = TRUE
            ORDER BY i.name
            """,
            (player_id,),
        ).fetchall()
    finally:
        conn.close()

    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# has_wondrous(player_id, category) → bool
# Used by branch view to decide whether to show the Wondrous flavor line.
# ---------------------------------------------------------------------------

def has_wondrous(player_id: int, category: str, db_path: str) -> bool:
    conn = _get_db(db_path)
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM bankitem bi
            JOIN item i ON bi.item_id = i.id
            WHERE bi.player_id = ? AND i.category = ? AND i.rarity = 'Wondrous'
              AND bi.on_floor = FALSE
            LIMIT 1
            """,
            (player_id, category),
        ).fetchone()
    finally:
        conn.close()

    return row is not None


# ---------------------------------------------------------------------------
# active_quests_count(player_id) → int
# Returns number of active quests. Returns 0 if quest table doesn't exist yet.
# ---------------------------------------------------------------------------

def active_quests_count(player_id: int, db_path: str) -> int:
    conn = _get_db(db_path)
    try:
        # Quest system is post-VS — guard against table not existing
        row = conn.execute(
            """
            SELECT COUNT(*) as cnt
            FROM quest
            WHERE player_id = ? AND status = 'active'
            """,
            (player_id,),
        ).fetchone()
        return row["cnt"] if row else 0
    except sqlite3.OperationalError:
        # Quest table doesn't exist yet — return 0 silently
        return 0
    finally:
        conn.close()
