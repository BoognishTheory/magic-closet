import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player, ActiveRun, BankItem, RunHistory, SkillPoints
from game.access import has_access, deny_access
from game.run_manager import resolve_node, roll_death_save, MAX_STRIKES
from game.level_up import apply_xp_and_check_levelup, post_levelup_message
from game.char_level import apply_char_win, post_char_levelup_message, WIN_COMBAT, WIN_SOCIAL
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

# Node types that count as combat wins when resolved by fighting
COMBAT_NODE_TYPES = {"combat"}

# Node types that count as social wins when resolved successfully
SOCIAL_NODE_TYPES = {"social", "npc_encounter"}


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
    if not success:
        return 0
    node_type = node.get("type", "").lower()
    tranche   = NODE_TRANCHE_MAP.get(node_type)
    if tranche is None:
        return 0
    return DUNGEON_NODE_XP.get(tranche, 0)


def get_win_type(node: dict, success: bool, choice: str) -> str | None:
    """
    Returns WIN_COMBAT or WIN_SOCIAL if this outcome counts as a win.
    Returns None if no win should be awarded.

    Combat win: combat node resolved successfully by fighting (not fleeing).
    Social win: social or NPC encounter node resolved successfully.
    """
    if not success:
        return None
    node_type = node.get("type", "").lower()
    if node_type in COMBAT_NODE_TYPES and choice.lower() != "flee":
        return WIN_COMBAT
    if node_type in SOCIAL_NODE_TYPES:
        return WIN_SOCIAL
    return None


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


