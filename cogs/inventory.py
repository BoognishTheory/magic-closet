"""
cogs/inventory.py
Slash command handlers for /bank and /inventory.

/bank   — Root → Branch navigation by item category. Button-driven.
/inventory — Compact daily snapshot. Single embed, no buttons.

Both commands are read-only and require the Patreon subscriber role.
"""

import discord
from discord import app_commands
from discord.ext import commands

from game.bank import (
    CATEGORIES,
    CATEGORY_EMOJI,
    RARITY_EMOJI,
    RARITY_ORDER,
    PAGE_SIZE,
    bank_browse_category,
    bank_summary,
    category_summary,
    floor_items,
    has_wondrous,
    active_quests_count,
)

# ---------------------------------------------------------------------------
# Config — adjust to match your bot's setup
# ---------------------------------------------------------------------------

PATREON_ROLE_NAME = "Patreon"   # Role name in your Discord server
EMBED_COLOR       = 0x5B2D8E    # Purple
DB_PATH           = "magic_closet.db"  # Path to your SQLite DB


# ---------------------------------------------------------------------------
# Role gate helper
# ---------------------------------------------------------------------------

def has_patreon_role(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    member = interaction.guild.get_member(interaction.user.id)
    if not member:
        return False
    return any(r.name == PATREON_ROLE_NAME for r in member.roles)


def gate_message() -> discord.Embed:
    embed = discord.Embed(
        description=(
            "✨ This command is available to Patreon subscribers.\n"
            "Support the show to unlock The Magic Closet!"
        ),
        color=EMBED_COLOR,
    )
    return embed


# ---------------------------------------------------------------------------
# Cycle state helper (mirrors spec sec 4.4)
# ---------------------------------------------------------------------------

def cycle_state_line(player) -> str:
    """
    player: any object/row with attributes prep_complete, shop_complete,
            dungeon_complete. Accepts sqlite3.Row or a simple namespace.
    """
    prep      = getattr(player, "prep_complete",    False)
    shop      = getattr(player, "shop_complete",    False)
    dungeon   = getattr(player, "dungeon_complete", False)

    if not prep and not shop and not dungeon:
        return "⏳ Ready to prep  ·  Run /prepstore to begin today's cycle"
    elif not prep:
        return "⏳ Prep pending  ·  /prepstore to stock the shelves"
    elif not shop:
        return "✅ Prep complete  ·  ⏳ Shop awaits  ·  /openshop to open"
    elif not dungeon:
        return "✅ Prep complete  ·  ✅ Shop complete  ·  ⏳ Dungeon awaits"
    else:
        return "✅ Full cycle complete  ·  Next cycle resets in 24h"


def get_player(player_id: int) -> object:
    """
    Fetches player row from DB. Returns a simple namespace with cycle flags.
    Returns a fresh (all-False) namespace if player row doesn't exist yet.
    """
    import sqlite3
    import types

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT prep_complete, shop_complete, dungeon_complete "
            "FROM player WHERE discord_id = ?",
            (player_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        ns = types.SimpleNamespace(
            prep_complete=False,
            shop_complete=False,
            dungeon_complete=False,
        )
        return ns

    return row


# ---------------------------------------------------------------------------
# Embed builders
# ---------------------------------------------------------------------------

def build_root_embed(player_name: str, total: int) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏦 Bizard's Bank  —  {player_name}",
        description=f"**{total} items** in bank  ·  Select a category below",
        color=EMBED_COLOR,
    )
    embed.set_footer(
        text="Categories with 0 items are greyed out  ·  /inventory for daily snapshot"
    )
    return embed


def build_branch_embed(
    player_name: str,
    category: str,
    result: dict,
    sort: str,
) -> discord.Embed:
    sort_label = "Rarity" if sort == "rarity" else "Value"
    paginated  = result["total_pages"] > 1

    description = f"**{result['total']} items**  ·  Sorted by: {sort_label}"
    if result["has_wondrous"]:
        description += (
            "\n\n✨ You have a Wondrous item. "
            "Bizard isn't sure where it came from. Neither should you be."
        )

    embed = discord.Embed(
        title=f"{CATEGORY_EMOJI.get(category, '')} {category}  —  {player_name}'s Bank",
        description=description,
        color=EMBED_COLOR,
    )

    for item in result["items"]:
        rarity_emoji  = RARITY_EMOJI.get(item["rarity"], "")
        rarity_label  = f"{rarity_emoji} {item['rarity']}"
        value_display = f"💰 {item['sell_value']} coin"
        embed.add_field(
            name=f"{rarity_emoji} {item['name']}",
            value=f"{rarity_label}  ·  {value_display}",
            inline=False,
        )

    if not result["items"]:
        embed.add_field(
            name="Empty",
            value=f"No {category} items in bank yet.",
            inline=False,
        )

    if paginated:
        embed.set_footer(
            text=f"Page {result['page']} of {result['total_pages']}  ·  {result['total']} {category}"
        )

    return embed


def build_inventory_embed(
    player_name: str,
    player,
    summary: dict,
    floor: list,
    quest_count: int,
) -> discord.Embed:
    state_line = cycle_state_line(player)

    embed = discord.Embed(
        title=f"🧙 Bizard's Inventory  —  {player_name}",
        description=state_line,
        color=EMBED_COLOR,
    )

    # Bank summary field
    if summary["total"] == 0:
        bank_value = "Empty — complete your first dungeon run tonight"
    else:
        rarity_parts = []
        for rarity in ["Common", "Uncommon", "Rare", "Very Rare", "Legendary", "Wondrous"]:
            count = summary["by_rarity"].get(rarity, 0)
            emoji = RARITY_EMOJI[rarity]
            rarity_parts.append(f"{emoji} {count}")
        bank_value = f"{summary['total']} items total  ·  " + "  ".join(rarity_parts)

    embed.add_field(name="🏦 Bank", value=bank_value, inline=False)

    # Floor field
    if floor:
        floor_lines = []
        for item in floor:
            emoji = RARITY_EMOJI.get(item["rarity"], "")
            floor_lines.append(f"{emoji} {item['name']}")
        floor_value = "\n".join(floor_lines)
    else:
        floor_value = "Shelves empty — /prepstore to stock up"

    embed.add_field(name="🏪 On the Floor", value=floor_value, inline=False)

    # Active quests field — omit if none
    if quest_count > 0:
        embed.add_field(
            name="🗺️ Active Quests",
            value=f"{quest_count} active quest(s) — see /quests for details",
            inline=False,
        )

    embed.set_footer(
        text="Use /bank to browse full inventory  ·  /prepstore to stock shelves"
    )
    return embed


# ---------------------------------------------------------------------------
# Discord Views
# ---------------------------------------------------------------------------

class BankRootView(discord.ui.View):
    def __init__(self, player_id: int, player_name: str, cat_counts: dict):
        super().__init__(timeout=900)  # 15 minutes
        self.player_id   = player_id
        self.player_name = player_name

        # Add one button per category — two rows of 3
        for i, category in enumerate(CATEGORIES):
            count    = cat_counts.get(category, 0)
            emoji    = CATEGORY_EMOJI.get(category, "")
            label    = f"{emoji} {category} ({count})"
            disabled = count == 0
            row      = 0 if i < 3 else 1

            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                disabled=disabled,
                row=row,
                custom_id=f"bank_cat_{category}",
            )
            btn.callback = self._make_callback(category)
            self.add_item(btn)

    def _make_callback(self, category: str):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            result = bank_browse_category(
                self.player_id, category, "rarity", 1, DB_PATH
            )
            embed = build_branch_embed(self.player_name, category, result, "rarity")
            view  = BankBranchView(
                self.player_id, self.player_name, category, "rarity", 1, result
            )
            await interaction.edit_original_response(embed=embed, view=view)
        return callback

    async def on_timeout(self):
        # Buttons go dead naturally — Discord handles this
        pass


