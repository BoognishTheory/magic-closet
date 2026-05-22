import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player, BankItem, SkillPoints
from game.access import has_access, deny_access
from game.cycle_manager import can_prep, start_cycle
from datetime import datetime
import json
import random

# Load item definitions at startup
with open("data/items.json", "r") as f:
    ITEMS_DATA = json.load(f)["items"]

ITEMS_BY_ID = {item["id"]: item for item in ITEMS_DATA}

RARITY_WEIGHTS = {
    "common": 60,
    "uncommon": 25,
    "rare": 12,
    "epic": 3
}

SHELF_SIZE = 6  # How many items get surfaced to the shelf


def get_or_create_player(session, discord_id: str) -> Player:
    """Fetch existing player or create a new one."""
    player = session.query(Player).filter_by(discord_id=discord_id).first()
    if not player:
        player = Player(
            discord_id=discord_id,
            created_at=datetime.utcnow(),
            last_active=datetime.utcnow()
        )
        session.add(player)
        session.flush()

        # Create skill points row
        skill_points = SkillPoints(player_id=player.id)
        session.add(skill_points)
        session.commit()

    return player


def surface_bank_items(session, player: Player) -> list:
    """
    Pull items from the bank onto the shelf.
    Weighted by rarity. Returns list of BankItems now on_floor.
    """
    # Clear previous shelf
    existing_shelf = session.query(BankItem).filter_by(
        player_id=player.id, on_floor=True
    ).all()
    for item in existing_shelf:
        item.on_floor = False

    # Get all bank items not on floor
    bank = session.query(BankItem).filter_by(
        player_id=player.id, on_floor=False
    ).all()

    if not bank:
        # Seed starter items if bank is empty
        starter_ids = ["iron_sword", "leather_boots", "health_potion"]
        for item_id in starter_ids:
            item_def = ITEMS_BY_ID.get(item_id)
            if item_def:
                bank_item = BankItem(
                    player_id=player.id,
                    item_id=item_id,
                    rarity=item_def["rarity"],
                    on_floor=False,
                    acquired_at=datetime.utcnow()
                )
                session.add(bank_item)
        session.commit()
        bank = session.query(BankItem).filter_by(
            player_id=player.id, on_floor=False
        ).all()

    # Weight selection by rarity
    weights = [RARITY_WEIGHTS.get(item.rarity, 10) for item in bank]
    count = min(SHELF_SIZE, len(bank))
    selected = random.choices(bank, weights=weights, k=count)

    # Deduplicate
    seen = set()
    shelf = []
    for item in selected:
        if item.id not in seen:
            seen.add(item.id)
            item.on_floor = True
            shelf.append(item)

    session.commit()
    return shelf


class PrepCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="prepstore", description="Stock your shelves and open the Magic Closet for the day.")
    async def prepstore(self, interaction: discord.Interaction):
        session = get_session()
        try:
            player = get_or_create_player(session, str(interaction.user.id))

            if not can_prep(player):
                await interaction.response.send_message(
                    "??? The Closet is already running today. Come back tomorrow for a fresh cycle.",
                    ephemeral=True
                )
                return

            # Start the cycle
            start_cycle(player)
            player.last_active = datetime.utcnow()
            session.commit()

            # Surface items to shelf
            shelf = surface_bank_items(session, player)

            # Mark prep complete
            player.prep_complete = True
            session.commit()


            # Build embed
            embed = discord.Embed(
                title="?? The Magic Closet — Shelf Stocked",
                description="The shelves are set. Your wares are ready for today's customers.",
                color=0x9b59b6
            )

            for bank_item in shelf:
                item_def = ITEMS_BY_ID.get(bank_item.item_id)
                if item_def:
                    embed.add_field(
                        name=f"{item_def['name']} ({item_def['rarity'].capitalize()})",
                        value=f"Base value: {item_def['sell_value']} coin",
                        inline=True
                    )

            embed.set_footer(text="Run /openshop when you're ready to sell.")
            await interaction.response.send_message(embed=embed)

        finally:
            session.close()


async def setup(bot):
    await bot.add_cog(PrepCog(bot))