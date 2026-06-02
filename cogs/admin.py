import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player, SkillPoints
from game.cycle_manager import start_cycle
from game import access
from datetime import datetime


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="debugsetupserver", description="[ADMIN] Manually run server setup — fixes category permissions.")
    async def debugsetupserver(self, interaction: discord.Interaction):
        from game.server_setup import setup_server
        await interaction.response.defer(ephemeral=True)
        try:
            result = await setup_server(interaction.guild, interaction.client.user)
            await interaction.followup.send(
                f"Server setup complete.\n"
                f"Category: {result['category'].name}\n"
                f"Already existed: {result['already_existed']}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"Setup failed: {e}", ephemeral=True)

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
            player.cycle_start              = None
            player.prep_complete            = False
            player.shop_complete            = False
            player.dungeon_complete         = False
            player.daily_customers          = None
            player.shop_name                = None
            player.town_name                = None
            player.name_last_changed_shop   = None
            player.name_last_changed_town   = None
            player.last_active              = datetime.utcnow()
            session.commit()

            for ch in interaction.guild.text_channels:
                if ch.name.startswith("tmc-"):
                    if ch.topic and interaction.user.display_name in ch.topic:
                        await ch.delete(reason="Debug full reset")
                        break

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
            sp = session.query(SkillPoints).filter_by(player_id=player.id).first()
            embed = discord.Embed(title="🔧 Debug — Player Status", color=0xe67e22)
            embed.add_field(name="Cycle Start",      value=str(player.cycle_start),      inline=False)
            embed.add_field(name="Prep Complete",    value=str(player.prep_complete),    inline=True)
            embed.add_field(name="Shop Complete",    value=str(player.shop_complete),    inline=True)
            embed.add_field(name="Dungeon Complete", value=str(player.dungeon_complete), inline=True)
            embed.add_field(name="Coin",             value=str(player.coin),             inline=True)
            embed.add_field(name="Debt",             value=str(player.debt),             inline=True)
            embed.add_field(name="Shop Level",       value=str(player.shop_level or 1),  inline=True)
            embed.add_field(name="Shop XP",          value=str(player.xp or 0),          inline=True)
            if sp:
                embed.add_field(name="Unspent Points",  value=str(sp.unspent_points or 0), inline=True)
                embed.add_field(name="Keen Eye",        value=str(sp.keen_eye or 0),       inline=True)
                embed.add_field(name="Smooth Talker",   value=str(sp.smooth_talker or 0),  inline=True)
                embed.add_field(name="Heavy Hauler",    value=str(sp.heavy_hauler or 0),   inline=True)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        finally:
            session.close()

    @app_commands.command(name="debugsetphase", description="[ADMIN] Jump to a specific phase.")
    @app_commands.choices(phase=[
        app_commands.Choice(name="Prep Done",    value="prep"),
        app_commands.Choice(name="Shop Done",    value="shop"),
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
        app_commands.Choice(name="Grant Access",  value="grant"),
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
        app_commands.Choice(name="Grant Access",  value="grant"),
        app_commands.Choice(name="Revoke Access", value="revoke"),
    ])
    async def debugaccessother(
        self,
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
        user: discord.Member,
    ):
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

    # -----------------------------------------------------------------------
    # /debuglevelup — branch command for testing level-up systems
    # -----------------------------------------------------------------------

    @app_commands.command(name="debuglevelup", description="[ADMIN] Force a level-up for testing.")
    @app_commands.describe(type="Which level-up system to test")
    @app_commands.choices(type=[
        app_commands.Choice(name="Shop Level",   value="shop"),
        app_commands.Choice(name="Player Level", value="player"),
    ])
    async def debuglevelup(
        self,
        interaction: discord.Interaction,
        type: app_commands.Choice[str],
    ):
        if type.value == "shop":
            await self._debug_shop_levelup(interaction)
        elif type.value == "player":
            await interaction.response.send_message(
                "🔧 Player (character) level-up is not implemented yet. "
                "This will be wired when Character Level Tracking is built.",
                ephemeral=True
            )

    async def _debug_shop_levelup(self, interaction: discord.Interaction):
        """
        Forces an immediate shop level-up by setting XP to threshold.
        Triggers the full level-up flow: skill point award + Bizard message.
        """
        from game.level_up import apply_xp_and_check_levelup, post_levelup_message
        from config import SHOP_LEVEL_THRESHOLDS

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

            sp = session.query(SkillPoints).filter_by(
                player_id=player.id
            ).first()

            # Set XP to exactly the threshold to trigger level-up
            current_level = player.shop_level or 1
            threshold     = SHOP_LEVEL_THRESHOLDS.get(current_level, 999)
            player.xp     = threshold

            levelled_up, new_level = apply_xp_and_check_levelup(player, sp, 0)

            # apply_xp_and_check_levelup with 0 xp_earned won't fire —
            # manually trigger since we set xp = threshold above
            if not levelled_up:
                player.xp -= threshold
                player.shop_level = current_level + 1
                new_level = player.shop_level
                if sp:
                    sp.unspent_points = (sp.unspent_points or 0) + 1
                levelled_up = True

            session.commit()

            # Post the level-up message to the player's TMC channel
            await post_levelup_message(
                interaction.guild,
                player.shop_name,
                interaction.user.display_name,
                new_level,
                sp,
            )

            await interaction.response.send_message(
                f"🔧 Shop level-up forced. "
                f"**Level {current_level} → {new_level}**. "
                f"Bizard's message posted to your channel.",
                ephemeral=True
            )

        finally:
            session.close()


    async def _debug_char_levelup(self, interaction: discord.Interaction):
        """Forces an immediate character level-up for testing."""
        from game.char_level import apply_char_win, post_char_levelup_message, WIN_COMBAT
        from config import CHAR_LEVEL_THRESHOLDS

        session = get_session()
        try:
            player = session.query(Player).filter_by(
                discord_id=str(interaction.user.id)
            ).first()
            if not player:
                await interaction.response.send_message("No player record found.", ephemeral=True)
                return

            current_level = player.char_level or 1
            threshold     = CHAR_LEVEL_THRESHOLDS.get(current_level, 999)

            # Set char_xp to threshold to trigger level-up on next win
            player.char_xp = threshold
            levelled_up, new_level = apply_char_win(player, WIN_COMBAT)

            if not levelled_up:
                # Manual trigger if apply_char_win didn't fire
                player.char_xp   -= threshold
                player.char_level = current_level + 1
                new_level         = player.char_level
                levelled_up       = True

            session.commit()

            await post_char_levelup_message(
                interaction.guild,
                player.shop_name,
                interaction.user.display_name,
                new_level,
                player,
            )

            await interaction.response.send_message(
                f"Character level-up forced. **Level {current_level} -> {new_level}**. "
                f"Message posted to your channel.",
                ephemeral=True,
            )
        finally:
            session.close()


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
