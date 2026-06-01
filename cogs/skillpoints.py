"""
cogs/skillpoints.py
Commands: /skillpoints, /spendpoint

/skillpoints  — View skill tree ranks and unspent points.
/spendpoint   — Spend 1 unspent point on a chosen tree (VS max rank 4).

Both require Business Owner role and TMC channel.
"""

import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player, SkillPoints
from game.access import has_access, deny_access
from cogs.startshop import check_shop_channel

EMBED_COLOR   = 0x5B2D8E
VS_MAX_RANK   = 4   # VS scope — ranks 5-8 post-VS


# ---------------------------------------------------------------------------
# Tree definitions
# ---------------------------------------------------------------------------

TREES = {
    "keen_eye": {
        "label":   "Keen Eye",
        "emoji":   "🔮",
        "column":  "keen_eye",
        "tagline": "Controls the Prep Phase",
        "ranks": {
            1: "Lock 2 floor slots manually",
            2: "Lock 3 floor slots manually",
            3: "Lock all 4 floor slots",
            4: "Keen Eye ability — reveal best choice at current sell stage (2/day)",
        },
    },
    "smooth_talker": {
        "label":   "Smooth Talker",
        "emoji":   "🗣️",
        "column":  "smooth_talker",
        "tagline": "Controls the Shop Phase",
        "ranks": {
            1: "Wrong answers hurt less — reduced negative penalty",
            2: "Right answers score more — increased positive bonus",
            3: "Unlock recovery option — partially undo one bad choice per sale",
            4: "See customer mood score — numerical feedback during interaction",
        },
    },
    "heavy_hauler": {
        "label":   "Heavy Hauler",
        "emoji":   "⚔️",
        "column":  "heavy_hauler",
        "tagline": "Controls the Dungeon Phase",
        "ranks": {
            1: "+1 item recovered per dungeon run",
            2: "+1 item + see loot preview before committing to a node",
            3: "+1 item + expanded bank capacity",
            4: "Unlock Tier 2 dungeons — Rare loot possible",
        },
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_skillpoints_embed(player_name: str, sp: SkillPoints) -> discord.Embed:
    unspent = sp.unspent_points or 0

    embed = discord.Embed(
        title=f"Skill Trees — {player_name}",
        description=(
            f"**{unspent} unspent skill point{'s' if unspent != 1 else ''}**\n\n"
            f"Use `/spendpoint [tree]` to invest in a tree.\n"
            f"Levels 1-3 require one point in each tree before spending freely."
        ),
        color=EMBED_COLOR,
    )

    for tree_key, tree in TREES.items():
        current_rank = getattr(sp, tree["column"], 0) or 0

        # Build rank display
        lines = []
        for rank in range(1, VS_MAX_RANK + 1):
            desc     = tree["ranks"].get(rank, "")
            if rank < current_rank:
                lines.append(f"✅ Rank {rank}: {desc}")
            elif rank == current_rank:
                lines.append(f"**▶ Rank {rank} (current): {desc}**")
            elif rank == current_rank + 1:
                lines.append(f"⬜ Rank {rank} (next): {desc}")
            else:
                lines.append(f"🔒 Rank {rank}: {desc}")

        if current_rank >= VS_MAX_RANK:
            lines.append(f"\n*Rank 5+ unlocks in a future update.*")

        embed.add_field(
            name=f"{tree['emoji']} {tree['label']}  —  {tree['tagline']}  (Rank {current_rank})",
            value="\n".join(lines),
            inline=False,
        )

    embed.set_footer(text="VS scope: Ranks 1-4 per tree. Ranks 5-8 unlock in a future update.")
    return embed


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class SkillPointsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------------------------
    # /skillpoints
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="skillpoints",
        description="View your skill tree ranks and unspent points.",
    )
    async def skillpoints(self, interaction: discord.Interaction):
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

            sp = session.query(SkillPoints).filter_by(
                player_id=player.id
            ).first()

            if not sp:
                await interaction.response.send_message(
                    "Skill points record not found. Try running /prepstore.",
                    ephemeral=True,
                )
                return

            embed = build_skillpoints_embed(interaction.user.display_name, sp)
            await interaction.response.send_message(embed=embed)

        finally:
            session.close()

    # -----------------------------------------------------------------------
    # /spendpoint
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="spendpoint",
        description="Spend 1 skill point on a tree: keen_eye, smooth_talker, or heavy_hauler.",
    )
    @app_commands.describe(tree="Which skill tree to invest in")
    @app_commands.choices(tree=[
        app_commands.Choice(name="🔮 Keen Eye",      value="keen_eye"),
        app_commands.Choice(name="🗣️ Smooth Talker", value="smooth_talker"),
        app_commands.Choice(name="⚔️ Heavy Hauler",  value="heavy_hauler"),
    ])
    async def spendpoint(
        self,
        interaction: discord.Interaction,
        tree: app_commands.Choice[str],
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

            sp = session.query(SkillPoints).filter_by(
                player_id=player.id
            ).first()

            if not sp:
                await interaction.response.send_message(
                    "Skill points record not found.",
                    ephemeral=True,
                )
                return

            # Check unspent points
            unspent = sp.unspent_points or 0
            if unspent < 1:
                await interaction.response.send_message(
                    "You have no unspent skill points. "
                    "Level up your shop to earn more.",
                    ephemeral=True,
                )
                return

            # Levels 1-3 gate: must invest at least 1 point in each tree first
            shop_level = player.shop_level or 1
            if shop_level <= 3:
                ke = sp.keen_eye      or 0
                st = sp.smooth_talker or 0
                hh = sp.heavy_hauler  or 0
                tree_ranks = {"keen_eye": ke, "smooth_talker": st, "heavy_hauler": hh}
                for t_key, rank in tree_ranks.items():
                    if rank == 0 and t_key != tree.value:
                        tree_def = TREES[t_key]
                        await interaction.response.send_message(
                            f"At shop levels 1-3 you must invest at least 1 point in each tree first.\n"
                            f"You still need to invest in **{tree_def['emoji']} {tree_def['label']}**.",
                            ephemeral=True,
                        )
                        return

            # Get current rank
            tree_def     = TREES[tree.value]
            current_rank = getattr(sp, tree_def["column"], 0) or 0

            # VS rank cap
            if current_rank >= VS_MAX_RANK:
                await interaction.response.send_message(
                    f"**{tree_def['emoji']} {tree_def['label']}** is already at Rank {VS_MAX_RANK}.\n"
                    f"Rank 5+ unlocks in a future update.",
                    ephemeral=True,
                )
                return

            # Spend the point
            new_rank = current_rank + 1
            setattr(sp, tree_def["column"], new_rank)
            sp.unspent_points = unspent - 1
            session.commit()

            unlock_desc = tree_def["ranks"].get(new_rank, "")
            remaining   = sp.unspent_points

            embed = discord.Embed(
                title=f"{tree_def['emoji']} {tree_def['label']} — Rank {new_rank}",
                description=(
                    f"**Unlocked:** {unlock_desc}\n\n"
                    f"You have **{remaining} unspent point{'s' if remaining != 1 else ''}** remaining."
                ),
                color=0x2ecc71,
            )
            embed.set_footer(text="Use /skillpoints to see your full tree summary.")
            await interaction.response.send_message(embed=embed)

        finally:
            session.close()


async def setup(bot: commands.Bot):
    await bot.add_cog(SkillPointsCog(bot))
