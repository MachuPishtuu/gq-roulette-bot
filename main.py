import os

TOKEN = os.getenv("DISCORD_TOKEN")
print(f"TOKEN loaded: {TOKEN is not None}")  # Should print True

import discord

intents = discord.Intents.default()
bot = discord.Client(intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

bot.run(TOKEN)
