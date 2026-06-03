"""
cogs/prep.py
Phase 1 — Prep the Store.

First /prepstore: Portal tutorial fires as a 2-page paginated scroll.
Subsequent /prepstore: Normal shelf stocking flow.

Portal tutorial fires when player.shop_name is set but no bank items exist yet.
(First run after /startshop, before any dungeon loot.)
"""

import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player, BankItem, SkillPoints
from game.access import has_access, deny_access
from game.cycle_manager import can_prep, start_cycle
from cogs.startshop import check_shop_channel
from datetime import datetime
import json
import random

with open("data/items.json", "r") as f:
    ITEMS_DATA = json.load(f)["items"]
ITEMS_BY_ID = {item["id"]: item for item in ITEMS_DATA}

RARITY_WEIGHTS = {"common": 60, "uncommon": 25, "rare": 12, "epic": 3}
SHELF_SIZE     = 6
EMBED_COLOR    = 0x5B2D8E

# ---------------------------------------------------------------------------
# Starter items — same for every new player.
# 6 items spanning 3 categories and 3 rarity tiers.
# Demonstrates portal variety from day one.
# ---------------------------------------------------------------------------

STARTER_ITEMS = [
    "instant_itching_powder",    # Pranks    — Common
    "self_stirring_spoon",       # Conveniences — Common
    "forget_your_ex_soap",       # Remedies  — Uncommon
    "enchanted_baking_flour",    # Magical Supplies — Common
    "strongly_worded_letter",    # Practical Magic — Common
    "broom_that_judges_you",     # Wonder Items — Uncommon
]

# ---------------------------------------------------------------------------
# Portal tutorial views — 2-page paginated scroll
# ---------------------------------------------------------------------------

def build_portal_page_1(player_name: str, shop_name: str, town_name: str) -> discord.Embed:
    """
    Page 1 — Bizard introduces the portal and explains how it works.
    Uses the flavor text from your Portal Lore page.
    """
    embed = discord.Embed(
        title="A scroll unfurls from the portal...",
        description=(
            "Within a closet in the back of your shop is a deep blue portal. "
            "Far in the distance, thin lines of light connect small points of white. "
            "A flash erupts from the portal and streaks toward you.\n\n"
            "As your vision returns, you find a note hovering in the air before you. "
            "It unfolds itself.\n\n"
            "*— A message from Bizard the Wizard —*"
        ),
        color=EMBED_COLOR,
    )
    embed.add_field(
        name="From the desk of Bizard",
        value=(
            f"Congratulations on your first day, {player_name}.\n\n"
            f"That portal behind you is your inventory system. "
            f"Every morning it surfaces items from your bank for you to consider selling. "
            f"It does not ask for your opinion. It gives what it gives.\n\n"
            f"At first the portal is... unpredictable. You will get what you get. "
            f"This is intentional. The portal respects those who earn its trust.\n\n"
            f"If you wish to have more say in what appears each morning, "
            f"invest in the **Keen Eye** skill tree. "
            f"A small investment unlocks the ability to lock specific items onto your shelf. "
            f"A larger investment gives you full control. "
            f"Use `/skillpoints` to see the tree when you're ready.\n\n"
            f"For now — the portal has already stocked your shelves for today. "
            f"Consider it a gift. Don't read too much into it.\n\n"
            f"— Bizard 🧙"
        ),
        inline=False,
    )
    embed.set_footer(text="Page 1 of 2  ·  Press Next to see your starting inventory")
    return embed


def build_portal_page_2(starter_items: list) -> discord.Embed:
    """
    Page 2 — Starter items revealed. Shelf is stocked. Ready to sell.
    """
    embed = discord.Embed(
        title="The portal hums. Items emerge.",
        description=(
            "The scroll poofs out of existence.\n\n"
            "The portal swirls. Six items drift out and arrange themselves "
            "on your shelves with an air of mild self-importance.\n\n"
            "These are yours to sell today."
        ),
        color=EMBED_COLOR,
    )

    for bank_item in starter_items:
        item_def = ITEMS_BY_ID.get(bank_item.item_id)
        if item_def:
            rarity_emoji = {
                "common": "⚪", "uncommon": "🟢",
                "rare": "🔵", "epic": "🟣"
            }.get(item_def.get("rarity", "common"), "⚪")
            embed.add_field(
                name=f"{rarity_emoji} {item_def['name']}",
                value=f"{item_def.get('rarity', 'common').capitalize()}  ·  {item_def.get('sell_value', 0)} coin",
                inline=True,
            )

    embed.add_field(
        name="What now?",
        value=(
            "Run `/openshop` to open your doors and meet your first customers.\n"
            "Use `/inventory` to see your full bank at any time.\n"
            "Use `/skillpoints` to explore the Keen Eye tree."
        ),
        inline=False,
    )
    embed.set_footer(text="Page 2 of 2  ·  Good luck. Bizard will be watching. Supportively.")
    return embed


class PortalTutorialView(discord.ui.View):
    """2-page paginated tutorial scroll for first /prepstore."""

    def __init__(self, starter_items: list):
        super().__init__(timeout=300)
        self.starter_items = starter_items

    @discord.ui.button(label="Next →", style=discord.ButtonStyle.primary, custom_id="portal_next")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_portal_page_2(self.starter_items)
        self.clear_items()

        done_btn = discord.ui.Button(
            label="Open for Business",
            style=discord.ButtonStyle.success,
            custom_id="portal_done"
        )
        done_btn.callback = self.done
        self.add_item(done_btn)

        await interaction.response.edit_message(embed=embed, view=self)

    async def done(self, interaction: discord.Interaction):
        self.clear_items()
        await interaction.response.edit_message(
            content="Your shelves are stocked. Run `/openshop` when you're ready.",
            embed=None,
            view=None,
        )
        self.stop()


