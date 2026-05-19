"""
cogs/inventory.py
Slash command handlers for /bank and /inventory.

/bank      — Root → Branch navigation by item category. Button-driven.
/inventory — Compact daily snapshot. Single embed, no buttons.

Both commands require the Patreon subscriber role.
"""

import types
import discord
from discord import app_commands
from discord.ext import commands

from game.bank import (
    CATEGORIES,
    CATEGORY_EMOJI,
    RARITY_EMOJI,
    bank_browse_category,
    bank_summary,
    category_summary,
    floor_items,
    active_quests_count,
    get_player_by_discord_id,
)

# ---------------------------------------------------------------------------
# Config — update PATREON_ROLE_NAME to match your server's exact role name
# ---------------------------------------------------------------------------

PATREON_ROLE_NAME = "Business Owner"
EMBED_COLOR       = 0x5B2D8E


# ---------------------------------------------------------------------------
# Role gate
# ---------------------------------------------------------------------------

def has_patreon_role(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    member = interaction.guild.get_member(interaction.user.id)
    if not member:
        return False
    return any(r.name == PATREON_ROLE_NAME for r in member.roles)


def gate_embed() -> discord.Embed:
    return discord.Embed(
        description=(
            "✨ This command is available to Patreon subscribers.\n"
            "Support the show to unlock The Magic Closet!"
        ),
        color=EMBED_COLOR,
    )


# ---------------------------------------------------------------------------
# Cycle state line
# ---------------------------------------------------------------------------

def cycle_state_line(player) -> str:
    prep    = getattr(player, "prep_complete",    False) or False
    shop    = getattr(player, "shop_complete",    False) or False
    dungeon = getattr(player, "dungeon_complete", False) or False

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
    category:    str,
    result:      dict,
    sort:        str,
) -> discord.Embed:
    sort_label = "Rarity" if sort == "rarity" else "Value"
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

    if result["items"]:
        for item in result["items"]:
            rarity_emoji = RARITY_EMOJI.get(item["rarity"], "")
            embed.add_field(
                name=f"{rarity_emoji} {item['name']}",
                value=f"{rarity_emoji} {item['rarity']}  ·  💰 {item['sell_value']} coin",
                inline=False,
            )
    else:
        embed.add_field(
            name="Empty",
            value=f"No {category} items in bank yet.",
            inline=False,
        )

    if result["total_pages"] > 1:
        embed.set_footer(
            text=(
                f"Page {result['page']} of {result['total_pages']}"
                f"  ·  {result['total']} {category}"
            )
        )
    return embed


def build_inventory_embed(
    player_name:  str,
    player,
    summary:      dict,
    floor:        list,
    quest_count:  int,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🧙 Bizard's Inventory  —  {player_name}",
        description=cycle_state_line(player),
        color=EMBED_COLOR,
    )

    # Bank summary
    if summary["total"] == 0:
        bank_value = "Empty — complete your first dungeon run tonight"
    else:
        parts = []
        for rarity in ["Common", "Uncommon", "Rare", "Very Rare", "Legendary", "Wondrous"]:
            count = summary["by_rarity"].get(rarity, 0)
            emoji = RARITY_EMOJI[rarity]
            parts.append(f"{emoji} {count}")
        bank_value = f"{summary['total']} items total  ·  " + "  ".join(parts)

    embed.add_field(name="🏦 Bank", value=bank_value, inline=False)

    # Floor
    if floor:
        lines = [
            f"{RARITY_EMOJI.get(item['rarity'], '')} {item['name']}"
            for item in floor
        ]
        floor_value = "\n".join(lines)
    else:
        floor_value = "Shelves empty — /prepstore to stock up"

    embed.add_field(name="🏪 On the Floor", value=floor_value, inline=False)

    # Active quests — omit if none
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
# Views
# ---------------------------------------------------------------------------

