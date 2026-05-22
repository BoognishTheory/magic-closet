import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player, ActiveRun, BankItem
from game.access import has_access, deny_access
from game.cycle_manager import can_dungeon
from datetime import datetime
import json
import random

with open("data/dungeons.json", "r") as f:
    DUNGEONS_DATA = json.load(f)["dungeons"]
DUNGEONS_BY_ID = {d["id"]: d for d in DUNGEONS_DATA}

with open("data/weapons.json", "r") as f:
    WEAPONS_DATA = json.load(f)["weapons"]
WEAPONS_BY_ID = {w["id"]: w for w in WEAPONS_DATA}

with open("data/spells.json", "r") as f:
    SPELLS_DATA = json.load(f)["spells"]
SPELLS_BY_ID = {s["id"]: s for s in SPELLS_DATA}

with open("data/node_templates.json", "r") as f:
    NODES_DATA = json.load(f)["nodes"]

with open("data/items.json", "r") as f:
    ITEMS_DATA = json.load(f)["items"]
ITEMS_BY_ID = {i["id"]: i for i in ITEMS_DATA}

with open("data/loot_tables.json", "r") as f:
    LOOT_TABLES = json.load(f)


def get_player_weapons(session, player):
    weapon_ids = set(WEAPONS_BY_ID.keys())
    bank_items = session.query(BankItem).filter_by(player_id=player.id).all()
    return [b for b in bank_items if b.item_id in weapon_ids]


def get_player_spells(session, player):
    spell_ids = set(SPELLS_BY_ID.keys())
    bank_items = session.query(BankItem).filter_by(player_id=player.id).all()
    return [b for b in bank_items if b.item_id in spell_ids]


def build_node_sequence(dungeon):
    all_node_ids = [n["id"] for n in NODES_DATA]
    count = dungeon["node_count"]
    return random.choices(all_node_ids, k=count)


