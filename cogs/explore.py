"""
cogs/explore.py
Dungeon exploration with full multi-round combat system.

Combat nodes present three paths:
  FIGHT — multi-round (5 round cap). HP bars each round. Enemy retreats at cap.
           Player death = run over, portal rescue, random loot dropped.
  TALK  — 3-stage compressed social path. Charm modifier. Enemy-specific outcomes.
  FLEE  — opposed agility check. Fortune bonus. Fail = hit once then escape.

Non-combat nodes use single-roll resolution (social, trap, puzzle, environmental, etc.)
"""

import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player, ActiveRun, BankItem, RunHistory, SkillPoints
from game.access import has_access, deny_access
from game.run_manager import (
    resolve_node,
    roll_death_save,
    start_combat,
    resolve_fight_round,
    resolve_flee,
    resolve_talk_outcome,
    score_talk_choice,
    get_talk_stage_description,
    calc_hp,
    get_stat,
    roll_loot_public,
    COMBAT_ROUND_CAP,
    TALK_STAGES,
    TALK_STAGE_LABELS,
    MAX_STRIKES,
)
from game.level_up import apply_xp_and_check_levelup, post_levelup_message
from game.char_level import apply_char_win, post_char_levelup_message, WIN_COMBAT, WIN_SOCIAL
from cogs.startshop import check_shop_channel
from config import DUNGEON_NODE_XP, NODE_TRANCHE_MAP, SHOP_LEVEL_THRESHOLDS, CHAR_LEVEL_THRESHOLDS
from datetime import datetime
import json
import random

with open("data/node_templates.json", "r") as f:
    NODES_DATA = json.load(f)["nodes"]
NODES_BY_ID = {n["id"]: n for n in NODES_DATA}

with open("data/items.json", "r") as f:
    ITEMS_DATA = json.load(f)["items"]
ITEMS_BY_ID = {i["id"]: i for i in ITEMS_DATA}

with open("data/dungeons.json", "r") as f:
    DUNGEONS_DATA = json.load(f)["dungeons"]
DUNGEONS_BY_ID = {d["id"]: d for d in DUNGEONS_DATA}

EMBED_COLOR_COMBAT   = 0xe74c3c
EMBED_COLOR_SUCCESS  = 0x2ecc71
EMBED_COLOR_FLEE     = 0xf39c12
EMBED_COLOR_DEAD     = 0x2c2c2c
EMBED_COLOR_TALK     = 0x3498db


# ---------------------------------------------------------------------------
# Shared helpers
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
    if not success:
        return 0
    tranche = NODE_TRANCHE_MAP.get(node.get("type", "").lower())
    return DUNGEON_NODE_XP.get(tranche, 0) if tranche else 0


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


def hp_bar(current: int, maximum: int, length: int = 8) -> str:
    filled = max(0, min(length, round((current / max(maximum, 1)) * length)))
    return f"[{'█' * filled}{'░' * (length - filled)}] {current}/{maximum}"


async def award_xp_and_wins(
    session, player, node: dict, success: bool,
    win_type: str | None, interaction: discord.Interaction
):
    """Award shop XP and character wins. Post level-up messages if triggered."""
    node_xp = get_node_xp(node, success)
    if node_xp > 0:
        sp          = session.query(SkillPoints).filter_by(player_id=player.id).first()
        shop_lvl_up, new_shop_lvl = apply_xp_and_check_levelup(player, sp, node_xp)
        session.commit()
        if shop_lvl_up:
            await post_levelup_message(
                interaction.guild, player.shop_name,
                interaction.user.display_name, new_shop_lvl, sp
            )

    if win_type:
        char_lvl_up, new_char_lvl = apply_char_win(player, win_type)
        session.commit()
        if char_lvl_up:
            await post_char_levelup_message(
                interaction.guild, player.shop_name,
                interaction.user.display_name, new_char_lvl, player
            )


# ---------------------------------------------------------------------------
# Portal death rescue — run ends, random loot dropped
# ---------------------------------------------------------------------------

