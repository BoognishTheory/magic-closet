"""
cogs/startshop.py
Commands: /startshop, /renameshop, /renametown

/startshop  — One-time setup. Collects store name + town name via Modal.
              Creates private TMC-[storename] channel under "The Magic Closet" category.
              Posts Bizard welcome message. Blocked if already set up.

/renameshop — Rename store. 90-day cooldown. Renames Discord channel to match.
/renametown — Rename town. 90-day cooldown. No channel rename needed.

All three require the Business Owner role.
"""

import re
import discord
from discord import app_commands
from discord.ext import commands
from db.database import get_session
from db.models import Player, SkillPoints
from game.access import has_access, deny_access
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CATEGORY_NAME     = "The Magic Closet"
REQUIRED_ROLE     = "Business Owner"
EMBED_COLOR       = 0x5B2D8E
RENAME_COOLDOWN_DAYS = 90

# ---------------------------------------------------------------------------
# Content moderation — basic slur/blocklist check
# Extend BLOCKLIST as needed. Keep this list private and not public-facing.
# ---------------------------------------------------------------------------

BLOCKLIST = [
    # Add slurs and blocked terms here as lowercase strings.
    # The normaliser handles leet-speak substitutions before checking.
    # Example structure — replace with real list before launch:
    # "badword1", "badword2",
]

LEET_MAP = str.maketrans({
    "@": "a", "3": "e", "1": "l", "0": "o",
    "!": "i", "$": "s", "5": "s", "4": "a",
})

def _normalise(text: str) -> str:
    """Lowercase, strip diacritics approx, expand leet-speak."""
    return text.lower().translate(LEET_MAP)

def is_name_allowed(name: str) -> bool:
    """Returns True if name passes moderation. False if blocked."""
    normalised = _normalise(name)
    for term in BLOCKLIST:
        if term in normalised:
            return False
    return True

# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------

ALLOWED_CHARS = re.compile(r"^[a-zA-Z0-9 '\-&!]+$")

def validate_name(name: str) -> str | None:
    """
    Returns None if valid.
    Returns error string if invalid.
    """
    name = name.strip()
    if len(name) < 3:
        return "Name must be at least 3 characters."
    if len(name) > 40:
        return "Name must be 40 characters or fewer."
    if not ALLOWED_CHARS.match(name):
        return "Only letters, numbers, spaces, apostrophes, hyphens, ampersands, and exclamation marks are allowed."
    if not is_name_allowed(name):
        return "That name isn't available — please choose a different one."
    return None

# ---------------------------------------------------------------------------
# Channel helpers
# ---------------------------------------------------------------------------

def channel_name_from_store(shop_name: str) -> str:
    """Convert store name to Discord channel name: TMC-[storename-slugified]"""
    slug = shop_name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return f"tmc-{slug}"


async def get_or_create_category(guild: discord.Guild) -> discord.CategoryChannel:
    """Find or create 'The Magic Closet' category."""
    for cat in guild.categories:
        if cat.name == CATEGORY_NAME:
            return cat
    return await guild.create_category(CATEGORY_NAME)


async def create_player_channel(
    guild: discord.Guild,
    member: discord.Member,
    shop_name: str,
    bot_user: discord.ClientUser,
) -> discord.TextChannel:
    category = await get_or_create_category(guild)
    channel_name = channel_name_from_store(shop_name)

    # Simplified overwrites — no role iteration
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        ),
    }

    return await guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
        topic=f"The Magic Closet — {shop_name} | {member.display_name}'s franchise",
    )


async def find_player_channel(
    guild: discord.Guild,
    shop_name: str,
) -> discord.TextChannel | None:
    """Find an existing TMC channel by current shop name slug."""
    target = channel_name_from_store(shop_name)
    for ch in guild.text_channels:
        if ch.name == target:
            return ch
    return None

# ---------------------------------------------------------------------------
# Welcome message — written in Bizard's voice
# ---------------------------------------------------------------------------

