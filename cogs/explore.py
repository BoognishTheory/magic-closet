import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player, ActiveRun, BankItem, RunHistory
from game.access import has_access, deny_access
from game.run_manager import resolve_node, roll_death_save, MAX_STRIKES
from cogs.startshop import check_shop_channel
from config import DUNGEON_NODE_XP, NODE_TRANCHE_MAP, SHOP_LEVEL_THRESHOLDS
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_current_node(run) -> dict:
    sequence = json.loads(run.node_sequence)
    if run.nodes_completed >= len(sequence):
        return None
    return NODES_BY_ID.get(sequence[run.nodes_completed])


def add_loot_to_run(session, player, run, item_id: str):
    loot = json.loads(run.loot_this_run)
    loot.append(item_id)
    run.loot_this_run = json.dumps(loot)
    item_def = ITEMS_BY_ID.get(item_id, {})
    session.add(BankItem(
        player_id=player.id,
        item_id=item_id,
        rarity=item_def.get("rarity", "common"),
        on_floor=False,
        acquired_at=datetime.utcnow()
    ))
    session.commit()


def get_node_xp(node: dict, success: bool) -> int:
    """
    Returns XP for a node resolution.
    Uses NODE_TRANCHE_MAP to look up tranche from node type.
    Returns 0 on failure or for non-XP node types (Discovery, Opening).
    """
    if not success:
        return 0
    node_type = node.get("type", "").lower()
    tranche = NODE_TRANCHE_MAP.get(node_type)
    if tranche is None:
        return 0
    return DUNGEON_NODE_XP.get(tranche, 0)


def apply_xp_and_check_levelup(player, xp_earned: int) -> tuple[bool, int]:
    """
    Adds XP to player and checks for level-up.
    Returns (levelled_up: bool, new_level: int).
    """
    if xp_earned <= 0:
        return False, player.shop_level
    player.xp = (player.xp or 0) + xp_earned
    threshold = SHOP_LEVEL_THRESHOLDS.get(player.shop_level, 999)
    if player.xp >= threshold:
        player.xp -= threshold
        player.shop_level += 1
        return True, player.shop_level
    return False, player.shop_level


def complete_run(session, player, run, outcome: str):
    loot = json.loads(run.loot_this_run)
    session.add(RunHistory(
        player_id=player.id,
        dungeon_id=run.dungeon_id,
        outcome=outcome,
        nodes_completed=run.nodes_completed,
        items_recovered=json.dumps(loot),
        coin_spent=DUNGEONS_BY_ID.get(run.dungeon_id, {}).get("entry_cost", 0),
        created_at=datetime.utcnow()
    ))
    session.delete(run)
    player.dungeon_complete = True
    player.last_active = datetime.utcnow()
    session.commit()


# ---------------------------------------------------------------------------
# NodeView
# ---------------------------------------------------------------------------

