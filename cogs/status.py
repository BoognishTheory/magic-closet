"""
cogs/status.py
Command: /status

Character-focused status command. Shows:
  - Character level and win progress
  - Win totals (combat + social)
  - Stat block (defaults until stat columns built in Character Level Up)

Distinct from /inventory (which focuses on shop/bank state).
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


# ---------------------------------------------------------------------------
# XP progress bar
# ---------------------------------------------------------------------------

def wins_progress_bar(current_xp: int, threshold: int, length: int = 10) -> str:
    if threshold <= 0 or threshold >= 999:
        return f"{current_xp} wins  (Level cap reached)" if threshold >= 999 else f"{current_xp} wins"
    filled = min(int((current_xp / threshold) * length), length)
    bar    = "=" * filled + "-" * (length - filled)
    return f"[{bar}]  {current_xp} / {threshold} wins"


# ---------------------------------------------------------------------------
# Stat block — uses DB values when available, falls back to starting defaults
# ---------------------------------------------------------------------------

def get_stat_block(player) -> dict:
    return {
        "Vitality": getattr(player, "vitality", None) or STARTING_STATS["vitality"],
        "Brawn":    getattr(player, "brawn",    None) or STARTING_STATS["brawn"],
        "Charm":    getattr(player, "charm",    None) or STARTING_STATS["charm"],
        "Arcana":   getattr(player, "arcana",   None) or STARTING_STATS["arcana"],
        "Fortune":  getattr(player, "fortune",  None) or STARTING_STATS["fortune"],
    }


# ---------------------------------------------------------------------------
# Status embed
# ---------------------------------------------------------------------------

def build_status_embed(player_name: str, player) -> discord.Embed:
    char_level = player.char_level or 1
    char_xp    = player.char_xp    or 0
    combat     = player.combat_wins or 0
    social     = player.social_wins or 0
    threshold  = CHAR_LEVEL_THRESHOLDS.get(char_level, 999)
    at_cap     = char_level >= CHAR_LEVEL_CAP

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
            f"⚔️ Combat wins: **{combat}**\n"
            f"🗣️ Social wins: **{social}**\n"
            f"Total: **{combat + social}**"
        ),
        inline=True,
    )

    # Stat block
    stats = get_stat_block(player)
    stat_lines = "  |  ".join(f"{k}: **{v}**" for k, v in stats.items())
    embed.add_field(
        name="Stats",
        value=stat_lines,
        inline=False,
    )

    # HP derived from vitality
    vit = stats["Vitality"]
    hp  = 3 + int(vit * 0.75)
    embed.add_field(
        name="HP",
        value=f"**{hp}** (base 3 + Vitality bonus)",
        inline=True,
    )

    embed.set_footer(
        text=(
            "Stats update when you invest stat points via /spendstat. "
            "Win /explore encounters to level up."
        )
    )
    return embed


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

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
