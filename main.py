import discord
from discord.ext import commands
from config import DISCORD_TOKEN
from db.database import init_db, get_session
from db.models import Player, ActiveRun
from scheduler.jobs import start_scheduler
from game.server_setup import setup_server, ENTRY_CHANNEL, BREAK_ROOM

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

MY_GUILD = discord.Object(id=1484388406065758349)

EXTENSIONS = [
    "cogs.prep",
    "cogs.shop",
    "cogs.admin",
    "cogs.dungeon",
    "cogs.explore",
    "cogs.quests",
    "cogs.leaderboard",
    "cogs.hotmarket",
    "cogs.inventory",
    "cogs.startshop",
    "cogs.skillpoints",
]


@bot.event
async def on_ready():
    init_db()
    print("Database initialized.")
    for ext in EXTENSIONS:
        if ext not in bot.extensions:
            await bot.load_extension(ext)
    print("Cogs loaded.")
    start_scheduler()
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        bot.tree.clear_commands(guild=MY_GUILD)
        bot.tree.copy_global_to(guild=MY_GUILD)
        synced = await bot.tree.sync(guild=MY_GUILD)
        print(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(e)


@bot.event
async def on_guild_join(guild: discord.Guild):
    """
    Fires when the bot is added to a server.
    Syncs slash commands immediately and creates server structure.
    """
    print(f"Joined guild: {guild.name} (ID: {guild.id})")

    try:
        guild_obj = discord.Object(id=guild.id)
        bot.tree.clear_commands(guild=guild_obj)
        bot.tree.copy_global_to(guild=guild_obj)
        synced = await bot.tree.sync(guild=guild_obj)
        print(f"Synced {len(synced)} slash command(s) to {guild.name}")
    except Exception as e:
        print(f"Command sync failed for {guild.name}: {e}")

    try:
        result = await setup_server(guild, bot.user)
        if result["already_existed"]:
            print(f"Server structure already exists in {guild.name} — skipped.")
        else:
            print(f"Server structure created in {guild.name}.")
            print(f"  Category:   {result['category'].name}")
            print(f"  Entry:      #{result['entry_channel'].name}")
            print(f"  Break room: #{result['break_room'].name}")
    except Exception as e:
        print(f"Error during server setup in {guild.name}: {e}")


# ---------------------------------------------------------------------------
# FT-02 — Session resume on interrupted gameplay
#
# When a player sends a message in their TMC channel, check whether they have
# an interrupted session (active dungeon run or incomplete shop phase) and
# remind them with a one-line prompt. Fires on any message — keeps them
# oriented after Discord interaction timeouts.
# ---------------------------------------------------------------------------

async def _check_resume_prompt(message: discord.Message):
    """
    If the player has an active run or an open shop phase, send a brief
    ephemeral-style reminder in their channel. Deletes after 10 seconds
    so it doesn't clutter the channel.
    """
    session = get_session()
    try:
        player = session.query(Player).filter_by(
            discord_id=str(message.author.id)
        ).first()

        if not player:
            return

        # Check for interrupted dungeon run
        active_run = session.query(ActiveRun).filter_by(
            player_id=player.id
        ).first()

        if active_run:
            reminder = await message.channel.send(
                f"{message.author.mention} You have an active dungeon run. "
                f"Use `/explore` to continue where you left off."
            )
            import asyncio
            await asyncio.sleep(10)
            await reminder.delete()
            return

        # Check for interrupted shop phase
        if player.prep_complete and not player.shop_complete:
            reminder = await message.channel.send(
                f"{message.author.mention} Your shop is still open. "
                f"Use `/openshop` to continue selling."
            )
            import asyncio
            await asyncio.sleep(10)
            await reminder.delete()

    finally:
        session.close()


@bot.event
async def on_message(message: discord.Message):
    """
    Channel enforcement and FT-02 session resume prompts.

    #start-your-franchise — deletes text messages, slash commands work.
    TMC channels         — sends resume prompt if player has active session.
    #the-break-room      — open chat, slowmode at channel level.
    """
    if message.author.bot:
        return

    if not message.guild:
        return

    import asyncio

    # #start-your-franchise — no text messages
    if message.channel.name == ENTRY_CHANNEL:
        await message.delete()
        notice = await message.channel.send(
            # [PLACEHOLDER — workshop with team]
            f"{message.author.mention} "
            f"[PLACEHOLDER — redirect message for text input in #start-your-franchise. "
            f"Direct them to /startshop.]",
        )
        await asyncio.sleep(5)
        await notice.delete()

    # TMC channels — FT-02 resume prompt
    elif message.channel.name.startswith("tmc-"):
        await _check_resume_prompt(message)

    # Break room — open chat, no enforcement needed.

    await bot.process_commands(message)


bot.run(DISCORD_TOKEN)