async def handle_player_death(
    session, player, run,
    interaction: discord.Interaction,
    view: discord.ui.View,
):
    """
    Player HP hit 0. Run ends. Random subset of loot dropped.
    Player ported back to shop with remaining items.
    """
    loot          = json.loads(run.loot_this_run)
    items_kept    = []
    items_dropped = []

    # Drop roughly half the loot randomly
    for item_id in loot:
        if random.random() < 0.5:
            items_dropped.append(item_id)
        else:
            items_kept.append(item_id)

    # Remove dropped items from DB
    for item_id in items_dropped:
        existing = session.query(BankItem).filter_by(
            player_id=player.id, item_id=item_id, on_floor=False
        ).first()
        if existing:
            session.delete(existing)

    run.loot_this_run = json.dumps(items_kept)
    complete_run(session, player, run, "died")

    kept_names    = [ITEMS_BY_ID.get(i, {}).get("name", i) for i in items_kept]
    dropped_names = [ITEMS_BY_ID.get(i, {}).get("name", i) for i in items_dropped]

    embed = discord.Embed(
        title="The Portal Pulls You Back",
        description=(
            "You hit the floor. The portal tears open and drags you through "
            "before anything worse can happen.\n\n"
            "*Bizard watches you land on the shop floor. "
            "He says nothing. He puts the kettle on.*"
        ),
        color=EMBED_COLOR_DEAD,
    )
    embed.add_field(
        name="Items Kept",
        value=", ".join(kept_names) if kept_names else "Nothing made it through.",
        inline=False,
    )
    if items_dropped:
        embed.add_field(
            name="Lost in Transit",
            value=", ".join(dropped_names),
            inline=False,
        )
    embed.set_footer(text="Come back tomorrow. The dungeon will still be there.")
    view.clear_items()
    await interaction.response.edit_message(embed=embed, view=view)
    session.close()


# ---------------------------------------------------------------------------
# Combat node selection view — Fight / Talk / Flee
# ---------------------------------------------------------------------------

