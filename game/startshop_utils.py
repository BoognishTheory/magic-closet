"""
game/startshop_utils.py
Shared utility functions used by both cogs/startshop.py and game/level_up.py.
Extracted here to avoid circular imports.
"""

import re


def channel_name_from_store(shop_name: str) -> str:
    """Convert store name to Discord channel name: tmc-[storename-slugified]"""
    slug = shop_name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return f"tmc-{slug}"
