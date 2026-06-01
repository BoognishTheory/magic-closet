"""
cogs/shop.py
FT-01: Customer pool locked on first /openshop call per cycle.
FT-03: Sale outcome tier displayed per customer before next customer loads.
XP:    Phase-normalized shop XP awarded at close. Huge Profit bonus applied.
       Level-up check via shared game/level_up.py — posts Bizard message to TMC channel.
"""

import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player, BankItem, SkillPoints
from game.access import has_access, deny_access
from game.cycle_manager import can_shop
from game.level_up import apply_xp_and_check_levelup, post_levelup_message
from cogs.startshop import check_shop_channel
from config import SHOP_XP_MAX, HUGE_PROFIT_BONUS, HUGE_PROFIT_BONUS_CAP, SHOP_LEVEL_THRESHOLDS
from datetime import datetime
import json
import random

with open("data/items.json", "r") as f:
    ITEMS_DATA = json.load(f)["items"]
ITEMS_BY_ID = {item["id"]: item for item in ITEMS_DATA}

with open("data/customers.json", "r") as f:
    CUSTOMERS_DATA = json.load(f)["customers"]

RARITY_MULTIPLIERS = {
    "common":   1.0,
    "uncommon": 1.5,
    "rare":     2.5,
    "epic":     4.0,
}

STAGE_LABELS = [
    "Greeting",
    "Item Presentation",
    "Price Anchoring",
    "Customer Objection",
    "Counteroffer",
    "Closing Pitch",
    "Final Decision",
]

MAX_SCORE_PER_CUSTOMER = 14


# ---------------------------------------------------------------------------
# Sale outcome tiers
# ---------------------------------------------------------------------------

def get_outcome_tier(score: int) -> tuple[str, str, int]:
    if score >= 13:
        return "Huge Profit",    "🏆", 0xf1c40f
    elif score >= 10:
        return "Medium Profit",  "💰", 0x2ecc71
    elif score >= 7:
        return "Small Profit",   "✅", 0x27ae60
    elif score >= 5:
        return "Broken Even",    "➖", 0x95a5a6
    elif score >= 3:
        return "Sold at a Loss", "📉", 0xe67e22
    else:
        return "Failed Sale",    "❌", 0xe74c3c


# ---------------------------------------------------------------------------
# XP calculation
# ---------------------------------------------------------------------------

def calculate_shop_xp(total_score: int, customers_served: int, huge_profit_count: int) -> int:
    """
    Phase-normalized shop XP.
    One customer or four — same scale, same ceiling.
    """
    if customers_served == 0:
        return 0
    max_possible    = MAX_SCORE_PER_CUSTOMER * customers_served
    performance     = total_score / max_possible
    base_xp         = round(SHOP_XP_MAX * performance)
    bonus_xp        = min(huge_profit_count * HUGE_PROFIT_BONUS, HUGE_PROFIT_BONUS_CAP)
    return base_xp + bonus_xp


# ---------------------------------------------------------------------------
# FT-01 — Customer pool
# ---------------------------------------------------------------------------

def _generate_customer_pool(shelf_items: list) -> list:
    pool = []
    for item in shelf_items:
        customer = pick_customer_for_item(item.rarity)
        pool.append({
            "item_id":       item.item_id,
            "customer_name": customer["name"],
            "customer_data": customer,
        })
    return pool

def _lock_customer_pool(player, pool, session):
    player.daily_customers = json.dumps(pool)
    session.commit()

def _load_customer_pool(player):
    if not player.daily_customers:
        return None
    return json.loads(player.daily_customers)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pick_customer_for_item(item_rarity: str) -> dict:
    matches = [c for c in CUSTOMERS_DATA if c["tier"] == item_rarity]
    return random.choice(matches if matches else CUSTOMERS_DATA)

from cogs.hotmarket import get_hot_market_multiplier

def calculate_sale_price(item: dict, score: int) -> int:
    base       = item["sell_value"]
    multiplier = RARITY_MULTIPLIERS.get(item["rarity"], 1.0)
    bonus      = 1.0 + (score * 0.10)
    hot        = get_hot_market_multiplier(item["id"])
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

        f"They push back - says it's too expensive. How do you handle it?\n\n"
        f"**A)** Emphasize the value, hold your price\n"
        f"**B)** Offer a small discount to keep momentum\n"
        f"**C)** Throw in a freebie to sweeten the deal",

        f"{customer['name']} makes a low counteroffer. What do you do?\n\n"
        f"**A)** Decline and restate your value\n"
        f"**B)** Meet them halfway\n"
        f"**C)** Accept - a sale is a sale",

        f"One last push before they decide. Your closing move?\n\n"
        f"**A)** Create urgency - another buyer is interested\n"
        f"**B)** Offer to bundle with something small\n"
        f"**C)** Stay silent and let the item speak for itself",

        f"{customer['name']} weighs their options. Final call?\n\n"
        f"**A)** Press for the close directly\n"
        f"**B)** Give them space to decide\n"
        f"**C)** Offer a payment plan",
    ]
    return stages[stage]


