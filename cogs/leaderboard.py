import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player, RunHistory
from sqlalchemy import func
import json

with open("data/dungeons.json", "r") as f:
    DUNGEONS_DATA = json.load(f)["dungeons"]
DUNGEONS_BY_ID = {d["id"]: d for d in DUNGEONS_DATA}


class LeaderboardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="leaderboard", description="View the Magic Closet hall of fame.")
    async def leaderboard(self, interaction: discord.Interaction):
        session = get_session()
        try:
            # Top 10 by coin
            top_coin = session.query(Player).order_by(Player.coin.desc()).limit(10).all()

            # Top 10 by completed dungeon runs
            top_runs = (
                session.query(
                    RunHistory.player_id,
                    func.count(RunHistory.id).label("run_count")
                )
                .filter_by(outcome="completed")
                .group_by(RunHistory.player_id)
                .order_by(func.count(RunHistory.id).desc())
                .limit(10)
                .all()
            )

            embed = discord.Embed(
                title="🏆 The Magic Closet — Hall of Fame",
                description="The most successful merchants and dungeon runners in the realm.",
                color=0xf1c40f
            )

            # Coin leaderboard
            coin_lines = []
            for i, player in enumerate(top_coin):
                try:
                    user = await interaction.client.fetch_user(int(player.discord_id))
                    name = user.display_name
                except:
                    name = f"Player {player.discord_id[-4:]}"
                medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i + 1}."
                coin_lines.append(f"{medal} **{name}** — {player.coin} coin")

            embed.add_field(
                name="💰 Richest Merchants",
                value="\n".join(coin_lines) if coin_lines else "No data yet.",
                inline=False
            )

            # Runs leaderboard
            run_lines = []
            for i, (player_id, run_count) in enumerate(top_runs):
                try:
                    user = await interaction.client.fetch_user(player_id)
                    name = user.display_name
                except:
                    name = f"Player {str(player_id)[-4:]}"
                medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i + 1}."
                run_lines.append(f"{medal} **{name}** — {run_count} completed runs")

            embed.add_field(
                name="⚔️ Top Dungeon Runners",
                value="\n".join(run_lines) if run_lines else "No data yet.",
                inline=False
            )

            embed.set_footer(text="Updated in real time. Glory awaits.")
            await interaction.response.send_message(embed=embed)

        finally:
            session.close()


async def setup(bot):
    await bot.add_cog(LeaderboardCog(bot))