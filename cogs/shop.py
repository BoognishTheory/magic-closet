"""
cogs/shop.py
FT-01: Customer pool locked on first /openshop call per cycle.
FT-03: Sale outcome tier displayed per customer before next customer loads.
XP:    Phase-normalized shop XP awarded at close.
Personalities: Demeanor-labeled choices. Scoring driven by customer archetype.
               Wildcard variance. Venter hard gate on stages 1-2.
"""

import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player, BankItem, SkillPoints
from game.access import has_access, deny_access
from game.cycle_manager import can_shop, is_chaos_stock
from game.level_up import apply_xp_and_check_levelup, post_levelup_message
from game.char_level import apply_char_win, post_char_levelup_message, WIN_SOCIAL
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
CUSTOMERS_BY_ID = {c["id"]: c for c in CUSTOMERS_DATA}

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

# Demeanor scoring values
SCORE_LOVES     = 2
SCORE_TOLERATES = 1
SCORE_HATES     = 0

# Stage option demeanor assignments
# Each stage has 3 options with demeanor labels.
# Order: [option_a_demeanor, option_b_demeanor, option_c_demeanor]
STAGE_DEMEANORS = [
    ["empathetic",   "deferential",  "enthusiastic"],  # Stage 1 — Greeting
    ["enthusiastic", "direct",       "deferential"],   # Stage 2 — Item Presentation
    ["direct",       "deferential",  "humorous"],      # Stage 3 — Price Anchoring
    ["direct",       "empathetic",   "deferential"],   # Stage 4 — Handle Objection
    ["direct",       "deferential",  "humorous"],      # Stage 5 — Counteroffer
    ["enthusiastic", "empathetic",   "direct"],        # Stage 6 — Closing Pitch
    ["direct",       "deferential",  "humorous"],      # Stage 7 — Final Decision
]

# Choice index map
CHOICE_INDEX = {"a": 0, "b": 1, "c": 2}


# ---------------------------------------------------------------------------
# Personality-driven scoring
# ---------------------------------------------------------------------------

def score_choice(stage: int, choice: str, customer: dict) -> int:
    """
    Score a choice based on the customer's personality.
    Loves = 2, Tolerates = 1, Hates = 0.
    Wildcard customers have random scoring with slight bias toward Humorous.
    Venter hard gate: stages 0-1 (1-2 in display) must be Empathetic or sale drops to 0.
    """
    choice_idx = CHOICE_INDEX.get(choice.lower(), 0)
    demeanor   = STAGE_DEMEANORS[stage][choice_idx]

    # Wildcard — random variance
    if customer.get("wildcard"):
        if demeanor == "humorous":
            return random.choices([2, 1, 0], weights=[60, 25, 15])[0]
        else:
            return random.choices([2, 1, 0], weights=[33, 34, 33])[0]

    # Venter hard gate — stages 0 and 1 must be empathetic
    if customer.get("hard_gate") and stage in customer.get("hard_gate_stages_zero", [0, 1]):
        if demeanor != customer.get("hard_gate_demeanor", "empathetic"):
            return 0  # Hard gate fired — sale is unrecoverable after this

    loves     = customer.get("loves", "direct")
    tolerates = customer.get("tolerates", "deferential")

    # Kid's Parent dual-loves handling
    if customer.get("dual_loves") and demeanor == customer.get("dual_loves_secondary"):
        return SCORE_LOVES

    if demeanor == loves:
        return SCORE_LOVES
    elif demeanor == tolerates:
        return SCORE_TOLERATES
    else:
        return SCORE_HATES


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
            "customer_id":   customer["id"],
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
    pool    = matches if matches else CUSTOMERS_DATA
    return random.choice(pool)

from cogs.hotmarket import get_hot_market_multiplier

def calculate_sale_price(item: dict, score: int) -> int:
    base       = item["sell_value"]
    multiplier = RARITY_MULTIPLIERS.get(item["rarity"], 1.0)
    bonus      = 1.0 + (score * 0.10)
    hot        = get_hot_market_multiplier(item["id"])
    return int(base * multiplier * bonus * hot)