# ---------------------------------------------------------------------------
# ShopView
# ---------------------------------------------------------------------------

class ShopView(discord.ui.View):
    def __init__(self, session, player, shelf_items, customer_pool: list):
        super().__init__(timeout=120)
        self.session           = session
        self.player            = player
        self.shelf_items       = shelf_items
        self.customer_pool     = customer_pool
        self.current_item_index = 0
        self.current_stage     = 0
        self.stage_score       = 0
        self.total_coin_earned = 0
        self.current_customer  = customer_pool[0]["customer_data"]
        self.cumulative_score  = 0
        self.customers_served  = 0
        self.huge_profit_count = 0
        self._set_stage_buttons()

    def _set_stage_buttons(self):
        self.clear_items()
        for label, cid, cb in [
            ("Option A", "choice_a", self.choice_a),
            ("Option B", "choice_b", self.choice_b),
            ("Option C", "choice_c", self.choice_c),
        ]:
            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary if cid == "choice_a" else discord.ButtonStyle.secondary,
                custom_id=cid,
            )
            btn.callback = cb
            self.add_item(btn)

    def _set_next_customer_button(self):
        self.clear_items()
        btn = discord.ui.Button(label="Next Customer ->", style=discord.ButtonStyle.success, custom_id="next_customer")
        btn.callback = self.next_customer
        self.add_item(btn)

    def _set_close_button(self):
        self.clear_items()
        btn = discord.ui.Button(label="Close Shop", style=discord.ButtonStyle.secondary, custom_id="close_shop")
        btn.callback = self._close_shop_btn
        self.add_item(btn)

    def build_stage_embed(self) -> discord.Embed:
        item     = self.shelf_items[self.current_item_index]
        item_def = ITEMS_BY_ID.get(item.item_id, {})
        embed = discord.Embed(
            title=f"The Magic Closet - {STAGE_LABELS[self.current_stage]}",
            description=get_stage_description(self.current_stage, item_def, self.current_customer),
            color=0x9b59b6,
        )
        embed.add_field(name="Item",     value=item_def.get("name", "Unknown"),    inline=True)
        embed.add_field(name="Customer", value=self.current_customer["name"],      inline=True)
        embed.add_field(name="Stage",    value=f"{self.current_stage + 1} / 7",    inline=True)
        embed.set_footer(text="Choose your approach wisely.")
        return embed

    async def _handle_choice(self, interaction: discord.Interaction, choice: str):
        self.stage_score   += score_choice(self.current_stage, choice)
        self.current_stage += 1
        if self.current_stage >= 7:
            await self._resolve_sale(interaction)
        else:
            await interaction.response.edit_message(embed=self.build_stage_embed(), view=self)

    async def _resolve_sale(self, interaction: discord.Interaction):
        item     = self.shelf_items[self.current_item_index]
        item_def = ITEMS_BY_ID.get(item.item_id, {})
        coin_earned = calculate_sale_price(item_def, self.stage_score)
        tier_label, tier_emoji, tier_color = get_outcome_tier(self.stage_score)

        # Accumulate XP data
        self.cumulative_score  += self.stage_score
        self.customers_served  += 1
        if tier_label == "Huge Profit":
            self.huge_profit_count += 1

        self.player.coin       += coin_earned
        self.total_coin_earned += coin_earned
        item.on_floor           = False
        self.session.commit()

        self.current_item_index += 1
        self.current_stage       = 0
        self.stage_score         = 0

        more_customers = self.current_item_index < len(self.shelf_items)

        embed = discord.Embed(
            title=f"{tier_emoji} {tier_label}",
            description=(
                f"**{item_def.get('name', 'Item')}** sold to **{self.current_customer['name']}**.\n\n"
                f"You earned **{coin_earned} coin**."
            ),
            color=tier_color,
        )
        embed.add_field(name="Total Earned Today", value=f"{self.total_coin_earned} coin", inline=True)
        embed.add_field(name="Balance",            value=f"{self.player.coin} coin",        inline=True)

        if more_customers:
            self.current_customer = self.customer_pool[self.current_item_index]["customer_data"]
            embed.set_footer(text="Next customer is already waiting.")
            self._set_next_customer_button()
        else:
            embed.set_footer(text="That was the last customer. Closing up.")
            self._set_close_button()

        await interaction.response.edit_message(embed=embed, view=self)

    async def next_customer(self, interaction: discord.Interaction):
        self._set_stage_buttons()
        await interaction.response.edit_message(content=None, embed=self.build_stage_embed(), view=self)

    async def _close_shop_btn(self, interaction: discord.Interaction):
        await self._close_shop(interaction)

    async def _close_shop(self, interaction: discord.Interaction):
        self.player.shop_complete = True
        self.player.last_active   = datetime.utcnow()

        # Load skill points row
        sp = self.session.query(SkillPoints).filter_by(player_id=self.player.id).first()

        # Calculate and award XP
        xp_earned  = calculate_shop_xp(self.cumulative_score, self.customers_served, self.huge_profit_count)
        levelled_up, new_level = apply_xp_and_check_levelup(self.player, sp, xp_earned)
        self.session.commit()

        # Post level-up message to TMC channel if levelled up
        if levelled_up:
            await post_levelup_message(
                interaction.guild,
                self.player.shop_name,
                interaction.user.display_name,
                new_level,
                sp,
            )

        next_threshold = SHOP_LEVEL_THRESHOLDS.get(self.player.shop_level, 999)
        embed = discord.Embed(
            title="The Magic Closet - Closed for the Day",
            description="The last customer has left. You flip the sign to closed.",
            color=0xe74c3c,
        )
        embed.add_field(name="Total Earned Today", value=f"{self.total_coin_earned} coin",  inline=True)
        embed.add_field(name="Current Balance",    value=f"{self.player.coin} coin",         inline=True)
        embed.add_field(
            name="Shop XP",
            value=f"+{xp_earned} XP  |  {self.player.xp} / {next_threshold} XP  (Level {self.player.shop_level})",
            inline=False,
        )
        if levelled_up:
            embed.add_field(
                name="Level Up!",
                value=f"Bizard has sent you a message. Check your channel.",
                inline=False,
            )
        embed.set_footer(text="Head into the dungeon with /dungeonprep")
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)
        self.session.close()

    async def choice_a(self, interaction): await self._handle_choice(interaction, "a")
    async def choice_b(self, interaction): await self._handle_choice(interaction, "b")
    async def choice_c(self, interaction): await self._handle_choice(interaction, "c")


