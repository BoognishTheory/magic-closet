import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player, ActiveRun, BankItem, RunHistory
from game.access import has_access, deny_access
from game.run_manager import resolve_node, roll_death_save, MAX_STRIKES
from cogs.startshop import check_shop_channel
from datetime import datetime
import json

with open("data/node_templates.json", "r") as f:
    NODES_DATA = json.load(f)["nodes"]
NODES_BY_ID = {n["id"]: n for n in NODES_DATA}

with open("data/items.json", "r") as f:
    ITEMS_DATA = json.load(f)["items"]
ITEMS_BY_ID = {i["id"]: i for i in ITEMS_DATA}

with open("data/dungeons.json", "r") as f:
    DUNGEONS_DATA = json.load(f)["dungeons"]
DUNGEONS_BY_ID = {d["id"]: d for d in DUNGEONS_DATA}


def get_current_node(run) -> dict:
    sequence = json.loads(run.node_sequence)
    if run.nodes_completed >= len(sequence):
        return None
    node_id = sequence[run.nodes_completed]
    return NODES_BY_ID.get(node_id)


def add_loot_to_run(session, player, run, item_id: str):
    loot = json.loads(run.loot_this_run)
    loot.append(item_id)
    run.loot_this_run = json.dumps(loot)

    item_def = ITEMS_BY_ID.get(item_id, {})
    bank_item = BankItem(
        player_id=player.id,
        item_id=item_id,
        rarity=item_def.get("rarity", "common"),
        on_floor=False,
        acquired_at=datetime.utcnow()
    )
    session.add(bank_item)
    session.commit()


def complete_run(session, player, run, outcome: str):
    loot = json.loads(run.loot_this_run)
    history = RunHistory(
        player_id=player.id,
        dungeon_id=run.dungeon_id,
        outcome=outcome,
        nodes_completed=run.nodes_completed,
        items_recovered=json.dumps(loot),
        coin_spent=DUNGEONS_BY_ID.get(run.dungeon_id, {}).get("entry_cost", 0),
        created_at=datetime.utcnow()
    )
    session.add(history)
    session.delete(run)
    player.dungeon_complete = True
    player.last_active = datetime.utcnow()
    session.commit()


