import discord 
from discord.ext import commands
import config

intents: discord.Intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print("Bot is ready and slash commands synced.")


@bot.tree.command()
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong!")


@bot.tree.command()
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message("Hey!")


bot.run(config.DISCORD_TOKEN)