"""
game/cycle_manager.py
FT-01 change: daily_customers cleared in start_cycle() alongside other flags.
"""

from datetime import datetime, timedelta

CYCLE_DURATION_HOURS = 24


def is_cycle_fresh(player) -> bool:
    """Returns True if 24 hours have passed or cycle has never started."""
    if not player.cycle_start:
        return True
    return datetime.utcnow() > player.cycle_start + timedelta(hours=CYCLE_DURATION_HOURS)


def can_prep(player) -> bool:
    """Player can prep if cycle is fresh."""
    return is_cycle_fresh(player)


def can_shop(player) -> bool:
    """Player can shop only after prep is done, and only once."""
    return player.prep_complete and not player.shop_complete


def can_dungeon(player) -> bool:
    """Player can dungeon only after shop is done, and only once."""
    return player.shop_complete and not player.dungeon_complete


def start_cycle(player):
    """
    Kick off a fresh 24hr cycle, resetting all phase flags.
    FT-01: daily_customers cleared here so next /openshop generates a fresh pool.
    """
    player.cycle_start       = datetime.utcnow()
    player.prep_complete     = False
    player.shop_complete     = False
    player.dungeon_complete  = False
    player.daily_customers   = None          # ← FT-01: clear locked customer pool


def get_cycle_status(player) -> dict:
    """Returns a summary of current cycle state — useful for debug and display."""
    return {
        "cycle_started":    player.cycle_start,
        "prep_complete":    player.prep_complete,
        "shop_complete":    player.shop_complete,
        "dungeon_complete": player.dungeon_complete,
        "cycle_fresh":      is_cycle_fresh(player),
        "customers_locked": player.daily_customers is not None,  # FT-01: debug visibility
    }
