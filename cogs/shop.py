import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player, BankItem
from game.access import has_access, deny_access
from game.cycle_manager import can_shop
from datetime import datetime
import json
import random

with open("data/items.json", "r") as f:
    ITEMS_DATA = json.load(f)["items"]
ITEMS_BY_ID = {item["id"]: item for item in ITEMS_DATA}

with open("data/customers.json", "r") as f:
    CUSTOMERS_DATA = json.load(f)["customers"]

RARITY_MULTIPLIERS = {
    "common": 1.0,
    "uncommon": 1.5,
    "rare": 2.5,
    "epic": 4.0
}

STAGE_LABELS = [
    "Greeting",
    "Item Presentation",
    "Price Anchoring",
    "Customer Objection",
    "Counteroffer",
    "Closing Pitch",
    "Final Decision"
]


def pick_customer_for_item(item_rarity: str) -> dict:
    matches = [c for c in CUSTOMERS_DATA if c["tier"] == item_rarity]
    if not matches:
        matches = CUSTOMERS_DATA
    return random.choice(matches)

from cogs.hotmarket import get_hot_market_multiplier

def calculate_sale_price(item: dict, score: int) -> int:
    base = item["sell_value"]
    multiplier = RARITY_MULTIPLIERS.get(item["rarity"], 1.0)
    bonus = 1.0 + (score * 0.10)
    hot = get_hot_market_multiplier(item["id"])
    return int(base * multiplier * bonus * hot)


def score_choice(stage: int, choice: str) -> int:
    matrix = [
        {"a": 2, "b": 1, "c": 0},
        {"a": 2, "b": 2, "c": 0},
        {"a": 2, "b": 1, "c": 1},
        {"a": 2, "b": 1, "c": 0},
        {"a": 2, "b": 1, "c": 0},
        {"a": 1, "b": 2, "c": 1},
        {"a": 2, "b": 1, "c": 0},
    ]
    return matrix[stage].get(choice, 0)


def get_stage_description(stage: int, item_def: dict, customer: dict) -> str:
    stages = [
        f"{customer['name']} walks in and eyes your {item_def.get('name', 'item')}. How do you greet them?\n\n"
        f"**A)** Warm welcome, offer to answer questions\n"
        f"**B)** Nod and let them browse\n"
        f"**C)** Immediately pitch the item",

        f"Time to show off the goods. How do you present the {item_def.get('name', 'item')}?\n\n"
        f"**A)** Highlight its rarity and origin\n"
        f"**B)** Let them pick it up and feel it\n"
        f"**C)** Drop the price first to hook them",

        f"{customer['name']} asks about the price. How do you anchor?\n\n"
        f"**A)** Name a high price and leave room to negotiate\n"
        f"**B)** Give them the fair market value straight\n"
        f"**C)** Ask what they think it's worth first",

        f"They push back — says it's too expensive. How do you handle it?\n\n"
        f"**A)** Emphasize the value, hold your price\n"
        f"**B)** Offer a small discount to keep momentum\n"
        f"**C)** Throw in a freebie to sweeten the deal",

        f"{customer['name']} makes a low counteroffer. What do you do?\n\n"
        f"**A)** Decline and restate your value\n"
        f"**B)** Meet them halfway\n"
        f"**C)** Accept — a sale is a sale",

        f"One last push before they decide. Your closing move?\n\n"
        f"**A)** Create urgency — another buyer is interested\n"
        f"**B)** Offer to bundle with something small\n"
        f"**C)** Stay silent and let the item speak for itself",

        f"{customer['name']} weighs their options. Final call?\n\n"
        f"**A)** Press for the close directly\n"
        f"**B)** Give them space to decide\n"
        f"**C)** Offer a payment plan"
    ]
    return stages[stage]


