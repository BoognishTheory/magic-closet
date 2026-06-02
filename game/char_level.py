"""
game/char_level.py
Character level-up logic. Parallel to game/level_up.py (shop level).
"""

import discord
import random
from config import CHAR_LEVEL_THRESHOLDS, CHAR_LEVEL_CAP, STARTING_STATS
from game.startshop_utils import channel_name_from_store


BIZARD_QUIPS = [
    "Bizard squints at you. 'You look different. Taller, maybe. Or just more dangerous.'",
    "The dungeon remembers you now. That's either very good or very bad.",
    "Bizard flips through a worn ledger. 'Ah yes. You've earned this one.'",
    "'Most people quit around here,' Bizard says. 'You are not most people.'",
    "Something has settled in you. The portal feels it. Bizard says nothing, but nods.",
    "The customers notice. They don't know why. You do.",
    "Bizard hands you a small envelope. Inside is a stat point and a note that says 'don't waste it.'",
    "'Growth,' Bizard announces to no one in particular. 'Happening. Right now. In this shop.'",
]

WIN_COMBAT = "combat"
WIN_SOCIAL = "social"

STAT_MAX   = 10
VALID_STATS = ["vitality", "brawn", "charm", "arcana", "fortune"]


def apply_char_win(player, win_type: str) -> tuple[bool, int]:
    """
    Records a win, awards 1 char_xp, checks threshold, fires level-up.
    Awards 1 stat_points_unspent on level-up.
    Returns (levelled_up: bool, new_char_level: int).
    Does NOT commit.
    """
    current_level = player.char_level or 1

    if current_level >= CHAR_LEVEL_CAP:
        return False, current_level

    if win_type == WIN_COMBAT:
        player.combat_wins = (player.combat_wins or 0) + 1
    elif win_type == WIN_SOCIAL:
        player.social_wins = (player.social_wins or 0) + 1

    player.char_xp = (player.char_xp or 0) + 1
    threshold = CHAR_LEVEL_THRESHOLDS.get(current_level, 999)

    if player.char_xp >= threshold:
        player.char_xp         -= threshold
        player.char_level       = current_level + 1
        # Award 1 stat point on character level-up
        player.stat_points_unspent = (player.stat_points_unspent or 0) + 1
        return True, player.char_level

    return False, current_level


def build_char_levelup_embed(
    player_name: str,
    new_level: int,
    player,
) -> discord.Embed:
    quip    = random.choice(BIZARD_QUIPS)
    unspent = player.stat_points_unspent or 1

    embed = discord.Embed(
        title=f"Character Level {new_level}",
        description=(
            f"*{quip}*\n\n"
            f"**{player_name}** has reached **Character Level {new_level}**.\n\n"
            f"You have been awarded **1 stat point**. "
            f"You now have **{unspent} unspent stat point{'s' if unspent != 1 else ''}**.\n\n"
            f"Use `/spendstat [stat]` to invest it.\n"
            f"Use `/status` to see your current stat block."
        ),
        color=0x3498db,
    )

    # Live stat block from DB — falls back to starting defaults
    vit  = player.vitality or STARTING_STATS["vitality"]
    brwn = player.brawn    or STARTING_STATS["brawn"]
    chrm = player.charm    or STARTING_STATS["charm"]
    arc  = player.arcana   or STARTING_STATS["arcana"]
    frt  = player.fortune  or STARTING_STATS["fortune"]

    embed.add_field(
        name="Current Stats",
        value=(
            f"Vitality: {vit}/10  |  Brawn: {brwn}/10  |  Charm: {chrm}/10\n"
            f"Arcana: {arc}/10  |  Fortune: {frt}/10"
        ),
        inline=False,
    )

    combat = player.combat_wins or 0
    social = player.social_wins or 0
    embed.add_field(
        name="Win Record",
        value=f"Combat: {combat}  |  Social: {social}",
        inline=False,
    )

    embed.set_footer(text="— The Magic Closet  |  Keep winning.")
    return embed


async def post_char_levelup_message(
    guild: discord.Guild,
    shop_name: str,
    player_name: str,
    new_level: int,
    player,
) -> None:
    if not shop_name:
        return

    channel_name = channel_name_from_store(shop_name)
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if not channel:
        return

    bot_member = guild.me
    if bot_member:
        perms = channel.permissions_for(bot_member)
        if not perms.send_messages or not perms.view_channel:
            try:
                await channel.set_permissions(
                    bot_member,
                    view_channel=True,
                    send_messages=True,
                    manage_messages=True,
                    read_message_history=True,
                )
            except Exception:
                return

    embed = build_char_levelup_embed(player_name, new_level, player)
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        pass
