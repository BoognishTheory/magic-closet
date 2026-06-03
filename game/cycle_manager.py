"""
game/cycle_manager.py
Pure cycle logic. Reads and modifies player object.
No DB commits — calling cog commits.

Chaos stock: if a player skips /prepstore and fires /openshop directly,
the shop opens with 4 fully random items. No rarity weighting.
No Keen Eye influence. is_chaos_stock() tells the shop whether prep was skipped.
"""

from datetime import datetime, timedelta

CYCLE_DURATION_HOURS = 24


def is_cycle_fresh(player) -> bool:
    if not player.cycle_start:
        return True
    return datetime.utcnow() > player.cycle_start + timedelta(hours=CYCLE_DURATION_HOURS)


def can_prep(player) -> bool:
    return is_cycle_fresh(player)


def can_shop(player) -> bool:
    return player.prep_complete and not player.shop_complete


def can_dungeon(player) -> bool:
    return player.shop_complete and not player.dungeon_complete


def is_chaos_stock(player) -> bool:
    """
    True if the player opened the shop without completing prep.
    Signals shop.py to use random stock with chaos flavor text.
    """
    return (
        player.cycle_start is not None
        and not player.prep_complete
        and not player.shop_complete
    )


def start_cycle(player):
    player.cycle_start      = datetime.utcnow()
    player.prep_complete    = False
    player.shop_complete    = False
    player.dungeon_complete = False
    player.daily_customers  = None


def get_cycle_status(player) -> dict:
    return {
        "cycle_started":    player.cycle_start,
        "prep_complete":    player.prep_complete,
        "shop_complete":    player.shop_complete,
        "dungeon_complete": player.dungeon_complete,
        "cycle_fresh":      is_cycle_fresh(player),
        "customers_locked": player.daily_customers is not None,
        "chaos_stock":      is_chaos_stock(player),
    }