# ---------------------------------------------------------------------------
# Player helpers
# ---------------------------------------------------------------------------

def get_or_create_player(session, discord_id: str) -> Player:
    player = session.query(Player).filter_by(discord_id=discord_id).first()
    if not player:
        player = Player(
            discord_id=discord_id,
            created_at=datetime.utcnow(),
            last_active=datetime.utcnow(),
        )
        session.add(player)
        session.flush()
        session.add(SkillPoints(player_id=player.id))
        session.commit()
    return player


def is_first_prepstore(session, player: Player) -> bool:
    """True if the player has never had bank items before."""
    count = session.query(BankItem).filter_by(player_id=player.id).count()
    return count == 0


def seed_starter_items(session, player: Player) -> list:
    """
    Seeds the 6 starter items into the player's bank and puts them on the floor.
    Falls back gracefully if an item_id isn't in items.json.
    Returns the list of BankItems created.
    """
    seeded = []
    for item_id in STARTER_ITEMS:
        item_def = ITEMS_BY_ID.get(item_id)
        if not item_def:
            # Fallback — use first available common item
            fallback = next(
                (i for i in ITEMS_DATA if i.get("rarity") == "common"), None
            )
            if not fallback:
                continue
            item_id  = fallback["id"]
            item_def = fallback

        bank_item = BankItem(
            player_id=player.id,
            item_id=item_id,
            rarity=item_def.get("rarity", "common"),
            on_floor=True,
            acquired_at=datetime.utcnow(),
        )
        session.add(bank_item)
        seeded.append(bank_item)

    session.commit()
    return seeded


def surface_bank_items(session, player: Player) -> list:
    """
    Standard shelf stocking for subsequent /prepstore calls.
    Clears existing shelf. Weighted random selection by rarity.
    """
    for item in session.query(BankItem).filter_by(
        player_id=player.id, on_floor=True
    ).all():
        item.on_floor = False

    bank = session.query(BankItem).filter_by(
        player_id=player.id, on_floor=False
    ).all()

    if not bank:
        return []

    weights  = [RARITY_WEIGHTS.get(item.rarity, 10) for item in bank]
    count    = min(SHELF_SIZE, len(bank))
    selected = random.choices(bank, weights=weights, k=count)

    seen, shelf = set(), []
    for item in selected:
        if item.id not in seen:
            seen.add(item.id)
            item.on_floor = True
            shelf.append(item)

    session.commit()
    return shelf


# ---------------------------------------------------------------------------
# PrepCog
# ---------------------------------------------------------------------------

class PrepCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="prepstore",
        description="Stock your shelves and open the Magic Closet for the day.",
    )
    async def prepstore(self, interaction: discord.Interaction):
        if not has_access(interaction):
            await deny_access(interaction)
            return

        if not await check_shop_channel(interaction):
            return

        session = get_session()
        try:
            player = get_or_create_player(session, str(interaction.user.id))

            if not can_prep(player):
                await interaction.response.send_message(
                    "The Closet is already running today. Come back tomorrow for a fresh cycle.",
                    ephemeral=True,
                )
                return

            start_cycle(player)
            player.last_active = datetime.utcnow()
            session.commit()

            # First /prepstore — portal tutorial + starter items
            if is_first_prepstore(session, player):
                starter = seed_starter_items(session, player)
                player.prep_complete = True
                session.commit()

                shop_name  = player.shop_name  or "Your Shop"
                town_name  = player.town_name  or "Your Town"

                embed = build_portal_page_1(
                    interaction.user.display_name,
                    shop_name,
                    town_name,
                )
                view = PortalTutorialView(starter)
                await interaction.response.send_message(embed=embed, view=view)
                return

            # Normal /prepstore — standard shelf stocking
            shelf = surface_bank_items(session, player)
            player.prep_complete = True
            session.commit()

            embed = discord.Embed(
                title="The Magic Closet — Shelf Stocked",
                description=(
                    "The portal hums. Items drift out and settle onto your shelves.\n"
                    "Today's selection is ready."
                ),
                color=EMBED_COLOR,
            )

            if shelf:
                for bank_item in shelf:
                    item_def = ITEMS_BY_ID.get(bank_item.item_id)
                    if item_def:
                        rarity_emoji = {
                            "common": "⚪", "uncommon": "🟢",
                            "rare": "🔵", "epic": "🟣"
                        }.get(item_def.get("rarity", "common"), "⚪")
                        embed.add_field(
                            name=f"{rarity_emoji} {item_def['name']}",
                            value=f"{item_def.get('rarity', 'common').capitalize()}  ·  {item_def.get('sell_value', 0)} coin",
                            inline=True,
                        )
            else:
                embed.add_field(
                    name="Empty Bank",
                    value="No items in bank. Run a dungeon tonight to stock up.",
                    inline=False,
                )

            embed.set_footer(text="Run /openshop when you're ready to sell.")
            await interaction.response.send_message(embed=embed)

        finally:
            session.close()


async def setup(bot):
    await bot.add_cog(PrepCog(bot))
