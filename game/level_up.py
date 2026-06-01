"""
game/level_up.py
Shared level-up logic used by shop.py and explore.py.
"""

import discord
import random
from config import SHOP_LEVEL_THRESHOLDS
from game.startshop_utils import channel_name_from_store


BIZARD_QUIPS = [
    "The shelves shimmer. The portal hums a little louder. Something has changed.",
    "Bizard adjusts his hat. 'I always knew you had it in you. I said it from day one. Ask anyone.'",
    "The dungeon noticed. It is not pleased. Good.",
    "A skill point materializes in your palm. Bizard watches. 'Don't waste it on something boring.'",
    "Your regulars are talking. Word travels fast in towns with one magic shop.",
    "Bizard stamps your franchise certificate with unnecessary ceremony. 'There. Official.'",
    "The portal gave you something extra today. Bizard pretends he planned it.",
    "Level up. Bizard raises a glass of something that smells like lightning. 'To commerce.'",
]


def apply_xp_and_check_levelup(player, skill_points_row, xp_earned: int) -> tuple[bool, int]:
    """
    Adds XP to player and checks for level-up.
    Awards 1 unspent skill point if levelled up.
    Does NOT commit — caller must commit.
    """
    if xp_earned <= 0:
        return False, player.shop_level or 1

    player.xp = (player.xp or 0) + xp_earned
    current_level = player.shop_level or 1
    threshold = SHOP_LEVEL_THRESHOLDS.get(current_level, 999)

    if player.xp >= threshold:
        player.xp -= threshold
        player.shop_level = current_level + 1
        if skill_points_row:
            skill_points_row.unspent_points = (skill_points_row.unspent_points or 0) + 1
        return True, player.shop_level

    return False, current_level


def build_levelup_embed(
    player_name: str,
    new_level: int,
    skill_points_row,
) -> discord.Embed:
    quip    = random.choice(BIZARD_QUIPS)
    unspent = getattr(skill_points_row, "unspent_points", 1) or 1

    embed = discord.Embed(
        title="A scroll materializes in the air before you...",
        description=(
            f"*{quip}*\n\n"
            f"**The Magic Closet — Level {new_level}**\n\n"
            f"You have been awarded **1 skill point**. "
            f"You now have **{unspent} unspent point{'s' if unspent != 1 else ''}**.\n\n"
            f"Use `/skillpoints` to see your skill trees.\n"
            f"Use `/spendpoint [tree]` to spend your point."
        ),
        color=0xf1c40f,
    )

    if skill_points_row:
        ke = getattr(skill_points_row, "keen_eye",      0) or 0
        st = getattr(skill_points_row, "smooth_talker", 0) or 0
        hh = getattr(skill_points_row, "heavy_hauler",  0) or 0
        embed.add_field(
            name="Current Skill Tree Ranks",
            value=(
                f"🔮 Keen Eye: Rank {ke}\n"
                f"🗣️ Smooth Talker: Rank {st}\n"
                f"⚔️ Heavy Hauler: Rank {hh}"
            ),
            inline=False,
        )

    embed.set_footer(text="— Bizard the Wizard  |  The Magic Closet Franchise Network")
    return embed


async def post_levelup_message(
    guild: discord.Guild,
    shop_name: str,
    player_name: str,
    new_level: int,
    skill_points_row,
) -> None:
    """
    Finds the player's TMC channel and posts the level-up embed.
    Checks bot permissions before sending. Fails silently if blocked.
    """
    if not shop_name:
        return

    channel_name = channel_name_from_store(shop_name)
    channel = discord.utils.get(guild.text_channels, name=channel_name)

    if not channel:
        return

    # Verify bot has permission to send in this channel before attempting
    bot_member = guild.me
    if bot_member:
        perms = channel.permissions_for(bot_member)
        if not perms.send_messages or not perms.view_channel:
            # Bot lacks permission — attempt to fix overwrites then retry
            try:
                await channel.set_permissions(
                    bot_member,
                    view_channel=True,
                    send_messages=True,
                    manage_messages=True,
                    read_message_history=True,
                )
            except Exception:
                return  # Can't fix permissions — fail silently

    embed = build_levelup_embed(player_name, new_level, skill_points_row)
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        pass  # Fail silently — level-up still applies, message just didn't send
