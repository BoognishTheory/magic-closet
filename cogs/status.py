"""
cogs/status.py
Command: /status

Character-focused status command. Shows:
  - Character level and win progress
  - Win totals (combat + social)
  - Stat block displayed as X/10 so players know the ceiling
  - HP calculation from Vitality
  - Unspent stat points
"""

import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player
from game.access import has_access, deny_access
from cogs.startshop import check_shop_channel
from config import CHAR_LEVEL_THRESHOLDS, CHAR_LEVEL_CAP, STARTING_STATS

EMBED_COLOR = 0x3498db
STAT_MAX    = 10


def get_stat(player, stat: str) -> int:
    return getattr(player, stat, None) or STARTING_STATS.get(stat, 1)


def calc_hp(player) -> int:
    return 3 + int(get_stat(player, "vitality") * 0.75)


def wins_progress_bar(current_xp: int, threshold: int, length: int = 10) -> str:
    if threshold >= 999:
        return f"{current_xp} wins  (Level cap reached)"
    filled = min(int((current_xp / threshold) * length), length)
    bar    = "=" * filled + "-" * (length - filled)
    return f"[{bar}]  {current_xp} / {threshold} wins"


def build_status_embed(player_name: str, player) -> discord.Embed:
    char_level = player.char_level or 1
    char_xp    = player.char_xp    or 0
    combat     = player.combat_wins or 0
    social     = player.social_wins or 0
    threshold  = CHAR_LEVEL_THRESHOLDS.get(char_level, 999)
    at_cap     = char_level >= CHAR_LEVEL_CAP
    unspent    = player.stat_points_unspent or 0

    embed = discord.Embed(
        title=f"Character Status — {player_name}",
        color=EMBED_COLOR,
    )

    # Character level + progress
    if at_cap:
        level_value = f"**Level {char_level}** — Maximum level reached."
    else:
        level_value = f"**Level {char_level}**\n{wins_progress_bar(char_xp, threshold)}"
    embed.add_field(name="Character Level", value=level_value, inline=False)

    # Win record
    embed.add_field(
        name="Win Record",
        value=(
            f"⚔️ Combat: **{combat}**\n"
            f"🗣️ Social: **{social}**\n"
            f"Total: **{combat + social}**"
        ),
        inline=True,
    )

    # Unspent stat points
    if unspent > 0:
        embed.add_field(
            name="Unspent Stat Points",
            value=f"**{unspent}** — use `/spendstat` to invest",
            inline=True,
        )

    # Stat block — X/10 format
    vit  = get_stat(player, "vitality")
    brwn = get_stat(player, "brawn")
    chrm = get_stat(player, "charm")
    arc  = get_stat(player, "arcana")
    frt  = get_stat(player, "fortune")
    hp   = calc_hp(player)

    embed.add_field(
        name="Stats",
        value=(
            f"❤️ Vitality: **{vit}/{STAT_MAX}**  |  "
            f"⚔️ Brawn: **{brwn}/{STAT_MAX}**  |  "
            f"🗣️ Charm: **{chrm}/{STAT_MAX}**\n"
            f"🔮 Arcana: **{arc}/{STAT_MAX}**  |  "
            f"🍀 Fortune: **{frt}/{STAT_MAX}**  |  "
            f"HP: **{hp}**"
        ),
        inline=False,
    )

    footer_parts = ["Win dungeon encounters to level up."]
    if unspent > 0:
        footer_parts.append(f"You have {unspent} stat point{'s' if unspent != 1 else ''} to spend.")
    embed.set_footer(text="  |  ".join(footer_parts))
    return embed


class StatusCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="status",
        description="View your character level, win record, and stat block.",
    )
    async def status(self, interaction: discord.Interaction):
        if not has_access(interaction):
            await deny_access(interaction)
            return

        if not await check_shop_channel(interaction):
            return

        session = get_session()
        try:
            player = session.query(Player).filter_by(
                discord_id=str(interaction.user.id)
            ).first()

            if not player:
                await interaction.response.send_message(
                    "No player found. Run /prepstore first.",
                    ephemeral=True,
                )
                return

            embed = build_status_embed(interaction.user.display_name, player)
            await interaction.response.send_message(embed=embed)

        finally:
            session.close()


async def setup(bot: commands.Bot):
    await bot.add_cog(StatusCog(bot))