class BankBranchView(discord.ui.View):
    def __init__(
        self,
        player_id:   int,
        player_name: str,
        category:    str,
        sort:        str,
        page:        int,
        result:      dict,
    ):
        super().__init__(timeout=900)
        self.player_id   = player_id
        self.player_name = player_name
        self.category    = category
        self.sort        = sort
        self.page        = page
        self.result      = result

        paginated   = result["total_pages"] > 1
        rarity_active = sort == "rarity"
        value_active  = sort == "value"

        # Row 0: Back | Sort: Rarity | Sort: Value
        self.add_item(self._back_button())
        self.add_item(self._sort_button("rarity", "Sort: Rarity ▼", rarity_active, 0))
        self.add_item(self._sort_button("value",  "Sort: Value ▼",  value_active,  0))

        # Row 1: Prev | Next (only when paginated)
        if paginated:
            self.add_item(self._page_button("prev", page <= 1, 1))
            self.add_item(self._page_button("next", page >= result["total_pages"], 1))

    # --- Back ---

    def _back_button(self) -> discord.ui.Button:
        btn = discord.ui.Button(
            label="◄ Back",
            style=discord.ButtonStyle.secondary,
            row=0,
            custom_id="bank_back",
        )
        btn.callback = self._back_callback
        return btn

    async def _back_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cat_counts = category_summary(self.player_id, DB_PATH)
        total      = sum(cat_counts.values())
        embed      = build_root_embed(self.player_name, total)
        view       = BankRootView(self.player_id, self.player_name, cat_counts)
        await interaction.edit_original_response(embed=embed, view=view)

    # --- Sort ---

    def _sort_button(
        self, sort_key: str, label: str, active: bool, row: int
    ) -> discord.ui.Button:
        btn = discord.ui.Button(
            label=label,
            style=discord.ButtonStyle.primary if active else discord.ButtonStyle.secondary,
            row=row,
            custom_id=f"bank_sort_{sort_key}",
        )
        btn.callback = self._make_sort_callback(sort_key)
        return btn

    def _make_sort_callback(self, sort_key: str):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            result = bank_browse_category(
                self.player_id, self.category, sort_key, 1, DB_PATH
            )
            embed = build_branch_embed(
                self.player_name, self.category, result, sort_key
            )
            view = BankBranchView(
                self.player_id, self.player_name,
                self.category, sort_key, 1, result,
            )
            await interaction.edit_original_response(embed=embed, view=view)
        return callback

    # --- Pagination ---

    def _page_button(
        self, direction: str, disabled: bool, row: int
    ) -> discord.ui.Button:
        label = "◄ Prev" if direction == "prev" else "Next ►"
        btn   = discord.ui.Button(
            label=label,
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
            row=row,
            custom_id=f"bank_page_{direction}",
        )
        btn.callback = self._make_page_callback(direction)
        return btn

    def _make_page_callback(self, direction: str):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            new_page = self.page + (1 if direction == "next" else -1)
            result   = bank_browse_category(
                self.player_id, self.category, self.sort, new_page, DB_PATH
            )
            embed = build_branch_embed(
                self.player_name, self.category, result, self.sort
            )
            view = BankBranchView(
                self.player_id, self.player_name,
                self.category, self.sort, new_page, result,
            )
            await interaction.edit_original_response(embed=embed, view=view)
        return callback


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class InventoryCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------------------------
    # /bank
    # -----------------------------------------------------------------------

    @app_commands.command(name="bank", description="Browse your full item bank by category.")
    async def bank(self, interaction: discord.Interaction):
        if not has_patreon_role(interaction):
            await interaction.response.send_message(
                embed=gate_message(), ephemeral=True
            )
            return

        player_id   = interaction.user.id
        player_name = interaction.user.display_name
        cat_counts  = category_summary(player_id, DB_PATH)
        total       = sum(cat_counts.values())

        embed = build_root_embed(player_name, total)
        view  = BankRootView(player_id, player_name, cat_counts)

        await interaction.response.send_message(embed=embed, view=view)

    # -----------------------------------------------------------------------
    # /inventory
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="inventory",
        description="Quick daily snapshot — bank summary, shop floor, cycle state.",
    )
    async def inventory(self, interaction: discord.Interaction):
        if not has_patreon_role(interaction):
            await interaction.response.send_message(
                embed=gate_message(), ephemeral=True
            )
            return

        player_id   = interaction.user.id
        player_name = interaction.user.display_name

        player      = get_player(player_id)
        summary     = bank_summary(player_id, DB_PATH)
        floor       = floor_items(player_id, DB_PATH)
        quest_count = active_quests_count(player_id, DB_PATH)

        embed = build_inventory_embed(
            player_name, player, summary, floor, quest_count
        )
        await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def setup(bot: commands.Bot):
    await bot.add_cog(InventoryCog(bot))