# ---------------------------------------------------------------------------
# Stage descriptions — demeanor labels visible to player
# ---------------------------------------------------------------------------

def get_stage_description(stage: int, item_def: dict, customer: dict) -> str:
    name = item_def.get("name", "the item")
    cname = customer["name"]
    mood  = customer.get("surface_mood", "")

    # Stage 0 shows surface mood
    mood_line = f"\n\n*{mood}*" if stage == 0 and mood else ""

    stages = [
        # Stage 1 — Greeting
        f"{cname} walks in and eyes your {name}.{mood_line}\n\n"
        f"**A) [Empathetic]** Warm welcome — ask what brings them in today\n"
        f"**B) [Deferential]** Nod and give them space to look around\n"
        f"**C) [Enthusiastic]** Jump straight in — tell them this item is perfect for them",

        # Stage 2 — Item Presentation
        f"Time to show off the {name}.\n\n"
        f"**A) [Enthusiastic]** Highlight its rarity and the story behind it\n"
        f"**B) [Direct]** State what it does and why it works\n"
        f"**C) [Deferential]** Let them pick it up and draw their own conclusions",

        # Stage 3 — Price Anchoring
        f"{cname} asks about the price.\n\n"
        f"**A) [Direct]** Name the price clearly and stand behind it\n"
        f"**B) [Deferential]** Ask what they were hoping to spend\n"
        f"**C) [Humorous]** Joke that it's worth twice as much but you like them",

        # Stage 4 — Handle Objection
        f"They push back — says it's more than they wanted to spend.\n\n"
        f"**A) [Direct]** Hold the price, explain the value plainly\n"
        f"**B) [Empathetic]** Acknowledge the concern and offer a small gesture\n"
        f"**C) [Deferential]** Tell them there's no pressure — the item will still be here",

        # Stage 5 — Counteroffer
        f"{cname} makes a lower offer.\n\n"
        f"**A) [Direct]** Decline and restate your original value\n"
        f"**B) [Deferential]** Meet them somewhere in the middle\n"
        f"**C) [Humorous]** Laugh warmly and say that's almost what you paid for it",

        # Stage 6 — Closing Pitch
        f"One last push before they decide.\n\n"
        f"**A) [Enthusiastic]** Create a sense of urgency — someone else asked about this yesterday\n"
        f"**B) [Empathetic]** Tell them you think this is genuinely the right choice for them\n"
        f"**C) [Direct]** Ask plainly if they want it",

        # Stage 7 — Final Decision
        f"{cname} weighs it up.\n\n"
        f"**A) [Direct]** Press for the close — ask for the decision\n"
        f"**B) [Deferential]** Step back and give them the moment\n"
        f"**C) [Humorous]** Make a light comment that takes the pressure off",
    ]
    return stages[stage]


# ---------------------------------------------------------------------------
# ShopView
# ---------------------------------------------------------------------------