class CombatChoiceView(discord.ui.View):
    """Initial choice view shown at a combat node."""

    def __init__(self, session, player, run, node):
        super().__init__(timeout=120)
        self.session = session
        self.player  = player
        self.run     = run
        self.node    = node

    def build_embed(self) -> discord.Embed:
        dungeon  = DUNGEONS_BY_ID.get(self.run.dungeon_id, {})
        sequence = json.loads(self.run.node_sequence)
        total    = len(sequence)
        vit      = get_stat(self.player, "vitality")
        player_hp = calc_hp(vit)

        embed = discord.Embed(
            title=self.node.get("title", "Combat"),
            description=self.node.get("description", ""),
            color=EMBED_COLOR_COMBAT,
        )
        embed.add_field(name="Dungeon",   value=dungeon.get("name", "Unknown"),           inline=True)
        embed.add_field(name="Progress",  value=f"{self.run.nodes_completed + 1} / {total}", inline=True)
        embed.add_field(name="Your HP",   value=hp_bar(player_hp, player_hp),              inline=False)
        embed.set_footer(text="Choose your approach.")
        return embed

    @discord.ui.button(label="⚔️ Fight", style=discord.ButtonStyle.danger,     custom_id="combat_fight")
    async def fight(self, interaction: discord.Interaction, button: discord.ui.Button):
        combat_state = start_combat(self.node, self.player)
        view = FightView(self.session, self.player, self.run, self.node, combat_state)
        await interaction.response.edit_message(embed=view.build_round_embed(), view=view)

    @discord.ui.button(label="🗣️ Talk", style=discord.ButtonStyle.primary,    custom_id="combat_talk")
    async def talk(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = TalkView(self.session, self.player, self.run, self.node)
        await interaction.response.edit_message(embed=view.build_stage_embed(), view=view)

    @discord.ui.button(label="🏃 Flee", style=discord.ButtonStyle.secondary,  custom_id="combat_flee")
    async def flee(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve_flee(interaction)

    async def _resolve_flee(self, interaction: discord.Interaction):
        enemy  = start_combat(self.node, self.player)["enemy"]
        result = resolve_flee(self.player, enemy)

        vit       = get_stat(self.player, "vitality")
        player_hp = calc_hp(vit)

        if result["success"]:
            loot      = json.loads(self.run.loot_this_run)
            loot_names = [ITEMS_BY_ID.get(i, {}).get("name", i) for i in loot]
            complete_run(self.session, self.player, self.run, "fled")
            embed = discord.Embed(
                title="You Fled — Clean Escape",
                description=(
                    f"You rolled {result['player_roll']} + {result['player_bonus']} = "
                    f"**{result['player_total']}** vs {enemy['name']}'s "
                    f"{result['enemy_roll']} + {result['enemy_agility']} = "
                    f"{result['enemy_total']}.\n\n"
                    f"You were faster. You're out."
                ),
                color=EMBED_COLOR_FLEE,
            )
            embed.add_field(name="Items Kept", value=", ".join(loot_names) if loot_names else "None", inline=False)
            embed.set_footer(text="Your loot has been added to your bank.")
            self.clear_items()
            await interaction.response.edit_message(embed=embed, view=self)
            self.session.close()
        else:
            # Hit once, then escaped
            self.player.vitality = max(0, get_stat(self.player, "vitality"))
            dmg = result["damage"]

            embed = discord.Embed(
                title="You Fled — Hit on the Way Out",
                description=(
                    f"You rolled {result['player_roll']} + {result['player_bonus']} = "
                    f"**{result['player_total']}** vs {enemy['name']}'s "
                    f"{result['enemy_roll']} + {result['enemy_agility']} = "
                    f"**{result['enemy_total']}**.\n\n"
                    f"Not fast enough. {enemy['name']} caught you on the way out. "
                    f"**-{dmg} HP**. You're out anyway — it can't follow."
                ),
                color=EMBED_COLOR_FLEE,
            )

            # Check if this flee damage killed the player
            new_hp = calc_hp(get_stat(self.player, "vitality")) - dmg
            if new_hp <= 0:
                await handle_player_death(self.session, self.player, self.run, interaction, self)
                return

            loot      = json.loads(self.run.loot_this_run)
            loot_names = [ITEMS_BY_ID.get(i, {}).get("name", i) for i in loot]
            complete_run(self.session, self.player, self.run, "fled")
            embed.add_field(name="Items Kept", value=", ".join(loot_names) if loot_names else "None", inline=False)
            embed.set_footer(text="Your loot has been added to your bank.")
            self.clear_items()
            await interaction.response.edit_message(embed=embed, view=self)
            self.session.close()


# ---------------------------------------------------------------------------
# Fight view — multi-round combat
# ---------------------------------------------------------------------------

class FightView(discord.ui.View):
    def __init__(self, session, player, run, node, combat_state: dict):
        super().__init__(timeout=120)
        self.session      = session
        self.player       = player
        self.run          = run
        self.node         = node
        self.enemy        = combat_state["enemy"]
        self.enemy_hp     = combat_state["enemy_hp"]
        self.enemy_max    = combat_state["enemy_max"]
        self.player_hp    = combat_state["player_hp"]
        self.player_max   = combat_state["player_max"]
        self.round        = combat_state["round"]
        self.last_round   = None

    def build_round_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"⚔️ Combat — Round {self.round}",
            description=f"**{self.enemy['name']}**\n{self.enemy['description']}",
            color=EMBED_COLOR_COMBAT,
        )
        embed.add_field(
            name=f"{self.enemy['name']} HP",
            value=hp_bar(self.enemy_hp, self.enemy_max),
            inline=False,
        )
        embed.add_field(
            name="Your HP",
            value=hp_bar(self.player_hp, self.player_max),
            inline=False,
        )
        if self.last_round:
            embed.add_field(
                name="Last Round",
                value=f"{self.last_round['player_attack_line']}\n{self.last_round['enemy_attack_line']}",
                inline=False,
            )
        embed.set_footer(
            text=f"Round {self.round} of {COMBAT_ROUND_CAP}  ·  Fight to the end or flee."
        )
        return embed

    @discord.ui.button(label="Strike", style=discord.ButtonStyle.danger,    custom_id="fight_strike")
    async def strike(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve_round(interaction)

    @discord.ui.button(label="🏃 Flee", style=discord.ButtonStyle.secondary, custom_id="fight_flee")
    async def flee(self, interaction: discord.Interaction, button: discord.ui.Button):
        result = resolve_flee(self.player, self.enemy)
        if result["success"]:
            loot_names = [ITEMS_BY_ID.get(i, {}).get("name", i) for i in json.loads(self.run.loot_this_run)]
            complete_run(self.session, self.player, self.run, "fled")
            embed = discord.Embed(
                title="You Fled Mid-Combat",
                description=(
                    f"You broke away. ({result['player_total']} vs {result['enemy_total']})\n\n"
                    f"The {self.enemy['name']} watches you go. Not happy. Not following."
                ),
                color=EMBED_COLOR_FLEE,
            )
            embed.add_field(name="Items Kept", value=", ".join(loot_names) if loot_names else "None", inline=False)
            self.clear_items()
            await interaction.response.edit_message(embed=embed, view=self)
            self.session.close()
        else:
            dmg = result["damage"]
            self.player_hp = max(0, self.player_hp - dmg)
            self.session.commit()
            if self.player_hp <= 0:
                await handle_player_death(self.session, self.player, self.run, interaction, self)
                return
            embed = discord.Embed(
                title="Flee Failed — Still in Combat",
                description=(
                    f"You tried to break away. ({result['player_total']} vs {result['enemy_total']})\n\n"
                    f"{self.enemy['name']} caught you. **-{dmg} HP**. "
                    f"You're still in this."
                ),
                color=EMBED_COLOR_COMBAT,
            )
            embed.add_field(name="Your HP", value=hp_bar(self.player_hp, self.player_max), inline=False)
            await interaction.response.edit_message(embed=embed, view=self)

    async def _resolve_round(self, interaction: discord.Interaction):
        result = resolve_fight_round(
            self.player_hp, self.enemy_hp, self.player, self.enemy
        )
        self.player_hp  = result["player_hp"]
        self.enemy_hp   = result["enemy_hp"]
        self.last_round = result
        self.round     += 1

        # Enemy defeated
        if self.enemy_hp <= 0:
            await self._victory(interaction)
            return

        # Player defeated
        if self.player_hp <= 0:
            await handle_player_death(self.session, self.player, self.run, interaction, self)
            return

        # Round cap — enemy retreats
        if self.round > COMBAT_ROUND_CAP:
            await self._enemy_retreat(interaction)
            return

        await interaction.response.edit_message(embed=self.build_round_embed(), view=self)

    async def _victory(self, interaction: discord.Interaction):
        loot_item = roll_loot_public(self.run.dungeon_id, "combat")
        loot_line = ""
        if loot_item:
            add_loot_to_run(self.session, self.player, self.run, loot_item)
            loot_line = f"\n\nYou found: **{ITEMS_BY_ID.get(loot_item, {}).get('name', loot_item)}**"

        self.run.nodes_completed += 1
        await award_xp_and_wins(
            self.session, self.player, self.node, True, WIN_COMBAT, interaction
        )
        self.session.commit()

        next_node = get_current_node(self.run)
        xp_threshold = SHOP_LEVEL_THRESHOLDS.get(self.player.shop_level or 1, 999)

        embed = discord.Embed(
            title=f"⚔️ Victory — {self.enemy['name']} Defeated",
            description=(
                self.node.get("success_text", "You win.") + loot_line
            ),
            color=EMBED_COLOR_SUCCESS,
        )
        embed.add_field(
            name="Your HP",
            value=hp_bar(self.player_hp, self.player_max),
            inline=True,
        )
        embed.add_field(
            name="Shop XP",
            value=f"{self.player.xp or 0} / {xp_threshold} (Lv {self.player.shop_level or 1})",
            inline=True,
        )

        if not next_node:
            await self._end_run(interaction, embed, "completed")
            return

        self.clear_items()
        cont = discord.ui.Button(label="Continue →", style=discord.ButtonStyle.success, custom_id="continue")
        flee = discord.ui.Button(label="🏃 Flee Dungeon", style=discord.ButtonStyle.secondary, custom_id="flee_all")

        async def continue_cb(i):
            node_view = NodeView(self.session, self.player, self.run, next_node)
            await i.response.edit_message(embed=node_view.build_node_embed(), view=node_view)

        async def flee_cb(i):
            loot_names = [ITEMS_BY_ID.get(x, {}).get("name", x) for x in json.loads(self.run.loot_this_run)]
            complete_run(self.session, self.player, self.run, "fled")
            e = discord.Embed(title="You Fled!", description="You escaped with your life.", color=EMBED_COLOR_FLEE)
            e.add_field(name="Items Kept", value=", ".join(loot_names) if loot_names else "None", inline=False)
            self.clear_items()
            await i.response.edit_message(embed=e, view=self)
            self.session.close()

        cont.callback = continue_cb
        flee.callback = flee_cb
        self.add_item(cont)
        self.add_item(flee)
        embed.set_footer(text="Press Continue to face the next encounter.")
        await interaction.response.edit_message(embed=embed, view=self)

    async def _enemy_retreat(self, interaction: discord.Interaction):
        self.run.nodes_completed += 1
        await award_xp_and_wins(
            self.session, self.player, self.node, True, WIN_COMBAT, interaction
        )
        self.session.commit()

        loot_item = roll_loot_public(self.run.dungeon_id, "combat")
        loot_line = ""
        if loot_item:
            add_loot_to_run(self.session, self.player, self.run, loot_item)
            loot_line = f"\n\nYou found: **{ITEMS_BY_ID.get(loot_item, {}).get('name', loot_item)}**"

        next_node = get_current_node(self.run)
        embed = discord.Embed(
            title="Combat Over — Enemy Retreated",
            description=self.enemy.get("retreat_excuse", "It leaves.") + loot_line,
            color=EMBED_COLOR_SUCCESS,
        )
        embed.add_field(name="Your HP", value=hp_bar(self.player_hp, self.player_max), inline=True)

        if not next_node:
            await self._end_run(interaction, embed, "completed")
            return

        self.clear_items()
        cont = discord.ui.Button(label="Continue →", style=discord.ButtonStyle.success, custom_id="continue")

        async def continue_cb(i):
            node_view = NodeView(self.session, self.player, self.run, next_node)
            await i.response.edit_message(embed=node_view.build_node_embed(), view=node_view)

        cont.callback = continue_cb
        self.add_item(cont)
        embed.set_footer(text="Press Continue to face the next encounter.")
        await interaction.response.edit_message(embed=embed, view=self)

    async def _end_run(self, interaction, embed, result: str):
        loot_names = [ITEMS_BY_ID.get(i, {}).get("name", i) for i in json.loads(self.run.loot_this_run)]
        complete_run(self.session, self.player, self.run, result)
        embed.add_field(name="Items Recovered", value=", ".join(loot_names) if loot_names else "None", inline=False)
        embed.set_footer(text="Your loot has been added to your bank. Come back tomorrow.")
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)
        self.session.close()


# ---------------------------------------------------------------------------
# Talk view — compressed social path
# ---------------------------------------------------------------------------

class TalkView(discord.ui.View):
    def __init__(self, session, player, run, node):
        super().__init__(timeout=120)
        self.session      = session
        self.player       = player
        self.run          = run
        self.node         = node
        self.enemy        = __import__('game.run_manager', fromlist=['ENEMIES_BY_ID']).ENEMIES_BY_ID.get(
            node.get("enemy_id", "goblin"),
            {"name": "It", "talk_demeanor": "direct"}
        )
        self.stage        = 0
        self.total_score  = 0
        self.disposition  = -1   # combat context penalty

    def build_stage_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🗣️ Talk — {TALK_STAGE_LABELS[self.stage]}",
            description=get_talk_stage_description(self.stage, self.enemy),
            color=EMBED_COLOR_TALK,
        )
        embed.add_field(name="Stage",    value=f"{self.stage + 1} / {TALK_STAGES}", inline=True)
        embed.add_field(name="Opponent", value=self.enemy.get("name", "It"),          inline=True)
        embed.set_footer(
            text="You started this conversation mid-combat. "
                 "You have fewer stages to win them over."
        )
        return embed

    async def _handle_choice(self, interaction: discord.Interaction, choice: str):
        self.total_score += score_talk_choice(self.stage, choice, self.enemy)
        self.stage       += 1

        if self.stage >= TALK_STAGES:
            await self._resolve_talk(interaction)
        else:
            await interaction.response.edit_message(embed=self.build_stage_embed(), view=self)

    async def _resolve_talk(self, interaction: discord.Interaction):
        charm  = get_stat(self.player, "charm")
        result = resolve_talk_outcome(self.total_score, self.disposition, self.enemy)

        if result["success"]:
            # Award social win and XP
            await award_xp_and_wins(
                self.session, self.player, self.node, True, WIN_SOCIAL, interaction
            )

            loot_line = ""
            if result["high_success"] and result["item_reward"]:
                add_loot_to_run(self.session, self.player, self.run, result["item_reward"])
                item_name = ITEMS_BY_ID.get(result["item_reward"], {}).get("name", result["item_reward"])
                loot_line = f"\n\nYou received: **{item_name}**"

            self.run.nodes_completed += 1
            self.session.commit()
            next_node = get_current_node(self.run)

            embed = discord.Embed(
                title=f"🗣️ {'Great Success' if result['high_success'] else 'Success'} — "
                      f"{self.enemy.get('name', 'It')} Stood Down",
                description=result["message"] + loot_line,
                color=EMBED_COLOR_SUCCESS,
            )
            embed.add_field(
                name="Charm",
                value=f"{charm}/10 — applied to this interaction",
                inline=True
            )

            if not next_node:
                loot_names = [ITEMS_BY_ID.get(i, {}).get("name", i) for i in json.loads(self.run.loot_this_run)]
                complete_run(self.session, self.player, self.run, "completed")
                embed.add_field(name="Items Recovered", value=", ".join(loot_names) if loot_names else "None", inline=False)
                embed.set_footer(text="Your loot has been added to your bank. Come back tomorrow.")
                self.clear_items()
                await interaction.response.edit_message(embed=embed, view=self)
                self.session.close()
                return

            self.clear_items()
            cont = discord.ui.Button(label="Continue →", style=discord.ButtonStyle.success, custom_id="continue")

            async def continue_cb(i):
                node_view = NodeView(self.session, self.player, self.run, next_node)
                await i.response.edit_message(embed=node_view.build_node_embed(), view=node_view)

            cont.callback = continue_cb
            self.add_item(cont)
            embed.set_footer(text="Press Continue to face the next encounter.")
            await interaction.response.edit_message(embed=embed, view=self)

        else:
            # Talk failed — transition to fight, enemy attacks first
            combat_state          = start_combat(self.node, self.player)
            combat_state["round"] = 1

            # Enemy gets a free hit
            result_round = __import__('game.run_manager', fromlist=['resolve_fight_round']).resolve_fight_round(
                combat_state["player_hp"], combat_state["enemy_hp"],
                self.player, combat_state["enemy"]
            )
            combat_state["player_hp"] = result_round["player_hp"]
            combat_state["enemy_hp"]  = result_round["enemy_hp"]

            if combat_state["player_hp"] <= 0:
                await handle_player_death(self.session, self.player, self.run, interaction, self)
                return

            embed = discord.Embed(
                title="🗣️ Talk Failed — Combat Resumes",
                description=(
                    f"{result['message']}\n\n"
                    f"{result_round['enemy_attack_line']}"
                ),
                color=EMBED_COLOR_COMBAT,
            )
            embed.set_footer(text="The enemy got a free hit. Now it's your turn.")

            fight_view = FightView(self.session, self.player, self.run, self.node, combat_state)
            fight_view.last_round = result_round
            await interaction.response.edit_message(embed=embed, view=fight_view)

    @discord.ui.button(label="Option A", style=discord.ButtonStyle.primary,   custom_id="talk_a")
    async def choice_a(self, i, b): await self._handle_choice(i, "a")

    @discord.ui.button(label="Option B", style=discord.ButtonStyle.secondary, custom_id="talk_b")
    async def choice_b(self, i, b): await self._handle_choice(i, "b")

    @discord.ui.button(label="Option C", style=discord.ButtonStyle.secondary, custom_id="talk_c")
    async def choice_c(self, i, b): await self._handle_choice(i, "c")


