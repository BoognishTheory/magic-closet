"""
cogs/spendstat.py
Command: /spendstat

Spend 1 unspent stat point on a character stat.
Valid stats: vitality, brawn, charm, arcana, fortune.
Max value: 10 per stat — displayed as X/10 so players know the ceiling.
"""

import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player
from game.access import has_access, deny_access
from cogs.startshop import check_shop_channel
from config import STARTING_STATS

EMBED_COLOR = 0x3498db
STAT_MAX    = 10

# Stat metadata — label, emoji, description of what it does
STATS = {
    "vitality": {
        "label":  "Vitality",
        "emoji":  "❤️",
        "effect": "Increases max HP. HP = 3 + floor(Vitality x 0.75)",
    },
    "brawn": {
        "label":  "Brawn",
        "emoji":  "⚔️",
        "effect": "Improves combat encounter success rolls.",
    },
    "charm": {
        "label":  "Charm",
        "emoji":  "🗣️",
        "effect": "Improves social encounter success rolls.",
    },
    "arcana": {
        "label":  "Arcana",
        "emoji":  "🔮",
        "effect": "Powers spell attacks. 1d6 + floor(Arcana x 0.5) vs monster Agility.",
    },
    "fortune": {
        "label":  "Fortune",
        "emoji":  "🍀",
        "effect": "Improves monster attack defense rolls.",
    },
}


def get_stat_value(player, stat: str) -> int:
    return getattr(player, stat, None) or STARTING_STATS.get(stat, 1)


def calc_hp(player) -> int:
    vit = get_stat_value(player, "vitality")
    return 3 + int(vit * 0.75)


class SpendStatCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="spendstat",
        description="Spend 1 stat point on a character stat. Max 10 per stat.",
    )
    @app_commands.describe(stat="Which stat to invest in")
    @app_commands.choices(stat=[
        app_commands.Choice(name="❤️ Vitality  — increases max HP",             value="vitality"),
        app_commands.Choice(name="⚔️ Brawn     — improves combat rolls",        value="brawn"),
        app_commands.Choice(name="🗣️ Charm     — improves social rolls",        value="charm"),
        app_commands.Choice(name="🔮 Arcana    — powers spell attacks",          value="arcana"),
        app_commands.Choice(name="🍀 Fortune   — improves defense rolls",        value="fortune"),
    ])
    async def spendstat(
        self,
        interaction: discord.Interaction,
        stat: app_commands.Choice[str],
    ):
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

            # Check unspent points
            unspent = player.stat_points_unspent or 0
            if unspent < 1:
                await interaction.response.send_message(
                    "You have no unspent stat points. "
                    "Level up your character to earn more.",
                    ephemeral=True,
                )
                return

            # Check current value
            current = get_stat_value(player, stat.value)
            if current >= STAT_MAX:
                await interaction.response.send_message(
                    f"**{STATS[stat.value]['emoji']} {STATS[stat.value]['label']}** "
                    f"is already at maximum ({STAT_MAX}/{STAT_MAX}).",
                    ephemeral=True,
                )
                return

            # Spend the point
            new_value = current + 1
            setattr(player, stat.value, new_value)
            player.stat_points_unspent = unspent - 1
            session.commit()

            stat_def  = STATS[stat.value]
            remaining = player.stat_points_unspent
            new_hp    = calc_hp(player)

            embed = discord.Embed(
                title=f"{stat_def['emoji']} {stat_def['label']} increased",
                description=(
                    f"**{stat_def['label']}**: {current}/10 → **{new_value}/10**\n\n"
                    f"*{stat_def['effect']}*\n\n"
                    f"You have **{remaining} unspent stat point{'s' if remaining != 1 else ''}** remaining."
                ),
                color=EMBED_COLOR,
            )

            # Show HP update if vitality was spent
            if stat.value == "vitality":
                old_hp = 3 + int((current) * 0.75)
                embed.add_field(
                    name="HP Updated",
                    value=f"{old_hp} → **{new_hp}**",
                    inline=True,
                )

            # Show full stat block for context
            vit  = get_stat_value(player, "vitality")
            brwn = get_stat_value(player, "brawn")
            chrm = get_stat_value(player, "charm")
            arc  = get_stat_value(player, "arcana")
            frt  = get_stat_value(player, "fortune")

            embed.add_field(
                name="Current Stats",
                value=(
                    f"❤️ Vitality: {vit}/10  |  ⚔️ Brawn: {brwn}/10  |  🗣️ Charm: {chrm}/10\n"
                    f"🔮 Arcana: {arc}/10  |  🍀 Fortune: {frt}/10  |  HP: {new_hp}"
                ),
                inline=False,
            )

            embed.set_footer(text="Use /status to see your full character summary.")
            await interaction.response.send_message(embed=embed)

        finally:
            session.close()


async def setup(bot: commands.Bot):
    await bot.add_cog(SpendStatCog(bot))