class NodeView(discord.ui.View):
    def __init__(self, session, player, run, node):
        super().__init__(timeout=120)
        self.session  = session
        self.player   = player
        self.run      = run
        self.node     = node
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
        dungeon    = DUNGEONS_BY_ID.get(self.run.dungeon_id, {})
        sequence   = json.loads(self.run.node_sequence)
        total_nodes = len(sequence)
        next_threshold = SHOP_LEVEL_THRESHOLDS.get(self.player.shop_level, 999)

        embed = discord.Embed(
            title=self.node["title"],
            description=self.node["description"],
            color=0xe74c3c
        )
        embed.add_field(name="Dungeon",   value=dungeon.get("name", "Unknown"),              inline=True)
        embed.add_field(name="Progress",  value=f"{self.run.nodes_completed + 1} / {total_nodes}", inline=True)
        embed.add_field(name="Strikes",   value=f"{'X' * self.run.strikes}{'O' * (MAX_STRIKES - self.run.strikes)}", inline=True)
        embed.add_field(name="Weapon",    value=self.run.weapon_slot or "None",              inline=True)
        embed.add_field(name="Spell",     value=self.run.spell_slot or "None",               inline=True)
        embed.add_field(
            name="Shop XP",
            value=f"{self.player.xp or 0} / {next_threshold} (Level {self.player.shop_level or 1})",
            inline=True,
        )
        embed.set_footer(text="Choose your action.")
        return embed

    async def _handle_choice(self, interaction: discord.Interaction, choice: str):
        outcome = resolve_node(self.run, self.node, choice)

        if outcome["strike"]:
            self.run.strikes += 1

        # Award node XP
        node_xp = get_node_xp(self.node, outcome["success"])
        levelled_up = False
        if node_xp > 0:
            levelled_up, _ = apply_xp_and_check_levelup(self.player, node_xp)

        loot_line = ""
        if outcome["loot_item"]:
            add_loot_to_run(self.session, self.player, self.run, outcome["loot_item"])
            item_def  = ITEMS_BY_ID.get(outcome["loot_item"], {})
            loot_line = f"\n\nYou found: **{item_def.get('name', outcome['loot_item'])}**"

        self.run.nodes_completed += 1
        self.session.commit()

        # Death check
        if self.run.strikes >= MAX_STRIKES:
            survived = roll_death_save()
            if not survived:
                await self._end_run(interaction, outcome, loot_line, "died")
                return
            else:
                outcome["message"] += "\n\n**Death Save!** You barely cling to life..."
                self.run.strikes = MAX_STRIKES - 1
                self.session.commit()

        # Check if run is complete
        next_node = get_current_node(self.run)
        if not next_node:
            await self._end_run(interaction, outcome, loot_line, "completed")
            return

        # Build outcome embed with XP feedback
        result_embed = discord.Embed(
            title="Outcome",
            description=outcome["message"] + loot_line,
            color=0x2ecc71 if outcome["success"] else 0xe74c3c
        )
        result_embed.add_field(
            name="Strikes",
            value=f"{'X' * self.run.strikes}{'O' * (MAX_STRIKES - self.run.strikes)}",
            inline=True
        )
        if node_xp > 0:
            next_threshold = SHOP_LEVEL_THRESHOLDS.get(self.player.shop_level, 999)
            result_embed.add_field(
                name="Shop XP",
                value=f"+{node_xp} XP  |  {self.player.xp} / {next_threshold} (Level {self.player.shop_level})",
                inline=True
            )
        if levelled_up:
            result_embed.add_field(
                name="LEVEL UP!",
                value=f"Your Magic Closet reached **Level {self.player.shop_level}**!",
                inline=False
            )
        result_embed.set_footer(text="Press Continue to face the next encounter.")

        self.clear_items()
        cont = discord.ui.Button(label="Continue ->", style=discord.ButtonStyle.success, custom_id="continue")
        cont.callback = self._continue_run
        self.add_item(cont)
        flee = discord.ui.Button(label="Flee Dungeon", style=discord.ButtonStyle.danger, custom_id="flee")
        flee.callback = self.flee_dungeon
        self.add_item(flee)

        await interaction.response.edit_message(embed=result_embed, view=self)

    async def _continue_run(self, interaction: discord.Interaction):
        next_node = get_current_node(self.run)
        if not next_node:
            await interaction.response.edit_message(content="Run complete!", embed=None, view=None)
            return
        self.node = next_node
        self._add_choice_buttons()
        await interaction.response.edit_message(embed=self.build_node_embed(), view=self)

    async def _end_run(self, interaction, outcome, loot_line, result: str):
        loot      = json.loads(self.run.loot_this_run)
        loot_names = [ITEMS_BY_ID.get(i, {}).get("name", i) for i in loot]
        complete_run(self.session, self.player, self.run, result)

        titles = {"completed": "Dungeon Complete!", "fled": "You Fled!", "died": "You Died."}
        colors = {"completed": 0x2ecc71, "fled": 0xf39c12, "died": 0x2c2c2c}
        descs  = {
            "completed": outcome["message"] + loot_line + "\n\nYou emerge victorious from the dungeon.",
            "fled":      "You escaped with your life - and whatever you had on you.",
            "died":      "The dungeon claimed you. Better luck next cycle.",
        }

        embed = discord.Embed(title=titles[result], description=descs[result], color=colors[result])
        embed.add_field(
            name="Items Recovered",
            value=", ".join(loot_names) if loot_names else "None",
            inline=False
        )
        next_threshold = SHOP_LEVEL_THRESHOLDS.get(self.player.shop_level, 999)
        embed.add_field(
            name="Shop XP",
            value=f"{self.player.xp} / {next_threshold} (Level {self.player.shop_level})",
            inline=False
        )
        embed.set_footer(text="Your loot has been added to your bank. Come back tomorrow.")
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)
        self.session.close()

    async def flee_dungeon(self, interaction: discord.Interaction):
        loot       = json.loads(self.run.loot_this_run)
        loot_names = [ITEMS_BY_ID.get(i, {}).get("name", i) for i in loot]
        complete_run(self.session, self.player, self.run, "fled")

        embed = discord.Embed(title="You Fled!", description="You escaped with your life.", color=0xf39c12)
        embed.add_field(name="Items Kept", value=", ".join(loot_names) if loot_names else "None", inline=False)
        embed.set_footer(text="Your loot has been added to your bank. Come back tomorrow.")
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)
        self.session.close()


# ---------------------------------------------------------------------------
# ExploreCog
# ---------------------------------------------------------------------------

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

            run = session.query(ActiveRun).filter_by(player_id=player.id).first()

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

            view  = NodeView(session, player, run, node)
            embed = view.build_node_embed()
            await interaction.response.send_message(embed=embed, view=view)

        except Exception as e:
            session.close()
            raise e


async def setup(bot):
    await bot.add_cog(ExploreCog(bot))