# ---------------------------------------------------------------------------
# ShopCog
# ---------------------------------------------------------------------------

class ShopCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="openshop", description="Open the Magic Closet and sell today's stock.")
    async def openshop(self, interaction: discord.Interaction):
        if not has_access(interaction):
            await deny_access(interaction)
            return
        if not await check_shop_channel(interaction):
            return

        session = get_session()
        try:
            player = session.query(Player).filter_by(discord_id=str(interaction.user.id)).first()
            if not player:
                await interaction.response.send_message("You haven't stocked your shelves yet. Run /prepstore first.", ephemeral=True)
                session.close(); return

            if not can_shop(player):
                msg = "The shelves are bare. Stock them first with /prepstore." if not player.prep_complete else "The Magic Closet has already closed for the day. Come back tomorrow."
                await interaction.response.send_message(msg, ephemeral=True)
                session.close(); return

            shelf = session.query(BankItem).filter_by(player_id=player.id, on_floor=True).all()
            if not shelf:
                await interaction.response.send_message("Nothing on the shelves. Run /prepstore to stock up.", ephemeral=True)
                session.close(); return

            customer_pool = _load_customer_pool(player)
            if customer_pool is None:
                customer_pool = _generate_customer_pool(shelf)
                _lock_customer_pool(player, customer_pool, session)
            else:
                floor_ids     = {item.item_id for item in shelf}
                customer_pool = [c for c in customer_pool if c["item_id"] in floor_ids]
                if not customer_pool:
                    await interaction.response.send_message("All items have already been sold today.", ephemeral=True)
                    session.close(); return

            view  = ShopView(session, player, shelf, customer_pool)
            await interaction.response.send_message(embed=view.build_stage_embed(), view=view)

        except Exception as e:
            session.close(); raise e


async def setup(bot):
    await bot.add_cog(ShopCog(bot))