def build_welcome_embed(
    player_name: str,
    shop_name: str,
    town_name: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🧙 Welcome to The Magic Closet — {shop_name}",
        description=(
            f"Congratulations, {player_name}.\n\n"
            f"You are now the proud franchise owner of **The Magic Closet — {shop_name}**, "
            f"serving the fine and presumably solvent residents of **{town_name}**.\n\n"
            f"The sign out front says *The Magic Closet*. It will always say *The Magic Closet*. "
            f"That is non-negotiable. Bizard has opinions about brand consistency.\n\n"
            f"But everything inside — the shelves, the regulars, the reputation, the inexplicable "
            f"dungeon in the back — that is *yours*. You built this. Well. You're about to build this.\n\n"
            f"Your first order of business is stocking the shelves. The portal is already humming. "
            f"Whatever comes through it is yours to sell.\n\n"
            f"*Begin with* `/prepstore` *to open your first day.*\n\n"
            f"— Bizard 🧙"
        ),
        color=EMBED_COLOR,
    )
    embed.set_footer(
        text=(
            "This is your private shop channel. "
            "All game commands are run from here. "
            "Nobody else can see this space."
        )
    )
    return embed

# ---------------------------------------------------------------------------
# Player helpers
# ---------------------------------------------------------------------------

def get_or_create_player(session, discord_id: str) -> Player:
    player = session.query(Player).filter_by(discord_id=discord_id).first()
    if not player:
        player = Player(
            discord_id=discord_id,
            created_at=datetime.utcnow(),
            last_active=datetime.utcnow(),
        )
        session.add(player)
        session.flush()
        skill_points = SkillPoints(player_id=player.id)
        session.add(skill_points)
        session.commit()
    return player


def cooldown_remaining(last_changed: datetime | None) -> timedelta | None:
    """Returns remaining cooldown timedelta, or None if cooldown has passed."""
    if not last_changed:
        return None
    elapsed = datetime.utcnow() - last_changed
    remaining = timedelta(days=RENAME_COOLDOWN_DAYS) - elapsed
    return remaining if remaining.total_seconds() > 0 else None

# ---------------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------------

