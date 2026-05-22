"""
game/server_setup.py
Utility for initializing The Magic Closet server structure.
Called from main.py on_guild_join and available for admin /setupserver command.

Creates under "The Magic Closet" category:
  #start-your-franchise  — visible to all, slash commands only, no text
  #the-break-room        — Business Owners only, images/GIFs only, 15s slowmode

Per-player TMC channels are created by /startshop in cogs/startshop.py.

Safe to call multiple times — checks for existing structure before creating.
"""

import discord

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CATEGORY_NAME    = "The Magic Closet"
ENTRY_CHANNEL    = "start-your-franchise"
BREAK_ROOM       = "the-break-room"
REQUIRED_ROLE    = "Business Owner"
EMBED_COLOR      = 0x5B2D8E
SLOWMODE_SECONDS = 15


# ---------------------------------------------------------------------------
# Welcome embed — #start-your-franchise
# ---------------------------------------------------------------------------

def build_entry_embed() -> discord.Embed:
    embed = discord.Embed(
        title="The Magic Closet — Open for Business",
        color=EMBED_COLOR,
    )

    # [PLACEHOLDER — workshop with team]
    # Bizard voice — short, punchy, inviting. This is the storefront.
    # Non-subscribers see this. Make it sell the game.
    # Tone: confident, slightly mysterious, genuinely exciting.
    # Something like: "The portal is open. The shelves are waiting.
    # Somewhere between here and the dungeon, something extraordinary
    # is about to happen. It's called commerce."
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
            "[PLACEHOLDER — note for returning subscribers or anyone "
            "who already has the role and needs to run setup]"
        ),
        inline=False,
    )

    # [PLACEHOLDER — workshop with team]
    # Footer: one dry Bizard line. Confident, brief.
    embed.set_footer(
        text=(
            "[PLACEHOLDER — Bizard footer. One line. "
            "Something like: 'The portal has been open since Tuesday. "
            "Nobody told you sooner. That's on you.']"
        )
    )

    return embed


# ---------------------------------------------------------------------------
# Welcome embed — #the-break-room
# ---------------------------------------------------------------------------

def build_break_room_embed() -> discord.Embed:
    embed = discord.Embed(
        title="The Break Room",
        color=EMBED_COLOR,
    )

    # [PLACEHOLDER — workshop with team]
    # Bizard voice — warm, collegial. This is where franchise owners hang out.
    # They've made it past /startshop. Bizard acknowledges them as peers.
    # Tone: slightly less formal than the entry channel. Still Bizard.
    # Something like: "You made it to the back. This is where the
    # real business happens — showing off your wins and pretending
    # the losses were strategic."
    embed.description = (
        "**From Bizard:**\n\n"
        "*[PLACEHOLDER — Bizard break room intro. Workshop with team.\n"
        "Warm, collegial, a little proud of everyone here.\n"
        "Acknowledge that this is the community space.\n"
        "Keep it to 3 sentences max.]*\n\n"
        "— Bizard 🧙"
    )

    embed.add_field(
        name="House Rules",
        value=(
            "**Images and GIFs only.**\n"
            "This is a show-and-tell channel. Huge profits, rare drops, "
            "level-ups, spectacular dungeon deaths — if it happened in your "
            "franchise, post it here.\n\n"
            "**15 second cooldown** between posts.\n\n"
            "[PLACEHOLDER — any additional community guidelines. "
            "Keep it short. Players read rules once if you're lucky.]"
        ),
        inline=False,
    )

    # [PLACEHOLDER — workshop with team]
    # Footer: one Bizard line. Community-spirited but still dry.
    embed.set_footer(
        text=(
            "[PLACEHOLDER — break room footer. "
            "Something like: 'What happens in the break room "
            "ends up on the leaderboard eventually.']"
        )
    )

    return embed


# ---------------------------------------------------------------------------
# Core setup function
# ---------------------------------------------------------------------------

async def setup_server(guild: discord.Guild, bot_user: discord.ClientUser) -> dict:
    """
    Idempotent server setup. Safe to call multiple times.
    Returns dict with category, entry_channel, break_room, already_existed keys.
    """
    result = {
        "category":       None,
        "entry_channel":  None,
        "break_room":     None,
        "already_existed": False,
    }

    # --- Find or create category ---
    category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
    if category:
        result["already_existed"] = True
    else:
        category = await guild.create_category(CATEGORY_NAME)
    result["category"] = category

    # --- Find or create Business Owner role reference ---
    bo_role = discord.utils.get(guild.roles, name=REQUIRED_ROLE)

    # -------------------------------------------------------------------
    # #start-your-franchise
    # Visible to everyone. Slash commands allowed. No text messages.
    # -------------------------------------------------------------------
    entry_channel = discord.utils.get(
        guild.text_channels, name=ENTRY_CHANNEL
    )
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

        entry_channel = await guild.create_text_channel(
            name=ENTRY_CHANNEL,
            category=category,
            overwrites=entry_overwrites,
            topic=(
                # [PLACEHOLDER — workshop with team]
                "[PLACEHOLDER — channel topic. Something like: "
                "'The entrance to The Magic Closet. "
                "Run /startshop to open your franchise.']"
            ),
        )

        embed = build_entry_embed()
        msg = await entry_channel.send(embed=embed)
        await msg.pin()

    result["entry_channel"] = entry_channel

    # -------------------------------------------------------------------
    # #the-break-room
    # Business Owners only. Images and GIFs only. 15s slowmode.
    # -------------------------------------------------------------------
    break_room = discord.utils.get(
        guild.text_channels, name=BREAK_ROOM
    )
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

        # Grant Business Owner role access if it exists
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
            topic=(
                # [PLACEHOLDER — workshop with team]
                "[PLACEHOLDER — break room topic. Something like: "
                "'Images and GIFs only. Show off your wins. "
                "15 second cooldown.']"
            ),
        )

        embed = build_break_room_embed()
        msg = await break_room.send(embed=embed)
        await msg.pin()

    result["break_room"] = break_room
    return result
