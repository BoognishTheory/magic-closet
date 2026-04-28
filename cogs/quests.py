import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player, Quest
from datetime import datetime
from game.access import has_access, deny_access
import json

with open("data/items.json", "r") as f:
    ITEMS_DATA = json.load(f)["items"]
ITEMS_BY_ID = {i["id"]: i for i in ITEMS_DATA}

with open("data/dungeons.json", "r") as f:
    DUNGEONS_DATA = json.load(f)["dungeons"]
DUNGEONS_BY_ID = {d["id"]: d for d in DUNGEONS_DATA}

MAX_QUEST_SLOTS = 3
MAX_QUESTS_PER_WEEK = 3


def get_current_week() -> int:
    return datetime.utcnow().isocalendar()[1]


def generate_quest(player_id: int) -> Quest:
    import random
    item = random.choice(list(ITEMS_BY_ID.values()))
    dungeon = random.choice(list(DUNGEONS_BY_ID.values()))
    return Quest(
        player_id=player_id,
        item_id=item["id"],
        dungeon_id=dungeon["id"],
        day_count=0,
        week_number=get_current_week(),
        status="active",
        created_at=datetime.utcnow()
    )


class QuestsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="quests", description="View your active quests.")
    async def quests(self, interaction: discord.Interaction):
        session = get_session()
        if not has_access(interaction):
            await deny_access(interaction)
            session.close()
            return
        try:
            player = session.query(Player).filter_by(
                discord_id=str(interaction.user.id)
            ).first()

            if not player:
                await interaction.response.send_message(
                    "No player found. Run /prepstore first.",
                    ephemeral=True
                )
                return

            active_quests = session.query(Quest).filter_by(
                player_id=player.id,
                status="active"
            ).all()

            completed_this_week = session.query(Quest).filter_by(
                player_id=player.id,
                status="complete",
                week_number=get_current_week()
            ).count()

            embed = discord.Embed(
                title="📜 Quest Board",
                description="Your active quests are listed below. Each quest expires after 5 days.",
                color=0xf39c12
            )

            if not active_quests:
                embed.add_field(
                    name="No Active Quests",
                    value="You have no active quests right now.",
                    inline=False
                )
            else:
                for quest in active_quests:
                    item_def = ITEMS_BY_ID.get(quest.item_id, {})
                    dungeon_def = DUNGEONS_BY_ID.get(quest.dungeon_id, {})
                    days_left = max(0, 5 - quest.day_count)
                    embed.add_field(
                        name=f"Quest — {item_def.get('name', quest.item_id)}",
                        value=(
                            f"Find a **{item_def.get('name', quest.item_id)}** "
                            f"in **{dungeon_def.get('name', quest.dungeon_id)}**\n"
                            f"Days remaining: {days_left}\n"
                            f"Status: {quest.status.capitalize()}"
                        ),
                        inline=False
                    )

            embed.add_field(
                name="Weekly Progress",
                value=f"{completed_this_week} / {MAX_QUESTS_PER_WEEK} quests completed this week",
                inline=False
            )
            embed.add_field(
                name="Quest Slots",
                value=f"{len(active_quests)} / {MAX_QUEST_SLOTS} slots filled",
                inline=False
            )
            embed.set_footer(text="Quests are assigned automatically. Check back daily.")

            await interaction.response.send_message(embed=embed)

        finally:
            session.close()

    @app_commands.command(name="questdebugadd", description="[ADMIN] Add a test quest to your board.")
    async def questdebugadd(self, interaction: discord.Interaction):
        session = get_session()
        try:
            player = session.query(Player).filter_by(
                discord_id=str(interaction.user.id)
            ).first()

            if not player:
                await interaction.response.send_message("No player found.", ephemeral=True)
                return

            active_count = session.query(Quest).filter_by(
                player_id=player.id,
                status="active"
            ).count()

            if active_count >= MAX_QUEST_SLOTS:
                await interaction.response.send_message(
                    "Quest slots full. Complete or wait for quests to expire.",
                    ephemeral=True
                )
                return

            quest = generate_quest(player.id)
            session.add(quest)
            session.commit()

            item_def = ITEMS_BY_ID.get(quest.item_id, {})
            dungeon_def = DUNGEONS_BY_ID.get(quest.dungeon_id, {})

            await interaction.response.send_message(
                f"📜 Quest added: Find a **{item_def.get('name', quest.item_id)}** "
                f"in **{dungeon_def.get('name', quest.dungeon_id)}**",
                ephemeral=True
            )

        finally:
            session.close()


async def setup(bot):
    await bot.add_cog(QuestsCog(bot))