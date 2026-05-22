"""
game/server_setup.py
Utility for initializing The Magic Closet server structure.
Called from main.py on_guild_join and can be called from admin /setupserver command.

Creates:
- "The Magic Closet" category (if not present)
- #start-your-franchise channel (if not present)
- Pinned welcome message in #start-your-franchise

Safe to call multiple times — checks for existing structure before creating.
"""

import discord

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CATEGORY_NAME   = "The Magic Closet"
ENTRY_CHANNEL   = "start-your-franchise"
EMBED_COLOR     = 0x5B2D8E


# ---------------------------------------------------------------------------
# Welcome message
# ---------------------------------------------------------------------------

def build_welcome_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Welcome to The Magic Closet",
        color=EMBED_COLOR,
    )

    # --- Bizard voice section ---
    # [PLACEHOLDER — workshop with team]
    # Tone: warm, slightly pompous, genuinely excited. Bizard is proud of the
    # franchise model. He wants you here. He also wants you to know he built this.
    embed.description = (
        "**A message from Bizard the Wizard:**\n\n"
        "*[PLACEHOLDER — Bizard introduces the franchise. Something like:*\n"
        "*'The portal is open. The shelves are waiting. Somewhere between here*\n"
        "*and the dungeon, something extraordinary is about to happen.*\n"
        "*It's called commerce. Welcome to The Magic Closet.']*\n\n"
        "— Bizard 🧙"
    )

    # --- Practical instructions ---
    # [PLACEHOLDER — workshop with team]
    # Keep this tight. Players should be able to scan it in 10 seconds.
    embed.add_field(
        name="How to Open Your Franchise",
        value=(
            "**Step 1 — Become a subscriber**\n"
            "You'll need the **Business Owner** role to play.\n"
            "[PLACEHOLDER — add Patreon link here]\n\n"
            "**Step 2 — Start your franchise**\n"
            "Once you have the role, run `/startshop` right here in this channel.\n"
            "You'll name your store, name your town, and get your private shop channel.\n\n"
            "**Step 3 — Head to your channel**\n"
            "Everything happens in your private channel. "
            "Run `/prepstore` there to begin your first day."
        ),
        inline=False,
    )

    embed.add_field(
        name="Already a subscriber?",
        value=(
            "Run `/startshop` below. That's it. The rest explains itself.\n\n"
            "[PLACEHOLDER — any additional notes for returning or migrating subscribers]"
        ),
        inline=False,
    )

    embed.set_footer(
        text=(
            "[PLACEHOLDER — footer flavor text. Something short from Bizard. "
            "Could be a tagline or a dry one-liner.]"
        )
    )

    return embed


# ---------------------------------------------------------------------------
# Core setup function
# ---------------------------------------------------------------------------

async def setup_server(guild: discord.Guild, bot_user: discord.ClientUser) -> dict:
    """
    Idempotent server setup. Safe to call multiple times.
    Returns dict with 'category', 'channel', 'already_existed' keys.
    """
    result = {
        "category":       None,
        "channel":        None,
        "already_existed": False,
    }

    # --- Find or create category ---
    category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
    if category:
        result["already_existed"] = True
    else:
        category = await guild.create_category(CATEGORY_NAME)

    result["category"] = category

    # --- Find or create #start-your-franchise ---
    channel = discord.utils.get(guild.text_channels, name=ENTRY_CHANNEL)
    if not channel:
        # Everyone can view and use slash commands but cannot send messages
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                use_application_commands=True,
                read_message_history=True,
            ),
            bot_user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_messages=True,
                read_message_history=True,
            ),
        }

        channel = await guild.create_text_channel(
            name=ENTRY_CHANNEL,
            category=category,
            overwrites=overwrites,
            topic=(
                "[PLACEHOLDER — channel topic. Something like: "
                "'The entrance to The Magic Closet. Run /startshop to open your franchise.']"
            ),
        )

        # Post and pin the welcome message
        embed = build_welcome_embed()
        msg = await channel.send(embed=embed)
        await msg.pin()

    result["channel"] = channel
    return result