class StartShopModal(discord.ui.Modal, title="Name Your Magic Closet Franchise"):
    shop_name = discord.ui.TextInput(
        label="Store Name",
        placeholder="e.g. The Crooked Wand, Odds & Ends, Bizard's Best",
        min_length=3,
        max_length=40,
    )
    town_name = discord.ui.TextInput(
        label="Town Name",
        placeholder="e.g. Mudwick, Fernhallow, East Nowhere",
        min_length=3,
        max_length=40,
    )

    def __init__(self, bot_ref):
        super().__init__()
        self.bot_ref = bot_ref

    async def on_submit(self, interaction: discord.Interaction):
        shop = self.shop_name.value.strip()
        town = self.town_name.value.strip()

        # Validate
        shop_err = validate_name(shop)
        if shop_err:
            await interaction.response.send_message(
                f"Store name issue: {shop_err}", ephemeral=True
            )
            return

        town_err = validate_name(town)
        if town_err:
            await interaction.response.send_message(
                f"Town name issue: {town_err}", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        session = get_session()
        try:
            player = get_or_create_player(session, str(interaction.user.id))

            # Check if already set up
            if player.shop_name:
                existing = await find_player_channel(interaction.guild, player.shop_name)
                mention = existing.mention if existing else f"TMC-{player.shop_name.lower()}"
                await interaction.followup.send(
                    f"Your shop is already set up! Head to {mention} to play.",
                    ephemeral=True,
                )
                return

            # Save names
            player.shop_name = shop
            player.town_name = town
            player.name_last_changed_shop = datetime.utcnow()
            player.name_last_changed_town = datetime.utcnow()
            session.commit()

            # Create channel
            channel = await create_player_channel(
                interaction.guild,
                interaction.user,
                shop,
                self.bot_ref.user,
            )

            # Post welcome message
            welcome = build_welcome_embed(
                interaction.user.display_name,
                shop,
                town,
            )
            await channel.send(embed=welcome)

            await interaction.followup.send(
                f"✨ Your franchise is open! Head to {channel.mention} to begin.",
                ephemeral=True,
            )

        except Exception as e:
            session.close()
            raise e
        finally:
            session.close()


class RenameShopModal(discord.ui.Modal, title="Rename Your Magic Closet"):
    new_name = discord.ui.TextInput(
        label="New Store Name",
        placeholder="e.g. The Crooked Wand, Odds & Ends",
        min_length=3,
        max_length=40,
    )

    def __init__(self, bot_ref, old_name: str):
        super().__init__()
        self.bot_ref = bot_ref
        self.old_name = old_name

    async def on_submit(self, interaction: discord.Interaction):
        new = self.new_name.value.strip()

        err = validate_name(new)
        if err:
            await interaction.response.send_message(
                f"Store name issue: {err}", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        session = get_session()
        try:
            player = session.query(Player).filter_by(
                discord_id=str(interaction.user.id)
            ).first()

            # Update name and timestamp
            player.shop_name = new
            player.name_last_changed_shop = datetime.utcnow()
            session.commit()

            # Rename Discord channel
            channel = await find_player_channel(interaction.guild, self.old_name)
            if channel:
                await channel.edit(
                    name=channel_name_from_store(new),
                    topic=f"The Magic Closet — {new} | {interaction.user.display_name}'s franchise",
                )
                await channel.send(
                    f"🧙 The sign has been updated. This is now **The Magic Closet — {new}**."
                )

            await interaction.followup.send(
                f"✨ Store renamed to **{new}**. Your channel has been updated.",
                ephemeral=True,
            )

        except Exception as e:
            session.close()
            raise e
        finally:
            session.close()


class RenameTownModal(discord.ui.Modal, title="Rename Your Town"):
    new_name = discord.ui.TextInput(
        label="New Town Name",
        placeholder="e.g. Mudwick, Fernhallow, East Nowhere",
        min_length=3,
        max_length=40,
    )

    async def on_submit(self, interaction: discord.Interaction):
        new = self.new_name.value.strip()

        err = validate_name(new)
        if err:
            await interaction.response.send_message(
                f"Town name issue: {err}", ephemeral=True
            )
            return

        session = get_session()
        try:
            player = session.query(Player).filter_by(
                discord_id=str(interaction.user.id)
            ).first()
            player.town_name = new
            player.name_last_changed_town = datetime.utcnow()
            session.commit()

            await interaction.response.send_message(
                f"✨ Your town has been renamed to **{new}**. "
                f"The residents have been notified. Most seem unbothered.",
                ephemeral=True,
            )

        except Exception as e:
            session.close()
            raise e
        finally:
            session.close()

# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class StartShopCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------------------------
    # /startshop
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="startshop",
        description="Open your Magic Closet franchise for the first time.",
    )
    async def startshop(self, interaction: discord.Interaction):
        if not has_access(interaction):
            await deny_access(interaction)
            return

        # Check if already set up
        session = get_session()
        try:
            player = session.query(Player).filter_by(
                discord_id=str(interaction.user.id)
            ).first()
            if player and player.shop_name:
                existing = await find_player_channel(interaction.guild, player.shop_name)
                mention = existing.mention if existing else f"`tmc-{player.shop_name.lower()}`"
                await interaction.response.send_message(
                    f"Your franchise is already open! Head to {mention}.",
                    ephemeral=True,
                )
                return
        finally:
            session.close()

        # Warn about 90-day cooldown before showing modal
        warning = discord.Embed(
            title="⚠️ Before You Name Your Franchise",
            description=(
                "Your **store name** and **town name** can only be changed "
                f"**once every {RENAME_COOLDOWN_DAYS} days** after you set them.\n\n"
                "Take a moment. Choose something you'll be happy with for a while.\n\n"
                "When you're ready, hit **Continue** to open the naming form."
            ),
            color=0xe67e22,
        )

        class ConfirmView(discord.ui.View):
            def __init__(self, bot_ref):
                super().__init__(timeout=120)
                self.bot_ref = bot_ref

            @discord.ui.button(label="Continue →", style=discord.ButtonStyle.success)
            async def confirm(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                await btn_interaction.response.send_modal(StartShopModal(self.bot_ref))
                self.stop()

            @discord.ui.button(label="Not Yet", style=discord.ButtonStyle.secondary)
            async def cancel(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                await btn_interaction.response.edit_message(
                    content="No problem. Run /startshop whenever you're ready.",
                    embed=None,
                    view=None,
                )
                self.stop()

        await interaction.response.send_message(
            embed=warning,
            view=ConfirmView(self.bot),
            ephemeral=True,
        )

    # -----------------------------------------------------------------------
    # /renameshop
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="renameshop",
        description="Rename your Magic Closet franchise. 90-day cooldown.",
    )
    async def renameshop(self, interaction: discord.Interaction):
        if not has_access(interaction):
            await deny_access(interaction)
            return

        session = get_session()
        try:
            player = session.query(Player).filter_by(
                discord_id=str(interaction.user.id)
            ).first()

            if not player or not player.shop_name:
                await interaction.response.send_message(
                    "You haven't set up your shop yet. Run /startshop first.",
                    ephemeral=True,
                )
                return

            remaining = cooldown_remaining(player.name_last_changed_shop)
            if remaining:
                days = remaining.days
                hours = remaining.seconds // 3600
                await interaction.response.send_message(
                    f"Your shop can't be renamed yet. "
                    f"You can rename again in **{days}d {hours}h**.",
                    ephemeral=True,
                )
                return

            old_name = player.shop_name

        finally:
            session.close()

        # Warn about cooldown reset
        warning = discord.Embed(
            title="⚠️ Rename Your Magic Closet",
            description=(
                f"You're about to rename **The Magic Closet — {old_name}**.\n\n"
                f"After renaming, you won't be able to change it again for "
                f"**{RENAME_COOLDOWN_DAYS} days**.\n\n"
                "Your Discord channel will also be renamed to match."
            ),
            color=0xe67e22,
        )

        class ConfirmView(discord.ui.View):
            def __init__(self, bot_ref, old):
                super().__init__(timeout=120)
                self.bot_ref = bot_ref
                self.old = old

            @discord.ui.button(label="Rename →", style=discord.ButtonStyle.success)
            async def confirm(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                await btn_interaction.response.send_modal(
                    RenameShopModal(self.bot_ref, self.old)
                )
                self.stop()

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                await btn_interaction.response.edit_message(
                    content="Rename cancelled.", embed=None, view=None
                )
                self.stop()

        await interaction.response.send_message(
            embed=warning,
            view=ConfirmView(self.bot, old_name),
            ephemeral=True,
        )

    # -----------------------------------------------------------------------
    # /renametown
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="renametown",
        description="Rename your town. 90-day cooldown.",
    )
    async def renametown(self, interaction: discord.Interaction):
        if not has_access(interaction):
            await deny_access(interaction)
            return

        session = get_session()
        try:
            player = session.query(Player).filter_by(
                discord_id=str(interaction.user.id)
            ).first()

            if not player or not player.town_name:
                await interaction.response.send_message(
                    "You haven't set up your shop yet. Run /startshop first.",
                    ephemeral=True,
                )
                return

            remaining = cooldown_remaining(player.name_last_changed_town)
            if remaining:
                days = remaining.days
                hours = remaining.seconds // 3600
                await interaction.response.send_message(
                    f"Your town can't be renamed yet. "
                    f"You can rename again in **{days}d {hours}h**.",
                    ephemeral=True,
                )
                return

            old_town = player.town_name

        finally:
            session.close()

        warning = discord.Embed(
            title="⚠️ Rename Your Town",
            description=(
                f"You're about to rename **{old_town}**.\n\n"
                f"After renaming, you won't be able to change it again for "
                f"**{RENAME_COOLDOWN_DAYS} days**."
            ),
            color=0xe67e22,
        )

        class ConfirmView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=120)

            @discord.ui.button(label="Rename →", style=discord.ButtonStyle.success)
            async def confirm(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                await btn_interaction.response.send_modal(RenameTownModal())
                self.stop()

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                await btn_interaction.response.edit_message(
                    content="Rename cancelled.", embed=None, view=None
                )
                self.stop()

        await interaction.response.send_message(
            embed=warning,
            view=ConfirmView(),
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Channel restriction helper — import this in other cogs
# ---------------------------------------------------------------------------

async def check_shop_channel(interaction: discord.Interaction) -> bool:
    """
    Returns True if the interaction is happening in the player's TMC channel.
    Returns False and sends an ephemeral redirect if not.

    Usage in any gated cog:
        from cogs.startshop import check_shop_channel
        if not await check_shop_channel(interaction):
            return
    """
    session = get_session()
    try:
        player = session.query(Player).filter_by(
            discord_id=str(interaction.user.id)
        ).first()

        if not player or not player.shop_name:
            await interaction.response.send_message(
                "You haven't opened your franchise yet. Run /startshop to begin.",
                ephemeral=True,
            )
            return False

        expected_name = channel_name_from_store(player.shop_name)
        if interaction.channel.name != expected_name:
            # Find and mention their actual channel
            channel = None
            for ch in interaction.guild.text_channels:
                if ch.name == expected_name:
                    channel = ch
                    break
            mention = channel.mention if channel else f"`{expected_name}`"
            await interaction.response.send_message(
                f"Your Magic Closet is over in {mention}. Head there to play.",
                ephemeral=True,
            )
            return False

        return True

    finally:
        session.close()


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def setup(bot: commands.Bot):
    await bot.add_cog(StartShopCog(bot))
