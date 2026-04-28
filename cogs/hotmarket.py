import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player
from datetime import datetime, timedelta
import json

with open("data/items.json", "r") as f:
    ITEMS_DATA = json.load(f)["items"]
ITEMS_BY_ID = {i["id"]: i for i in ITEMS_DATA}

# Server-wide hot market state — lives in memory
hot_market_state = {
    "active": False,
    "item_id": None,
    "multiplier": 2.0,
    "expires_at": None,
    "announced_by": None
}


def is_hot_market_active() -> bool:
    if not hot_market_state["active"]:
        return False
    if hot_market_state["expires_at"] and datetime.utcnow() > hot_market_state["expires_at"]:
        hot_market_state["active"] = False
        return False
    return True


def get_hot_market_multiplier(item_id: str) -> float:
    if not is_hot_market_active():
        return 1.0
    if hot_market_state["item_id"] is None:
        return hot_market_state["multiplier"]
    if hot_market_state["item_id"] == item_id:
        return hot_market_state["multiplier"]
    return 1.0


class HotMarketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="hotmarket", description="[ADMIN] Trigger a hot market event.")
    @app_commands.choices(duration=[
        app_commands.Choice(name="1 Hour", value=1),
        app_commands.Choice(name="2 Hours", value=2),
        app_commands.Choice(name="4 Hours", value=4),
        app_commands.Choice(name="8 Hours", value=8),
        app_commands.Choice(name="24 Hours", value=24),
    ])
    @app_commands.choices(multiplier=[
        app_commands.Choice(name="1.5x", value=15),
        app_commands.Choice(name="2x", value=20),
        app_commands.Choice(name="3x", value=30),
    ])
    async def hotmarket(
        self,
        interaction: discord.Interaction,
        duration: app_commands.Choice[int],
        multiplier: app_commands.Choice[int],
        item: str = None
    ):
        # Admin only — check for manage guild permission
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "You don't have permission to trigger hot market events.",
                ephemeral=True
            )
            return

        # Resolve item if provided
        item_def = None
        if item:
            item_def = ITEMS_BY_ID.get(item.lower().replace(" ", "_"))
            if not item_def:
                await interaction.response.send_message(
                    f"Item '{item}' not found. Leave blank to apply to all items.",
                    ephemeral=True
                )
                return

        real_multiplier = multiplier.value / 10.0
        expires_at = datetime.utcnow() + timedelta(hours=duration.value)

        hot_market_state["active"] = True
        hot_market_state["item_id"] = item_def["id"] if item_def else None
        hot_market_state["multiplier"] = real_multiplier
        hot_market_state["expires_at"] = expires_at
        hot_market_state["announced_by"] = str(interaction.user.id)

        # Build announcement embed
        if item_def:
            title = f"🔥 Hot Market — {item_def['name']}!"
            desc = (
                f"Demand for **{item_def['name']}** has surged across the realm!\n\n"
                f"Sell yours now for **{real_multiplier}x** the normal price.\n"
                f"This market runs for **{duration.name}**."
            )
        else:
            title = "🔥 Hot Market — All Items!"
            desc = (
                f"The markets are on fire! ALL items are selling for **{real_multiplier}x** normal price.\n\n"
                f"Open your shop and cash in!\n"
                f"This market runs for **{duration.name}**."
            )

        embed = discord.Embed(title=title, description=desc, color=0xe74c3c)
        embed.set_footer(text=f"Expires at {expires_at.strftime('%H:%M UTC')}")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="hotmarketstatus", description="Check the current hot market status.")
    async def hotmarketstatus(self, interaction: discord.Interaction):
        if not is_hot_market_active():
            await interaction.response.send_message(
                "No hot market is currently active.",
                ephemeral=True
            )
            return

        item_id = hot_market_state["item_id"]
        item_def = ITEMS_BY_ID.get(item_id) if item_id else None
        expires_at = hot_market_state["expires_at"]

        embed = discord.Embed(
            title="🔥 Hot Market Active",
            color=0xe74c3c
        )
        embed.add_field(
            name="Item",
            value=item_def["name"] if item_def else "All Items",
            inline=True
        )
        embed.add_field(
            name="Multiplier",
            value=f"{hot_market_state['multiplier']}x",
            inline=True
        )
        embed.add_field(
            name="Expires",
            value=expires_at.strftime("%H:%M UTC") if expires_at else "No expiry",
            inline=True
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="hotmarketend", description="[ADMIN] End the hot market early.")
    async def hotmarketend(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "You don't have permission to end hot market events.",
                ephemeral=True
            )
            return

        hot_market_state["active"] = False
        await interaction.response.send_message(
            "🔥 Hot market ended.",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(HotMarketCog(bot))