class NodeView(discord.ui.View):
    def __init__(self, session, player, run, node):
        super().__init__(timeout=120)
        self.session = session
        self.player = player
        self.run = run
        self.node = node
        self._add_choice_buttons()

    def _add_choice_buttons(self):
        self.clear_items()
        for choice in self.node["choices"]:
            btn = discord.ui.Button(
                label=choice,
                style=discord.ButtonStyle.primary,
                custom_id=f"choice_{choice.lower().replace(' ', '_')}"
            )
            btn.callback = self._make_callback(choice)
            self.add_item(btn)

        flee_btn = discord.ui.Button(
            label="Flee Dungeon",
            style=discord.ButtonStyle.danger,
            custom_id="flee"
        )
        flee_btn.callback = self.flee_dungeon
        self.add_item(flee_btn)

    def _make_callback(self, choice: str):
        async def callback(interaction: discord.Interaction):
            await self._handle_choice(interaction, choice)
        return callback

    def build_node_embed(self) -> discord.Embed:
        dungeon = DUNGEONS_BY_ID.get(self.run.dungeon_id, {})
        sequence = json.loads(self.run.node_sequence)
        total_nodes = len(sequence)

        embed = discord.Embed(
            title=f"{self.node['title']}",
            description=self.node["description"],
            color=0xe74c3c
        )
        embed.add_field(name="Dungeon",  value=dungeon.get("name", "Unknown"), inline=True)
        embed.add_field(
            name="Progress",
            value=f"{self.run.nodes_completed + 1} / {total_nodes}",
            inline=True
        )
        embed.add_field(
            name="Strikes",
            value=f"{'X' * self.run.strikes}{'O' * (MAX_STRIKES - self.run.strikes)}",
            inline=True
        )
        embed.add_field(name="Weapon", value=self.run.weapon_slot or "None", inline=True)
        embed.add_field(name="Spell",  value=self.run.spell_slot or "None",  inline=True)
        embed.set_footer(text="Choose your action.")
        return embed

    async def _handle_choice(self, interaction: discord.Interaction, choice: str):
        outcome = resolve_node(self.run, self.node, choice)

        if outcome["strike"]:
            self.run.strikes += 1

        loot_line = ""
        if outcome["loot_item"]:
            add_loot_to_run(self.session, self.player, self.run, outcome["loot_item"])
            item_def = ITEMS_BY_ID.get(outcome["loot_item"], {})
            loot_line = f"\n\nYou found: **{item_def.get('name', outcome['loot_item'])}**"

        self.run.nodes_completed += 1
        self.session.commit()

        if self.run.strikes >= MAX_STRIKES:
            survived = roll_death_save()
            if not survived:
                await self._end_run(interaction, outcome, loot_line, "died")
                return
            else:
                outcome["message"] += "\n\n**Death Save!** You barely cling to life..."
                self.run.strikes = MAX_STRIKES - 1
                self.session.commit()

        next_node = get_current_node(self.run)
        if not next_node:
            await self._end_run(interaction, outcome, loot_line, "completed")
            return

        result_embed = discord.Embed(
            title="Outcome" if outcome["success"] else "Outcome",
            description=outcome["message"] + loot_line,
            color=0x2ecc71 if outcome["success"] else 0xe74c3c
        )
        result_embed.add_field(
            name="Strikes",
            value=f"{'X' * self.run.strikes}{'O' * (MAX_STRIKES - self.run.strikes)}",
            inline=True
        )
        result_embed.set_footer(text="Press Continue to face the next encounter.")

        self.clear_items()
        continue_btn = discord.ui.Button(
            label="Continue ->",
            style=discord.ButtonStyle.success,
            custom_id="continue"
        )
        continue_btn.callback = self._continue_run
        self.add_item(continue_btn)

        flee_btn = discord.ui.Button(
            label="Flee Dungeon",
            style=discord.ButtonStyle.danger,
            custom_id="flee"
        )
        flee_btn.callback = self.flee_dungeon
        self.add_item(flee_btn)

        await interaction.response.edit_message(embed=result_embed, view=self)

    async def _continue_run(self, interaction: discord.Interaction):
        next_node = get_current_node(self.run)
        if not next_node:
            await interaction.response.edit_message(
                content="Run complete!",
                embed=None,
                view=None
            )
            return
        self.node = next_node
        self._add_choice_buttons()
        embed = self.build_node_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _end_run(self, interaction, outcome, loot_line, result: str):
        loot = json.loads(self.run.loot_this_run)
        loot_names = [ITEMS_BY_ID.get(i, {}).get("name", i) for i in loot]

        complete_run(self.session, self.player, self.run, result)

        if result == "completed":
            color = 0x2ecc71
            title = "Dungeon Complete!"
            desc  = outcome["message"] + loot_line + "\n\nYou emerge victorious from the dungeon."
        elif result == "fled":
            color = 0xf39c12
            title = "You Fled!"
            desc  = "You escaped with your life - and whatever you had on you."
        else:
            color = 0x2c2c2c
            title = "You Died."
            desc  = "The dungeon claimed you. Better luck next cycle."

        embed = discord.Embed(title=title, description=desc, color=color)
        embed.add_field(
            name="Items Recovered",
            value=", ".join(loot_names) if loot_names else "None",
            inline=False
        )
        embed.set_footer(text="Your loot has been added to your bank. Come back tomorrow.")
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)
        self.session.close()

    async def flee_dungeon(self, interaction: discord.Interaction):
        loot = json.loads(self.run.loot_this_run)
        complete_run(self.session, self.player, self.run, "fled")

        loot_names = [ITEMS_BY_ID.get(i, {}).get("name", i) for i in loot]

        embed = discord.Embed(
            title="You Fled!",
            description="You escaped with your life - and whatever you had on you.",
            color=0xf39c12
        )
        embed.add_field(
            name="Items Kept",
            value=", ".join(loot_names) if loot_names else "None",
            inline=False
        )
        embed.set_footer(text="Your loot has been added to your bank. Come back tomorrow.")
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)
        self.session.close()


class ExploreCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="explore", description="Explore the dungeon - face the next encounter.")
    async def explore(self, interaction: discord.Interaction):
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
                    ephemeral=True
                )
                return

            run = session.query(ActiveRun).filter_by(
                player_id=player.id
            ).first()

            if not run:
                await interaction.response.send_message(
                    "You are not in a dungeon. Use /dungeonprep to enter one.",
                    ephemeral=True
                )
                return

            node = get_current_node(run)
            if not node:
                complete_run(session, player, run, "completed")
                await interaction.response.send_message(
                    "You have cleared the dungeon! Your loot has been added to your bank.",
                    ephemeral=True
                )
                return

            view = NodeView(session, player, run, node)
            embed = view.build_node_embed()
            await interaction.response.send_message(embed=embed, view=view)

        except Exception as e:
            session.close()
            raise e


async def setup(bot):
    await bot.add_cog(ExploreCog(bot))
