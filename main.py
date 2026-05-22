import discord
from discord.ext import commands
from config import DISCORD_TOKEN
from db.database import init_db
from scheduler.jobs import start_scheduler
from game.server_setup import setup_server

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
    Creates The Magic Closet category and #start-your-franchise channel.
    Safe to call on re-add — checks for existing structure before creating.
    """
    print(f"Joined guild: {guild.name} (ID: {guild.id})")
    try:
        result = await setup_server(guild, bot.user)
        if result["already_existed"]:
            print(f"Server structure already exists in {guild.name} — skipped creation.")
        else:
            print(f"Server structure created in {guild.name}.")
            print(f"  Category: {result['category'].name}")
            print(f"  Channel:  #{result['channel'].name}")
    except Exception as e:
        print(f"Error during server setup in {guild.name}: {e}")


@bot.event
async def on_message(message: discord.Message):
    """
    Deletes non-slash-command messages in #start-your-franchise.
    Keeps the entry channel clean — only bot responses visible.
    Non-bot text messages are deleted with an ephemeral-style note.
    """
    # Ignore bot messages
    if message.author.bot:
        return

    if (
        message.guild
        and message.channel.name == "start-your-franchise"
    ):
        await message.delete()
        # Send a brief redirect — auto-deletes after 5 seconds
        notice = await message.channel.send(
            f"{message.author.mention} "
            # [PLACEHOLDER — workshop with team]
            # Short, friendly, not scolding. Something like:
            # "This channel is for /startshop only. Chat lives elsewhere."
            "[PLACEHOLDER — redirect message for non-command input in #start-your-franchise]",
        )
        import asyncio
        await asyncio.sleep(5)
        await notice.delete()

    await bot.process_commands(message)


bot.run(DISCORD_TOKEN)