class BankRootView(discord.ui.View):
    def __init__(self, player_id: int, player_name: str, cat_counts: dict):
        super().__init__(timeout=900)
        self.player_id   = player_id
        self.player_name = player_name

        for i, category in enumerate(CATEGORIES):
            count    = cat_counts.get(category, 0)
            emoji    = CATEGORY_EMOJI.get(category, "")
            btn = discord.ui.Button(
                label=f"{emoji} {category} ({count})",
                style=discord.ButtonStyle.secondary,
                disabled=(count == 0),
                row=0 if i < 3 else 1,
                custom_id=f"bank_cat_{i}",
            )
            btn.callback = self._make_callback(category)
            self.add_item(btn)

    def _make_callback(self, category: str):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            result = bank_browse_category(self.player_id, category, "rarity", 1)
            embed  = build_branch_embed(self.player_name, category, result, "rarity")
            view   = BankBranchView(
                self.player_id, self.player_name, category, "rarity", 1, result
            )
            await interaction.edit_original_response(embed=embed, view=view)
        return callback


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

        paginated = result["total_pages"] > 1

        # Row 0 — Back | Sort: Rarity | Sort: Value
        back_btn = discord.ui.Button(
            label="◄ Back",
            style=discord.ButtonStyle.secondary,
            row=0, custom_id="bank_back",
        )
        back_btn.callback = self._back_callback
        self.add_item(back_btn)

        for sort_key, label in [("rarity", "Sort: Rarity ▼"), ("value", "Sort: Value ▼")]:
            btn = discord.ui.Button(
                label=label,
                style=(
                    discord.ButtonStyle.primary
                    if sort == sort_key
                    else discord.ButtonStyle.secondary
                ),
                row=0,
                custom_id=f"bank_sort_{sort_key}",
            )
            btn.callback = self._make_sort_callback(sort_key)
            self.add_item(btn)

        # Row 1 — Prev | Next (only when paginated)
        if paginated:
            prev_btn = discord.ui.Button(
                label="◄ Prev",
                style=discord.ButtonStyle.secondary,
                disabled=(page <= 1),
                row=1, custom_id="bank_prev",
            )
            prev_btn.callback = self._make_page_callback("prev")
            self.add_item(prev_btn)

            next_btn = discord.ui.Button(
                label="Next ►",
                style=discord.ButtonStyle.secondary,
                disabled=(page >= result["total_pages"]),
                row=1, custom_id="bank_next",
            )
            next_btn.callback = self._make_page_callback("next")
            self.add_item(next_btn)

    async def _back_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cat_counts = category_summary(self.player_id)
        total      = sum(cat_counts.values())
        embed      = build_root_embed(self.player_name, total)
        view       = BankRootView(self.player_id, self.player_name, cat_counts)
        await interaction.edit_original_response(embed=embed, view=view)

    def _make_sort_callback(self, sort_key: str):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            result = bank_browse_category(self.player_id, self.category, sort_key, 1)
            embed  = build_branch_embed(self.player_name, self.category, result, sort_key)
            view   = BankBranchView(
                self.player_id, self.player_name,
                self.category, sort_key, 1, result,
            )
            await interaction.edit_original_response(embed=embed, view=view)
        return callback

    def _make_page_callback(self, direction: str):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            new_page = self.page + (1 if direction == "next" else -1)
            result   = bank_browse_category(
                self.player_id, self.category, self.sort, new_page
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

    @app_commands.command(
        name="bank",
        description="Browse your full item bank by category.",
    )
    async def bank(self, interaction: discord.Interaction):
        if not has_patreon_role(interaction):
            await interaction.response.send_message(embed=gate_embed(), ephemeral=True)
            return

        player = get_player_by_discord_id(interaction.user.id)
        if not player:
            await interaction.response.send_message(
                "You don't have an account yet. Run /prepstore to get started!",
                ephemeral=True,
            )
            return

        cat_counts = category_summary(player.id)
        total      = sum(cat_counts.values())
        embed      = build_root_embed(interaction.user.display_name, total)
        view       = BankRootView(player.id, interaction.user.display_name, cat_counts)

        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(
        name="inventory",
        description="Quick daily snapshot — bank summary, shop floor, cycle state.",
    )
    async def inventory(self, interaction: discord.Interaction):
        if not has_patreon_role(interaction):
            await interaction.response.send_message(embed=gate_embed(), ephemeral=True)
            return

        player = get_player_by_discord_id(interaction.user.id)

        # New player — no DB row yet. Show empty state with fresh defaults.
        if not player:
            blank = types.SimpleNamespace(
                prep_complete=False,
                shop_complete=False,
                dungeon_complete=False,
            )
            embed = build_inventory_embed(
                interaction.user.display_name, blank,
                {"total": 0, "by_rarity": {}}, [], 0,
            )
            await interaction.response.send_message(embed=embed)
            return

        summary     = bank_summary(player.id)
        floor       = floor_items(player.id)
        quest_count = active_quests_count(player.id)

        embed = build_inventory_embed(
            interaction.user.display_name, player,
            summary, floor, quest_count,
        )
        await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def setup(bot: commands.Bot):
    await bot.add_cog(InventoryCog(bot))
