import discord
from discord.ext import commands
from config import DISCORD_TOKEN
from db.database import init_db
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
    Creates The Magic Closet category, #start-your-franchise, and #the-break-room.
    Syncs slash commands to the guild immediately so no redeploy is needed.
    Safe to call on re-add — skips any structure that already exists.
    """
    print(f"Joined guild: {guild.name} (ID: {guild.id})")

    # Sync commands to this guild immediately on join
    try:
        guild_obj = discord.Object(id=guild.id)
        bot.tree.clear_commands(guild=guild_obj)
        bot.tree.copy_global_to(guild=guild_obj)
        synced = await bot.tree.sync(guild=guild_obj)
        print(f"Synced {len(synced)} slash command(s) to {guild.name}")
    except Exception as e:
        print(f"Command sync failed for {guild.name}: {e}")

    # Create server structure
    try:
        result = await setup_server(guild, bot.user)
        if result["already_existed"]:
            print(f"Server structure already exists in {guild.name} — skipped creation.")
        else:
            print(f"Server structure created in {guild.name}.")
            print(f"  Category:  {result['category'].name}")
            print(f"  Entry:     #{result['entry_channel'].name}")
            print(f"  Break room: #{result['break_room'].name}")
    except Exception as e:
        print(f"Error during server setup in {guild.name}: {e}")


@bot.event
async def on_message(message: discord.Message):
    """
    #start-your-franchise — deletes all text messages (slash commands still work).
    #the-break-room       — open chat, slowmode enforced at channel level.
    """
    if message.author.bot:
        return

    if not message.guild:
        return

    import asyncio

    if message.channel.name == ENTRY_CHANNEL:
        await message.delete()
        notice = await message.channel.send(
            # [PLACEHOLDER — workshop with team]
            # Short, friendly, not scolding.
            f"{message.author.mention} "
            f"[PLACEHOLDER — redirect message for text input in #start-your-franchise. "
            f"Direct them to /startshop.]",
        )
        await asyncio.sleep(5)
        await notice.delete()

    # Break room — open chat, no enforcement needed.
    # Slowmode (15s) set at channel level on creation.

    await bot.process_commands(message)


bot.run(DISCORD_TOKEN)
