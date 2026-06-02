"""
game/char_level.py
Character level-up logic. Parallel to game/level_up.py (shop level).

apply_char_win()         — increments combat_wins or social_wins, awards
                           char_xp, checks threshold, fires level-up.
post_char_levelup_msg()  — posts character level-up embed to TMC channel.

Character level-up is distinct from shop level-up:
  - Driven by wins (combat or social), not XP points
  - Awards 1 free stat point (wired in Character Level Up section)
  - Different embed tone — personal growth, not franchise milestone
  - Stat block shown with starting defaults until stat columns built
"""

import discord
import random
from config import CHAR_LEVEL_THRESHOLDS, CHAR_LEVEL_CAP, STARTING_STATS
from game.startshop_utils import channel_name_from_store


# ---------------------------------------------------------------------------
# Bizard character level quips — personal growth tone
# [PLACEHOLDER — workshop with team for final flavor text]
# ---------------------------------------------------------------------------

CHAR_LEVEL_QUIPS = [
    "Bizard squints at you. 'You look different. Taller, maybe. Or just more dangerous.'",
    "The dungeon remembers you now. That's either very good or very bad.",
    "Bizard flips through a worn ledger. 'Ah yes. You've earned this one.'",
    "'Most people quit around here,' Bizard says. 'You are not most people.'",
    "Something has settled in you. The portal feels it. Bizard says nothing, but nods.",
    "The customers notice. They don't know why. You do.",
    "Bizard hands you a small envelope. Inside is a stat point and a note that says 'don't waste it.'",
    "'Growth,' Bizard announces to no one in particular. 'Happening. Right now. In this shop.'",
]


# ---------------------------------------------------------------------------
# Win types
# ---------------------------------------------------------------------------

WIN_COMBAT = "combat"
WIN_SOCIAL = "social"


# ---------------------------------------------------------------------------
# Core character win logic
# ---------------------------------------------------------------------------

def apply_char_win(player, win_type: str) -> tuple[bool, int]:
    """
    Records a combat or social win, awards 1 char_xp, checks level threshold.
    Returns (levelled_up: bool, new_char_level: int).
    Does NOT commit — caller commits.

    win_type: WIN_COMBAT or WIN_SOCIAL
    """
    current_level = player.char_level or 1

    # Cap check — no progression beyond level 42
    if current_level >= CHAR_LEVEL_CAP:
        return False, current_level

    # Increment win counter
    if win_type == WIN_COMBAT:
        player.combat_wins = (player.combat_wins or 0) + 1
    elif win_type == WIN_SOCIAL:
        player.social_wins = (player.social_wins or 0) + 1

    # Award 1 char_xp per win
    player.char_xp = (player.char_xp or 0) + 1

    # Check threshold
    threshold = CHAR_LEVEL_THRESHOLDS.get(current_level, 999)
    if player.char_xp >= threshold:
        player.char_xp -= threshold
        player.char_level = current_level + 1
        return True, player.char_level

    return False, current_level


# ---------------------------------------------------------------------------
# Character level-up embed
# ---------------------------------------------------------------------------

def build_char_levelup_embed(
    player_name: str,
    new_level: int,
    player,
) -> discord.Embed:
    """
    Personal growth embed — distinct tone from shop level-up scroll.
    Shows new char level, stat block with current or default values.
    """
    quip = random.choice(CHAR_LEVEL_QUIPS)

    embed = discord.Embed(
        title=f"Character Level {new_level}",
        description=(
            f"*{quip}*\n\n"
            f"**{player_name}** has reached **Character Level {new_level}**.\n\n"
            f"A free stat point has been awarded.\n"
            f"Use `/spendstat [stat]` to invest it."
        ),
        color=0x3498db,
    )

    # Stat block — use DB values if columns exist, fall back to starting defaults
    vit  = getattr(player, "vitality", None) or STARTING_STATS["vitality"]
    brwn = getattr(player, "brawn",    None) or STARTING_STATS["brawn"]
    chrm = getattr(player, "charm",    None) or STARTING_STATS["charm"]
    arc  = getattr(player, "arcana",   None) or STARTING_STATS["arcana"]
    frt  = getattr(player, "fortune",  None) or STARTING_STATS["fortune"]

    embed.add_field(
        name="Current Stats",
        value=(
            f"Vitality: {vit}  |  Brawn: {brwn}  |  Charm: {chrm}\n"
            f"Arcana: {arc}  |  Fortune: {frt}"
        ),
        inline=False,
    )

    # Win totals
    combat = player.combat_wins or 0
    social = player.social_wins or 0
    embed.add_field(
        name="Win Record",
        value=f"Combat: {combat}  |  Social: {social}",
        inline=False,
    )

    embed.set_footer(text="— The Magic Closet  |  Keep winning.")
    return embed


# ---------------------------------------------------------------------------
# Post character level-up message to TMC channel
# ---------------------------------------------------------------------------

async def post_char_levelup_message(
    guild: discord.Guild,
    shop_name: str,
    player_name: str,
    new_level: int,
    player,
) -> None:
    """
    Posts character level-up embed to player's TMC channel.
    Checks and repairs bot permissions. Fails silently.
    """
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