class ShopView(discord.ui.View):
    def __init__(self, session, player, shelf_items, customer_pool: list, chaos: bool = False):
        super().__init__(timeout=120)
        self.session              = session
        self.player               = player
        self.shelf_items          = shelf_items
        self.customer_pool        = customer_pool
        self.current_item_index   = 0
        self.current_stage        = 0
        self.stage_score          = 0
        self.total_coin_earned    = 0
        self.current_customer     = customer_pool[0]["customer_data"]
        self.cumulative_score     = 0
        self.customers_served     = 0
        self.huge_profit_count    = 0
        self.social_wins_earned   = 0
        # Track Venter hard gate state
        self.venter_gate_broken   = False
        self.chaos_stock          = chaos
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
        btn = discord.ui.Button(
            label="Next Customer ->",
            style=discord.ButtonStyle.success,
            custom_id="next_customer"
        )
        btn.callback = self.next_customer
        self.add_item(btn)

    def _set_close_button(self):
        self.clear_items()
        btn = discord.ui.Button(
            label="Close Shop",
            style=discord.ButtonStyle.secondary,
            custom_id="close_shop"
        )
        btn.callback = self._close_shop_btn
        self.add_item(btn)

    def build_stage_embed(self) -> discord.Embed:
        item     = self.shelf_items[self.current_item_index]
        item_def = ITEMS_BY_ID.get(item.item_id, {})
        customer = self.current_customer

        embed = discord.Embed(
            title=f"The Magic Closet — {STAGE_LABELS[self.current_stage]}",
            description=get_stage_description(self.current_stage, item_def, customer),
            color=0x9b59b6,
        )
        embed.add_field(name="Item",     value=item_def.get("name", "Unknown"),    inline=True)
        embed.add_field(name="Customer", value=customer["name"],                    inline=True)
        embed.add_field(name="Stage",    value=f"{self.current_stage + 1} / 7",    inline=True)
        chaos_line = (
            

"*Bizard overslept. The portal stocked whatever was closest to hand. "
            "Keen Eye has no power here.*"
            if self.chaos_stock else ""
        )
        if chaos_line and self.current_stage == 0:
            embed.description = (embed.description or "") + chaos_line
        embed.set_footer(text="Choose your approach. [Brackets] show your demeanor.")
        return embed

    async def _handle_choice(self, interaction: discord.Interaction, choice: str):
        customer = self.current_customer

        # Check Venter hard gate
        if (
            customer.get("hard_gate")
            and self.current_stage in [0, 1]
        ):
            choice_idx = CHOICE_INDEX.get(choice.lower(), 0)
            demeanor   = STAGE_DEMEANORS[self.current_stage][choice_idx]
            if demeanor != customer.get("hard_gate_demeanor", "empathetic"):
                self.venter_gate_broken = True

        points = score_choice(self.current_stage, choice, customer)

        # If Venter gate was broken, this stage scores 0 regardless
        if self.venter_gate_broken and self.current_stage in [0, 1]:
            points = 0

        self.stage_score   += points
        self.current_stage += 1

        if self.current_stage >= 7:
            await self._resolve_sale(interaction)
        else:
            await interaction.response.edit_message(
                embed=self.build_stage_embed(), view=self
            )

    async def _resolve_sale(self, interaction: discord.Interaction):
        item     = self.shelf_items[self.current_item_index]
        item_def = ITEMS_BY_ID.get(item.item_id, {})
        coin_earned = calculate_sale_price(item_def, self.stage_score)
        tier_label, tier_emoji, tier_color = get_outcome_tier(self.stage_score)

        # Accumulate XP and win tracking
        self.cumulative_score  += self.stage_score
        self.customers_served  += 1
        if tier_label == "Huge Profit":
            self.huge_profit_count += 1
        if self.stage_score >= 7:  # Small Profit or better = social win
            self.social_wins_earned += 1

        self.player.coin       += coin_earned
        self.total_coin_earned += coin_earned
        item.on_floor           = False
        self.session.commit()

        self.current_item_index += 1
        self.current_stage       = 0
        self.stage_score         = 0
        self.venter_gate_broken  = False

        more_customers = self.current_item_index < len(self.shelf_items)

        embed = discord.Embed(
            title=f"{tier_emoji} {tier_label}",
            description=(
                f"**{item_def.get('name', 'Item')}** sold to "
                f"**{self.current_customer['name']}**.\n\n"
                f"You earned **{coin_earned} coin**."
            ),
            color=tier_color,
        )
        embed.add_field(
            name="Total Earned Today",
            value=f"{self.total_coin_earned} coin",
            inline=True
        )
        embed.add_field(
            name="Balance",
            value=f"{self.player.coin} coin",
            inline=True
        )

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
        await interaction.response.edit_message(
            content=None, embed=self.build_stage_embed(), view=self
        )

    async def _close_shop_btn(self, interaction: discord.Interaction):
        await self._close_shop(interaction)

    async def _close_shop(self, interaction: discord.Interaction):
        self.player.shop_complete = True
        self.player.last_active   = datetime.utcnow()

        # Load skill points and award shop XP
        sp = self.session.query(SkillPoints).filter_by(
            player_id=self.player.id
        ).first()
        xp_earned  = calculate_shop_xp(
            self.cumulative_score,
            self.customers_served,
            self.huge_profit_count
        )
        levelled_up, new_level = apply_xp_and_check_levelup(
            self.player, sp, xp_earned
        )
        self.session.commit()

        if levelled_up:
            await post_levelup_message(
                interaction.guild,
                self.player.shop_name,
                interaction.user.display_name,
                new_level,
                sp,
            )

        # Award social wins and check char level-up
        for _ in range(self.social_wins_earned):
            char_levelled, char_new_lvl = apply_char_win(
                self.player, WIN_SOCIAL
            )
            self.session.commit()
            if char_levelled:
                await post_char_levelup_message(
                    interaction.guild,
                    self.player.shop_name,
                    interaction.user.display_name,
                    char_new_lvl,
                    self.player,
                )

        next_threshold = SHOP_LEVEL_THRESHOLDS.get(self.player.shop_level, 999)
        embed = discord.Embed(
            title="The Magic Closet — Closed for the Day",
            description="The last customer has left. You flip the sign to closed.",
            color=0xe74c3c,
        )
        embed.add_field(
            name="Total Earned Today",
            value=f"{self.total_coin_earned} coin",
            inline=True
        )
        embed.add_field(
            name="Current Balance",
            value=f"{self.player.coin} coin",
            inline=True
        )
        embed.add_field(
            name="Shop XP",
            value=f"+{xp_earned} XP  |  {self.player.xp} / {next_threshold} XP  (Level {self.player.shop_level})",
            inline=False,
        )
        if levelled_up:
            embed.add_field(
                name="Level Up!",
                value="Bizard has sent you a message. Check your channel.",
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

    @app_commands.command(
        name="openshop",
        description="Open the Magic Closet and sell today's stock."
    )
    async def openshop(self, interaction: discord.Interaction):
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
                    "You haven't stocked your shelves yet. Run /prepstore first.",
                    ephemeral=True,
                )
                session.close()
                return

            if not can_shop(player):
                msg = (
                    "The shelves are bare. Stock them first with /prepstore."
                    if not player.prep_complete
                    else "The Magic Closet has already closed for the day. Come back tomorrow."
                )
                await interaction.response.send_message(msg, ephemeral=True)
                session.close()
                return

            # Chaos stock — player skipped prep, stock 4 random items
            chaos = is_chaos_stock(player)
            if chaos:
                all_bank = session.query(BankItem).filter_by(
                    player_id=player.id, on_floor=False
                ).all()
                if all_bank:
                    import random as _random
                    chosen = _random.sample(all_bank, min(4, len(all_bank)))
                    for item in chosen:
                        item.on_floor = True
                    player.prep_complete = True
                    session.commit()

            shelf = session.query(BankItem).filter_by(
                player_id=player.id, on_floor=True
            ).all()

            if not shelf:
                await interaction.response.send_message(
                    "Nothing on the shelves. Run /prepstore to stock up.",
                    ephemeral=True,
                )
                session.close()
                return

            customer_pool = _load_customer_pool(player)

            if customer_pool is None:
                customer_pool = _generate_customer_pool(shelf)
                _lock_customer_pool(player, customer_pool, session)
            else:
                floor_ids     = {item.item_id for item in shelf}
                customer_pool = [
                    c for c in customer_pool if c["item_id"] in floor_ids
                ]
                if not customer_pool:
                    await interaction.response.send_message(
                        "All items have already been sold today.",
                        ephemeral=True,
                    )
                    session.close()
                    return

            view  = ShopView(session, player, shelf, customer_pool, chaos=chaos)
            embed = view.build_stage_embed()
            await interaction.response.send_message(embed=embed, view=view)

        except Exception as e:
            session.close()
            raise e


async def setup(bot):
    await bot.add_cog(ShopCog(bot))
