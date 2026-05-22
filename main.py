import discord
from discord.ext import commands
from config import DISCORD_TOKEN
from db.database import init_db
from scheduler.jobs import start_scheduler

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

MY_GUILD = discord.Object(id=1484388406065758349)

EXTENSIONS = [
    "cogs.prep",
    "cogs.shop",
    "cogs.startshop",
    "cogs.admin",
    "cogs.dungeon",
    "cogs.explore",
    "cogs.quests",
    "cogs.leaderboard",
    "cogs.hotmarket",
    "cogs.inventory",
    "cogs.startshop"
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

bot.run(DISCORD_TOKEN)