class ShopView(discord.ui.View):
    def __init__(self, session, player, shelf_items):
        super().__init__(timeout=120)
        self.session = session
        self.player = player
        self.shelf_items = shelf_items
        self.current_item_index = 0
        self.current_stage = 0
        self.stage_score = 0
        self.total_coin_earned = 0
        self.current_customer = pick_customer_for_item(shelf_items[0].rarity)
        self._set_stage_buttons()

    def _set_stage_buttons(self):
        self.clear_items()
        btn1 = discord.ui.Button(label="Option A", style=discord.ButtonStyle.primary, custom_id="choice_a")
        btn2 = discord.ui.Button(label="Option B", style=discord.ButtonStyle.secondary, custom_id="choice_b")
        btn3 = discord.ui.Button(label="Option C", style=discord.ButtonStyle.secondary, custom_id="choice_c")
        btn1.callback = self.choice_a
        btn2.callback = self.choice_b
        btn3.callback = self.choice_c
        self.add_item(btn1)
        self.add_item(btn2)
        self.add_item(btn3)

    def _set_next_customer_button(self):
        self.clear_items()
        btn = discord.ui.Button(label="Next Customer →", style=discord.ButtonStyle.success, custom_id="next_customer")
        btn.callback = self.next_customer
        self.add_item(btn)

    def build_stage_embed(self) -> discord.Embed:
        item = self.shelf_items[self.current_item_index]
        item_def = ITEMS_BY_ID.get(item.item_id, {})
        stage_label = STAGE_LABELS[self.current_stage]
        customer = self.current_customer

        embed = discord.Embed(
            title=f"🛒 The Magic Closet — {stage_label}",
            description=get_stage_description(self.current_stage, item_def, customer),
            color=0x9b59b6
        )
        embed.add_field(name="Item", value=item_def.get("name", "Unknown"), inline=True)
        embed.add_field(name="Customer", value=customer["name"], inline=True)
        embed.add_field(name="Stage", value=f"{self.current_stage + 1} / 7", inline=True)
        embed.set_footer(text="Choose your approach wisely.")
        return embed

    async def _handle_choice(self, interaction: discord.Interaction, choice: str):
        self.stage_score += score_choice(self.current_stage, choice)
        self.current_stage += 1

        if self.current_stage >= 7:
            await self._resolve_sale(interaction)
        else:
            embed = self.build_stage_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    async def _resolve_sale(self, interaction: discord.Interaction):
        item = self.shelf_items[self.current_item_index]
        item_def = ITEMS_BY_ID.get(item.item_id, {})
        coin_earned = calculate_sale_price(item_def, self.stage_score)

        self.player.coin += coin_earned
        self.total_coin_earned += coin_earned
        item.on_floor = False
        self.session.commit()

        self.current_item_index += 1
        self.current_stage = 0
        self.stage_score = 0

        if self.current_item_index < len(self.shelf_items):
            self.current_customer = pick_customer_for_item(
                self.shelf_items[self.current_item_index].rarity
            )
            embed = discord.Embed(
                title="💰 Sale Complete!",
                description=f"You earned **{coin_earned} coin** for the {item_def.get('name', 'item')}.\n\nA new customer is already eyeing your wares.",
                color=0x2ecc71
            )
            embed.add_field(name="Total Earned Today", value=f"{self.total_coin_earned} coin", inline=False)
            self._set_next_customer_button()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await self._close_shop(interaction, coin_earned)

    async def next_customer(self, interaction: discord.Interaction):
        self._set_stage_buttons()
        embed = self.build_stage_embed()
        await interaction.response.edit_message(content=None, embed=embed, view=self)

    async def _close_shop(self, interaction: discord.Interaction, last_coin_earned: int):
        self.player.shop_complete = True
        self.player.last_active = datetime.utcnow()
        self.session.commit()

        embed = discord.Embed(
            title="🔒 The Magic Closet — Closed for the Day",
            description="The last customer has left. You flip the sign to closed.",
            color=0xe74c3c
        )
        embed.add_field(name="Last Sale", value=f"{last_coin_earned} coin", inline=True)
        embed.add_field(name="Total Earned Today", value=f"{self.total_coin_earned} coin", inline=False)
        embed.add_field(name="Current Balance", value=f"{self.player.coin} coin", inline=False)
        embed.set_footer(text="Head into the dungeon with /dungeonprep")
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)
        self.session.close()

    async def choice_a(self, interaction: discord.Interaction):
        await self._handle_choice(interaction, "a")

    async def choice_b(self, interaction: discord.Interaction):
        await self._handle_choice(interaction, "b")

    async def choice_c(self, interaction: discord.Interaction):
        await self._handle_choice(interaction, "c")


class ShopCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="openshop", description="Open the Magic Closet and sell today's stock.")
    async def openshop(self, interaction: discord.Interaction):
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
                    "You haven't stocked your shelves yet. Run /prepstore first.",
                    ephemeral=True
                )
                return

            if not can_shop(player):
                if not player.prep_complete:
                    await interaction.response.send_message(
                        "The shelves are bare. Stock them first with /prepstore.",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "The Magic Closet has already closed for the day. Come back tomorrow.",
                        ephemeral=True
                    )
                return

            shelf = session.query(BankItem).filter_by(
                player_id=player.id, on_floor=True
            ).all()

            if not shelf:
                await interaction.response.send_message(
                    "Nothing on the shelves. Run /prepstore to stock up.",
                    ephemeral=True
                )
                return

            view = ShopView(session, player, shelf)
            embed = view.build_stage_embed()
            await interaction.response.send_message(embed=embed, view=view)

        except Exception as e:
            session.close()
            raise e


async def setup(bot):
    await bot.add_cog(ShopCog(bot))