class NodeView(discord.ui.View):
    def __init__(self, session, player, run, node):
        super().__init__(timeout=120)
        self.session = session
        self.player  = player
        self.run     = run
        self.node    = node
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
        flee = discord.ui.Button(
            label="Flee Dungeon",
            style=discord.ButtonStyle.danger,
            custom_id="flee"
        )
        flee.callback = self.flee_dungeon
        self.add_item(flee)

    def _make_callback(self, choice: str):
        async def cb(interaction): await self._handle_choice(interaction, choice)
        return cb

    def build_node_embed(self) -> discord.Embed:
        dungeon        = DUNGEONS_BY_ID.get(self.run.dungeon_id, {})
        total          = len(json.loads(self.run.node_sequence))
        next_threshold = SHOP_LEVEL_THRESHOLDS.get(self.player.shop_level or 1, 999)

        embed = discord.Embed(
            title=self.node["title"],
            description=self.node["description"],
            color=0xe74c3c
        )
        embed.add_field(name="Dungeon",  value=dungeon.get("name", "Unknown"),                    inline=True)
        embed.add_field(name="Progress", value=f"{self.run.nodes_completed + 1} / {total}",       inline=True)
        embed.add_field(name="Strikes",  value=f"{'X' * self.run.strikes}{'O' * (MAX_STRIKES - self.run.strikes)}", inline=True)
        embed.add_field(name="Weapon",   value=self.run.weapon_slot or "None",                    inline=True)
        embed.add_field(name="Spell",    value=self.run.spell_slot or "None",                     inline=True)
        embed.add_field(name="Shop XP",  value=f"{self.player.xp or 0} / {next_threshold} (Lv {self.player.shop_level or 1})", inline=True)
        embed.set_footer(text="Choose your action.")
        return embed

    async def _handle_choice(self, interaction: discord.Interaction, choice: str):
        outcome = resolve_node(self.run, self.node, choice, self.player)

        if outcome["strike"]:
            self.run.strikes += 1

        # Shop XP
        node_xp      = get_node_xp(self.node, outcome["success"])
        shop_levelled = False
        sp            = None
        if node_xp > 0:
            sp = self.session.query(SkillPoints).filter_by(player_id=self.player.id).first()
            shop_levelled, _ = apply_xp_and_check_levelup(self.player, sp, node_xp)

        # Character win
        win_type      = get_win_type(self.node, outcome["success"], choice)
        char_levelled = False
        char_new_lvl  = self.player.char_level or 1
        if win_type:
            char_levelled, char_new_lvl = apply_char_win(self.player, win_type)

        # Loot
        loot_line = ""
        if outcome["loot_item"]:
            add_loot_to_run(self.session, self.player, self.run, outcome["loot_item"])
            loot_line = f"\n\nYou found: **{ITEMS_BY_ID.get(outcome['loot_item'], {}).get('name', outcome['loot_item'])}**"

        self.run.nodes_completed += 1
        self.session.commit()

        # Post level-up messages to TMC channel
        if shop_levelled:
            await post_levelup_message(
                interaction.guild,
                self.player.shop_name,
                interaction.user.display_name,
                self.player.shop_level,
                sp,
            )
        if char_levelled:
            await post_char_levelup_message(
                interaction.guild,
                self.player.shop_name,
                interaction.user.display_name,
                char_new_lvl,
                self.player,
            )

        # Death check
        if self.run.strikes >= MAX_STRIKES:
            if not roll_death_save():
                await self._end_run(interaction, outcome, loot_line, "died"); return
            else:
                outcome["message"] += "\n\n**Death Save!** You barely cling to life..."
                self.run.strikes = MAX_STRIKES - 1
                self.session.commit()

        next_node = get_current_node(self.run)
        if not next_node:
            await self._end_run(interaction, outcome, loot_line, "completed"); return

        next_threshold = SHOP_LEVEL_THRESHOLDS.get(self.player.shop_level or 1, 999)
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
            result_embed.add_field(
                name="Shop XP",
                value=f"+{node_xp} XP  |  {self.player.xp} / {next_threshold} (Lv {self.player.shop_level})",
                inline=True
            )
        if outcome.get("stat_boosted") and outcome.get("stat_name"):
            stat_val = getattr(self.player, outcome["stat_name"], None) or 1
            result_embed.add_field(
                name="Stat Bonus",
                value=f"{outcome['stat_name'].capitalize()} {stat_val}/10 contributed to this outcome.",
                inline=True
            )
        if win_type:
            char_threshold = __import__('config').CHAR_LEVEL_THRESHOLDS.get(self.player.char_level or 1, 999)
            result_embed.add_field(
                name="Char XP",
                value=f"+1 {'Combat' if win_type == WIN_COMBAT else 'Social'} win  |  {self.player.char_xp} / {char_threshold} (Char Lv {self.player.char_level or 1})",
                inline=True
            )
        if shop_levelled:
            result_embed.add_field(name="Shop Level Up!", value="Bizard has sent you a message.", inline=False)
        if char_levelled:
            result_embed.add_field(name="Character Level Up!", value=f"Reached Char Level {char_new_lvl}. Check your channel.", inline=False)
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
            await interaction.response.edit_message(content="Run complete!", embed=None, view=None); return
        self.node = next_node
        self._add_choice_buttons()
        await interaction.response.edit_message(embed=self.build_node_embed(), view=self)

    async def _end_run(self, interaction, outcome, loot_line, result: str):
        loot_names = [ITEMS_BY_ID.get(i, {}).get("name", i) for i in json.loads(self.run.loot_this_run)]
        complete_run(self.session, self.player, self.run, result)

        titles = {"completed": "Dungeon Complete!", "fled": "You Fled!", "died": "You Died."}
        colors = {"completed": 0x2ecc71, "fled": 0xf39c12, "died": 0x2c2c2c}
        descs  = {
            "completed": outcome["message"] + loot_line + "\n\nYou emerge victorious.",
            "fled":      "You escaped with your life.",
            "died":      "The dungeon claimed you. Better luck next cycle.",
        }
        embed = discord.Embed(title=titles[result], description=descs[result], color=colors[result])
        embed.add_field(name="Items Recovered", value=", ".join(loot_names) if loot_names else "None", inline=False)
        next_threshold = SHOP_LEVEL_THRESHOLDS.get(self.player.shop_level or 1, 999)
        embed.add_field(name="Shop XP", value=f"{self.player.xp or 0} / {next_threshold} (Lv {self.player.shop_level or 1})", inline=True)
        char_threshold = __import__('config').CHAR_LEVEL_THRESHOLDS.get(self.player.char_level or 1, 999)
        embed.add_field(name="Char XP", value=f"{self.player.char_xp or 0} / {char_threshold} (Char Lv {self.player.char_level or 1})", inline=True)
        embed.set_footer(text="Your loot has been added to your bank. Come back tomorrow.")
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)
        self.session.close()

    async def flee_dungeon(self, interaction: discord.Interaction):
        loot_names = [ITEMS_BY_ID.get(i, {}).get("name", i) for i in json.loads(self.run.loot_this_run)]
        complete_run(self.session, self.player, self.run, "fled")
        embed = discord.Embed(title="You Fled!", description="You escaped with your life.", color=0xf39c12)
        embed.add_field(name="Items Kept", value=", ".join(loot_names) if loot_names else "None", inline=False)
        embed.set_footer(text="Your loot has been added to your bank. Come back tomorrow.")
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)
        self.session.close()


class ExploreCog(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="explore", description="Explore the dungeon - face the next encounter.")
    async def explore(self, interaction: discord.Interaction):
        if not has_access(interaction): await deny_access(interaction); return
        if not await check_shop_channel(interaction): return

        session = get_session()
        try:
            player = session.query(Player).filter_by(discord_id=str(interaction.user.id)).first()
            if not player:
                await interaction.response.send_message("No player found. Run /prepstore first.", ephemeral=True); return
            run = session.query(ActiveRun).filter_by(player_id=player.id).first()
            if not run:
                await interaction.response.send_message("You are not in a dungeon. Use /dungeonprep to enter one.", ephemeral=True); return
            node = get_current_node(run)
            if not node:
                complete_run(session, player, run, "completed")
                await interaction.response.send_message("You have cleared the dungeon! Your loot has been added to your bank.", ephemeral=True); return
            view = NodeView(session, player, run, node)
            await interaction.response.send_message(embed=view.build_node_embed(), view=view)
        except Exception as e:
            session.close(); raise e


async def setup(bot):
    await bot.add_cog(ExploreCog(bot))