class WeaponSelectView(discord.ui.View):
    def __init__(self, parent, options):
        super().__init__(timeout=60)
        self.parent = parent
        select = discord.ui.Select(placeholder="Choose a weapon", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        self.parent.selected_weapon = self.children[0].values[0]
        self.parent._add_buttons()
        await interaction.response.edit_message(
            content=None, embed=self.parent.build_embed(), view=self.parent
        )


class SpellSelectView(discord.ui.View):
    def __init__(self, parent, options):
        super().__init__(timeout=60)
        self.parent = parent
        select = discord.ui.Select(placeholder="Choose a spell", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        self.parent.selected_spell = self.children[0].values[0]
        self.parent._add_buttons()
        await interaction.response.edit_message(
            content=None, embed=self.parent.build_embed(), view=self.parent
        )


class LoadoutView(discord.ui.View):
    def __init__(self, session, player, dungeon):
        super().__init__(timeout=120)
        self.session = session
        self.player = player
        self.dungeon = dungeon
        self.selected_weapon = None
        self.selected_spell = None
        self.selected_item = None
        self._add_buttons()

    def _add_buttons(self):
        self.clear_items()

        weapon_btn = discord.ui.Button(
            label=f"Weapon: {self.selected_weapon or 'None'}",
            style=discord.ButtonStyle.secondary,
            custom_id="select_weapon"
        )
        weapon_btn.callback = self.select_weapon
        self.add_item(weapon_btn)

        spell_btn = discord.ui.Button(
            label=f"Spell: {self.selected_spell or 'None'}",
            style=discord.ButtonStyle.secondary,
            custom_id="select_spell"
        )
        spell_btn.callback = self.select_spell
        self.add_item(spell_btn)

        confirm_btn = discord.ui.Button(
            label="Enter Dungeon",
            style=discord.ButtonStyle.success,
            custom_id="confirm_loadout"
        )
        confirm_btn.callback = self.confirm_loadout
        self.add_item(confirm_btn)

    def build_embed(self):
        dungeon = self.dungeon
        embed = discord.Embed(
            title=f"Loadout — {dungeon['name']}",
            description=dungeon["description"],
            color=0xe74c3c
        )
        embed.add_field(name="Tier", value=str(dungeon["tier"]), inline=True)
        embed.add_field(name="Nodes", value=str(dungeon["node_count"]), inline=True)
        embed.add_field(name="Entry Cost", value=f"{dungeon['entry_cost']} coin", inline=True)
        embed.add_field(name="Weapon Slot", value=self.selected_weapon or "Empty", inline=True)
        embed.add_field(name="Spell Slot", value=self.selected_spell or "Empty", inline=True)
        embed.add_field(name="Your Coin", value=f"{self.player.coin} coin", inline=True)
        embed.set_footer(text="Select your loadout then enter the dungeon.")
        return embed

    async def select_weapon(self, interaction: discord.Interaction):
        weapons = get_player_weapons(self.session, self.player)
        if not weapons:
            self.selected_weapon = "iron_sword"
            self._add_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
            return
        options = [
            discord.SelectOption(label=WEAPONS_BY_ID[w.item_id]["name"], value=w.item_id)
            for w in weapons if w.item_id in WEAPONS_BY_ID
        ]
        view = WeaponSelectView(self, options)
        await interaction.response.edit_message(content="Pick your weapon:", embed=None, view=view)

    async def select_spell(self, interaction: discord.Interaction):
        spells = get_player_spells(self.session, self.player)
        if not spells:
            self.selected_spell = "fireball"
            self._add_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
            return
        options = [
            discord.SelectOption(label=SPELLS_BY_ID[s.item_id]["name"], value=s.item_id)
            for s in spells if s.item_id in SPELLS_BY_ID
        ]
        view = SpellSelectView(self, options)
        await interaction.response.edit_message(content="Pick your spell:", embed=None, view=view)

    async def confirm_loadout(self, interaction: discord.Interaction):
        dungeon = self.dungeon

        if not self.selected_weapon:
            self.selected_weapon = "iron_sword"
        if not self.selected_spell:
            self.selected_spell = "fireball"

        self.player.coin -= dungeon["entry_cost"]

        node_sequence = build_node_sequence(dungeon)

        run = ActiveRun(
            player_id=self.player.id,
            dungeon_id=dungeon["id"],
            strikes=0,
            nodes_completed=0,
            node_sequence=json.dumps(node_sequence),
            loot_this_run=json.dumps([]),
            weapon_slot=self.selected_weapon,
            spell_slot=self.selected_spell,
            item_slot=self.selected_item,
            started_at=datetime.utcnow()
        )
        self.session.add(run)
        self.session.commit()

        embed = discord.Embed(
            title=f"Entering {dungeon['name']}...",
            description=f"You descend into the darkness. There is no turning back.\n\nRun /explore to begin.",
            color=0xe74c3c
        )
        embed.add_field(name="Weapon", value=self.selected_weapon, inline=True)
        embed.add_field(name="Spell", value=self.selected_spell, inline=True)
        embed.add_field(name="Nodes Ahead", value=str(dungeon["node_count"]), inline=True)
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)
        self.session.close()


class DungeonSelectView(discord.ui.View):
    def __init__(self, session, player):
        super().__init__(timeout=120)
        self.session = session
        self.player = player
        self._add_dungeon_buttons()

    def _add_dungeon_buttons(self):
        for dungeon in DUNGEONS_DATA:
            btn = discord.ui.Button(
                label=f"{dungeon['name']} (Tier {dungeon['tier']}) - {dungeon['entry_cost']} coin",
                style=discord.ButtonStyle.primary,
                custom_id=f"dungeon_{dungeon['id']}"
            )
            btn.callback = self._make_callback(dungeon)
            self.add_item(btn)

    def _make_callback(self, dungeon):
        async def callback(interaction: discord.Interaction):
            if self.player.coin < dungeon["entry_cost"]:
                await interaction.response.edit_message(
                    content=f"Not enough coin. You need {dungeon['entry_cost']} coin to enter {dungeon['name']}.",
                    embed=None,
                    view=None
                )
                return
            view = LoadoutView(self.session, self.player, dungeon)
            embed = view.build_embed()
            await interaction.response.edit_message(embed=embed, view=view)
        return callback


class DungeonCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="dungeonprep", description="Choose your dungeon and loadout.")
    async def dungeonprep(self, interaction: discord.Interaction):
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

            if not can_dungeon(player):
                if not player.shop_complete:
                    await interaction.response.send_message(
                        "You need to run the shop first. Use /openshop.",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "You have already completed the dungeon today. Come back tomorrow.",
                        ephemeral=True
                    )
                return

            existing_run = session.query(ActiveRun).filter_by(
                player_id=player.id
            ).first()
            if existing_run:
                await interaction.response.send_message(
                    "You are already in a dungeon run. Use /explore to continue.",
                    ephemeral=True
                )
                return

            embed = discord.Embed(
                title="Choose Your Dungeon",
                description="Each dungeon costs coin to enter. Higher tiers mean better loot and more risk.",
                color=0xe74c3c
            )
            for dungeon in DUNGEONS_DATA:
                embed.add_field(
                    name=f"{dungeon['name']} - Tier {dungeon['tier']}",
                    value=f"{dungeon['description']}\nEntry: {dungeon['entry_cost']} coin",
                    inline=False
                )
            embed.add_field(name="Your Coin", value=f"{player.coin} coin", inline=False)

            view = DungeonSelectView(session, player)
            await interaction.response.send_message(embed=embed, view=view)

        except Exception as e:
            session.close()
            raise e


async def setup(bot):
    await bot.add_cog(DungeonCog(bot))