# ---------------------------------------------------------------------------
# Non-combat node view
# ---------------------------------------------------------------------------

class NodeView(discord.ui.View):
    def __init__(self, session, player, run, node):
        super().__init__(timeout=120)
        self.session = session
        self.player  = player
        self.run     = run
        self.node    = node
        self._add_buttons()

    def _add_buttons(self):
        self.clear_items()
        node_type = self.node.get("type", "").lower()
        choices   = self.node.get("choices", ["Proceed"])

        if isinstance(choices, str):
            choices = [c.strip() for c in choices.split("/") if c.strip()]

        for i, choice in enumerate(choices[:3]):
            style = discord.ButtonStyle.primary if i == 0 else discord.ButtonStyle.secondary
            btn   = discord.ui.Button(label=choice, style=style, custom_id=f"node_choice_{i}")
            btn.callback = self._make_callback(choice)
            self.add_item(btn)

        flee = discord.ui.Button(label="Flee Dungeon", style=discord.ButtonStyle.danger, custom_id="node_flee")
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
            title=self.node.get("title", "Encounter"),
            description=self.node.get("description", self.node.get("opener_text", "")),
            color=EMBED_COLOR_COMBAT,
        )
        embed.add_field(name="Dungeon",  value=dungeon.get("name", "Unknown"),                      inline=True)
        embed.add_field(name="Progress", value=f"{self.run.nodes_completed + 1} / {total}",          inline=True)
        embed.add_field(name="Strikes",  value=f"{'X' * self.run.strikes}{'O' * (MAX_STRIKES - self.run.strikes)}", inline=True)
        embed.add_field(name="Shop XP",  value=f"{self.player.xp or 0} / {next_threshold} (Lv {self.player.shop_level or 1})", inline=True)
        embed.set_footer(text="Choose your action.")
        return embed

    async def _handle_choice(self, interaction: discord.Interaction, choice: str):
        node_type = self.node.get("type", "").lower()

        # Combat nodes route to CombatChoiceView
        if node_type == "combat":
            view = CombatChoiceView(self.session, self.player, self.run, self.node)
            await interaction.response.edit_message(embed=view.build_embed(), view=view)
            return

        outcome = resolve_node(self.run, self.node, choice, self.player)

        if outcome["strike"]:
            self.run.strikes += 1

        win_type  = WIN_SOCIAL if node_type in {"social", "npc_encounter"} and outcome["success"] else None
        node_xp   = get_node_xp(self.node, outcome["success"])

        loot_line = ""
        if outcome["loot_item"]:
            add_loot_to_run(self.session, self.player, self.run, outcome["loot_item"])
            loot_line = f"\n\nYou found: **{ITEMS_BY_ID.get(outcome['loot_item'], {}).get('name', outcome['loot_item'])}**"

        self.run.nodes_completed += 1
        await award_xp_and_wins(self.session, self.player, self.node, outcome["success"], win_type, interaction)
        self.session.commit()

        # Death save if too many strikes
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
        result_embed   = discord.Embed(
            title="Outcome",
            description=outcome["message"] + loot_line,
            color=EMBED_COLOR_SUCCESS if outcome["success"] else EMBED_COLOR_COMBAT,
        )
        result_embed.add_field(
            name="Strikes",
            value=f"{'X' * self.run.strikes}{'O' * (MAX_STRIKES - self.run.strikes)}",
            inline=True,
        )
        if node_xp > 0:
            result_embed.add_field(
                name="Shop XP",
                value=f"+{node_xp} XP  |  {self.player.xp} / {next_threshold} (Lv {self.player.shop_level})",
                inline=True,
            )
        if outcome.get("stat_boosted") and outcome.get("stat_name"):
            stat_val = getattr(self.player, outcome["stat_name"], None) or 1
            result_embed.add_field(
                name="Stat Bonus",
                value=f"{outcome['stat_name'].capitalize()} {stat_val}/10 contributed.",
                inline=True,
            )
        result_embed.set_footer(text="Press Continue to face the next encounter.")

        self.clear_items()
        cont = discord.ui.Button(label="Continue →", style=discord.ButtonStyle.success, custom_id="continue")
        flee = discord.ui.Button(label="Flee Dungeon", style=discord.ButtonStyle.danger,    custom_id="flee")

        async def cont_cb(i):
            nv = NodeView(self.session, self.player, self.run, next_node)
            await i.response.edit_message(embed=nv.build_node_embed(), view=nv)

        async def flee_cb(i):
            loot_names = [ITEMS_BY_ID.get(x, {}).get("name", x) for x in json.loads(self.run.loot_this_run)]
            complete_run(self.session, self.player, self.run, "fled")
            e = discord.Embed(title="You Fled!", description="You escaped with your life.", color=EMBED_COLOR_FLEE)
            e.add_field(name="Items Kept", value=", ".join(loot_names) if loot_names else "None", inline=False)
            self.clear_items()
            await i.response.edit_message(embed=e, view=self)
            self.session.close()

        cont.callback = cont_cb
        flee.callback = flee_cb
        self.add_item(cont)
        self.add_item(flee)
        await interaction.response.edit_message(embed=result_embed, view=self)

    async def _end_run(self, interaction, outcome, loot_line, result: str):
        loot_names = [ITEMS_BY_ID.get(i, {}).get("name", i) for i in json.loads(self.run.loot_this_run)]

        if result == "died":
            await handle_player_death(self.session, self.player, self.run, interaction, self)
            return

        complete_run(self.session, self.player, self.run, result)
        titles = {"completed": "Dungeon Complete!", "fled": "You Fled!"}
        colors = {"completed": EMBED_COLOR_SUCCESS, "fled": EMBED_COLOR_FLEE}
        descs  = {
            "completed": (outcome["message"] if outcome else "") + loot_line + "\n\nYou emerge victorious.",
            "fled":      "You escaped with your life.",
        }
        embed = discord.Embed(title=titles[result], description=descs[result], color=colors[result])
        embed.add_field(name="Items Recovered", value=", ".join(loot_names) if loot_names else "None", inline=False)
        embed.set_footer(text="Your loot has been added to your bank. Come back tomorrow.")
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)
        self.session.close()

    async def flee_dungeon(self, interaction: discord.Interaction):
        loot_names = [ITEMS_BY_ID.get(i, {}).get("name", i) for i in json.loads(self.run.loot_this_run)]
        complete_run(self.session, self.player, self.run, "fled")
        embed = discord.Embed(title="You Fled!", description="You escaped with your life.", color=EMBED_COLOR_FLEE)
        embed.add_field(name="Items Kept", value=", ".join(loot_names) if loot_names else "None", inline=False)
        embed.set_footer(text="Your loot has been added to your bank. Come back tomorrow.")
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)
        self.session.close()


# ---------------------------------------------------------------------------
# ExploreCog
# ---------------------------------------------------------------------------

class ExploreCog(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="explore", description="Explore the dungeon — face the next encounter.")
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

            node_type = node.get("type", "").lower()

            # Combat nodes go straight to combat choice view
            if node_type == "combat":
                view = CombatChoiceView(session, player, run, node)
                await interaction.response.send_message(embed=view.build_embed(), view=view)
            else:
                view = NodeView(session, player, run, node)
                await interaction.response.send_message(embed=view.build_node_embed(), view=view)

        except Exception as e:
            session.close(); raise e


async def setup(bot):
    await bot.add_cog(ExploreCog(bot))
