import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player
from game.cycle_manager import start_cycle
from game import access
from datetime import datetime


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="debugfullreset", description="[ADMIN] Full wipe - clears cycle and all flags.")
    async def debugfullreset(self, interaction: discord.Interaction):
        session = get_session()
        try:
            player = session.query(Player).filter_by(
                discord_id=str(interaction.user.id)
            ).first()
            if not player:
                await interaction.response.send_message("No player record found.", ephemeral=True)
                return
            player.cycle_start      = None
            player.prep_complete    = False
            player.shop_complete    = False
            player.dungeon_complete = False
            player.last_active      = datetime.utcnow()
            session.commit()
            await interaction.response.send_message(
                "🔧 Full reset complete. cycle_start cleared. Run /prepstore to begin.",
                ephemeral=True
            )
        finally:
            session.close()

    @app_commands.command(name="debugreset", description="[ADMIN] Reset your cycle for testing.")
    async def debugreset(self, interaction: discord.Interaction):
        session = get_session()
        try:
            player = session.query(Player).filter_by(
                discord_id=str(interaction.user.id)
            ).first()
            if not player:
                await interaction.response.send_message(
                    "No player record found. Run /prepstore first.",
                    ephemeral=True
                )
                return
            start_cycle(player)
            player.last_active = datetime.utcnow()
            session.commit()
            await interaction.response.send_message(
                "🔧 Cycle reset. All phase flags cleared. Run /prepstore to start fresh.",
                ephemeral=True
            )
        finally:
            session.close()

    @app_commands.command(name="debugstatus", description="[ADMIN] Check your current cycle state.")
    async def debugstatus(self, interaction: discord.Interaction):
        session = get_session()
        try:
            player = session.query(Player).filter_by(
                discord_id=str(interaction.user.id)
            ).first()
            if not player:
                await interaction.response.send_message("No player record found.", ephemeral=True)
                return
            embed = discord.Embed(title="🔧 Debug — Cycle Status", color=0xe67e22)
            embed.add_field(name="Cycle Start", value=str(player.cycle_start), inline=False)
            embed.add_field(name="Prep Complete", value=str(player.prep_complete), inline=True)
            embed.add_field(name="Shop Complete", value=str(player.shop_complete), inline=True)
            embed.add_field(name="Dungeon Complete", value=str(player.dungeon_complete), inline=True)
            embed.add_field(name="Coin", value=str(player.coin), inline=True)
            embed.add_field(name="Debt", value=str(player.debt), inline=True)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        finally:
            session.close()

    @app_commands.command(name="debugsetphase", description="[ADMIN] Jump to a specific phase.")
    @app_commands.choices(phase=[
        app_commands.Choice(name="Prep Done", value="prep"),
        app_commands.Choice(name="Shop Done", value="shop"),
        app_commands.Choice(name="Dungeon Done", value="dungeon"),
    ])
    async def debugsetphase(self, interaction: discord.Interaction, phase: app_commands.Choice[str]):
        session = get_session()
        try:
            player = session.query(Player).filter_by(
                discord_id=str(interaction.user.id)
            ).first()
            if not player:
                await interaction.response.send_message("No player record found.", ephemeral=True)
                return
            if phase.value == "prep":
                player.prep_complete    = True
                player.shop_complete    = False
                player.dungeon_complete = False
            elif phase.value == "shop":
                player.prep_complete    = True
                player.shop_complete    = True
                player.dungeon_complete = False
            elif phase.value == "dungeon":
                player.prep_complete    = True
                player.shop_complete    = True
                player.dungeon_complete = True
            session.commit()
            await interaction.response.send_message(
                f"🔧 Phase set to **{phase.name}**. Flags updated.",
                ephemeral=True
            )
        finally:
            session.close()

    @app_commands.command(name="debugaccess", description="[ADMIN] Toggle access bypass for testing.")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Grant Access", value="grant"),
        app_commands.Choice(name="Revoke Access", value="revoke"),
    ])
    async def debugaccess(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        user_id = str(interaction.user.id)
        if mode.value == "grant":
            access.DEBUG_BYPASS_IDS.add(user_id)
            await interaction.response.send_message(
                "🔧 Access granted. You are now bypassing the role gate.",
                ephemeral=True
            )
        else:
            access.DEBUG_BYPASS_IDS.discard(user_id)
            await interaction.response.send_message(
                "🔧 Access revoked. You are now subject to the role gate.",
                ephemeral=True
            )

    @app_commands.command(name="debugaccessother", description="[ADMIN] Grant or revoke access for another user.")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Grant Access", value="grant"),
        app_commands.Choice(name="Revoke Access", value="revoke"),
    ])
    async def debugaccessother(self, interaction: discord.Interaction, mode: app_commands.Choice[str], user: discord.Member):
        user_id = str(user.id)
        if mode.value == "grant":
            access.DEBUG_BYPASS_IDS.add(user_id)
            await interaction.response.send_message(
                f"🔧 Access granted for {user.display_name}.",
                ephemeral=True
            )
        else:
            access.DEBUG_BYPASS_IDS.discard(user_id)
            await interaction.response.send_message(
                f"🔧 Access revoked for {user.display_name}.",
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(AdminCog(bot))