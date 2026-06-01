"""
game/server_setup.py
Utility for initializing The Magic Closet server structure.
Called from main.py on_guild_join. Safe to call multiple times.
"""

import discord

CATEGORY_NAME    = "The Magic Closet"
ENTRY_CHANNEL    = "start-your-franchise"
BREAK_ROOM       = "the-break-room"
REQUIRED_ROLE    = "Business Owner"
EMBED_COLOR      = 0x5B2D8E
SLOWMODE_SECONDS = 15


def build_entry_embed() -> discord.Embed:
    embed = discord.Embed(
        title="The Magic Closet — Open for Business",
        color=EMBED_COLOR,
    )
    embed.description = (
        "**A message from Bizard the Wizard:**\n\n"
        "*[PLACEHOLDER — Bizard storefront intro. Workshop with team.\n"
        "Short — 3 sentences max. Non-subscribers read this first.\n"
        "Make them want to subscribe before they finish reading it.]*\n\n"
        "— Bizard 🧙"
    )
    embed.add_field(
        name="Ready to open your franchise?",
        value=(
            "**Step 1 — Subscribe on Patreon**\n"
            "[PLACEHOLDER — Patreon link]\n\n"
            "**Step 2 — Link your Discord**\n"
            "Connect your Discord account to Patreon to receive the "
            "**Business Owner** role automatically.\n\n"
            "**Step 3 — Run /startshop**\n"
            "Once you have the role, run `/startshop` right here. "
            "You'll name your store, name your town, and get your "
            "private shop channel where the game lives."
        ),
        inline=False,
    )
    embed.add_field(
        name="Already a Business Owner?",
        value=(
            "Run `/startshop` below to open your franchise.\n\n"
            "[PLACEHOLDER — note for returning subscribers]"
        ),
        inline=False,
    )
    embed.set_footer(
        text="[PLACEHOLDER — Bizard footer. One line.]"
    )
    return embed


def build_break_room_embed() -> discord.Embed:
    embed = discord.Embed(title="The Break Room", color=EMBED_COLOR)
    embed.description = (
        "**From Bizard:**\n\n"
        "*[PLACEHOLDER — Bizard break room intro. Warm, collegial.]*\n\n"
        "— Bizard 🧙"
    )
    embed.add_field(
        name="House Rules",
        value=(
            "Open chat for all Business Owners.\n"
            "Share your wins, your losses, your dungeon horror stories.\n"
            "Screenshots and GIFs encouraged.\n\n"
            "**15 second cooldown** between messages.\n\n"
            "[PLACEHOLDER — any additional community guidelines.]"
        ),
        inline=False,
    )
    embed.set_footer(text="[PLACEHOLDER — break room footer]")
    return embed


async def setup_server(guild: discord.Guild, bot_user: discord.ClientUser) -> dict:
    """
    Idempotent server setup. Safe to call multiple times.
    Returns dict with category, entry_channel, break_room, already_existed keys.
    """
    result = {
        "category":        None,
        "entry_channel":   None,
        "break_room":      None,
        "already_existed": False,
    }

    bo_role = discord.utils.get(guild.roles, name=REQUIRED_ROLE)

    # ---------------------------------------------------------------------------
    # Category — deny @everyone, explicitly grant bot full access
    # Bot MUST have manage_channels + manage_permissions on the category
    # or it cannot create channels inside it.
    # ---------------------------------------------------------------------------
    cat_overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
        ),
        bot_user: discord.PermissionOverwrite(
            view_channel=True,
            manage_channels=True,
            manage_permissions=True,
            send_messages=True,
            read_message_history=True,
        ),
    }

    # Grant Business Owner role visibility to category
    if bo_role:
        cat_overwrites[bo_role] = discord.PermissionOverwrite(
            view_channel=True,
        )

    category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
    if category:
        result["already_existed"] = True
        # Retroactively fix permissions on existing category
        await category.edit(overwrites=cat_overwrites)
    else:
        category = await guild.create_category(
            CATEGORY_NAME,
            overwrites=cat_overwrites,
        )
    result["category"] = category

    # ---------------------------------------------------------------------------
    # #start-your-franchise
    # Everyone can view and use slash commands. No text messages.
    # ---------------------------------------------------------------------------
    entry_channel = discord.utils.get(guild.text_channels, name=ENTRY_CHANNEL)
    if not entry_channel:
        entry_overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                use_application_commands=True,
                read_message_history=True,
                add_reactions=False,
            ),
            bot_user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_messages=True,
                read_message_history=True,
            ),
        }
        if bo_role:
            entry_overwrites[bo_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                use_application_commands=True,
                read_message_history=True,
            )

        entry_channel = await guild.create_text_channel(
            name=ENTRY_CHANNEL,
            category=category,
            overwrites=entry_overwrites,
            topic="[PLACEHOLDER — channel topic]",
        )
        msg = await entry_channel.send(embed=build_entry_embed())
        await msg.pin()

    result["entry_channel"] = entry_channel

    # ---------------------------------------------------------------------------
    # #the-break-room
    # Business Owners only. Open chat. 15s slowmode.
    # ---------------------------------------------------------------------------
    break_room = discord.utils.get(guild.text_channels, name=BREAK_ROOM)
    if not break_room:
        break_overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
            ),
            bot_user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_messages=True,
                read_message_history=True,
            ),
        }
        if bo_role:
            break_overwrites[bo_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
                add_reactions=True,
            )

        break_room = await guild.create_text_channel(
            name=BREAK_ROOM,
            category=category,
            overwrites=break_overwrites,
            slowmode_delay=SLOWMODE_SECONDS,
            topic="[PLACEHOLDER — break room topic]",
        )
        msg = await break_room.send(embed=build_break_room_embed())
        await msg.pin()

    result["break_room"] = break_room
    return result
