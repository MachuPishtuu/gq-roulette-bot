import discord
import os

TOKEN = os.getenv("DISCORD_TOKEN")  # Make sure your token is in Render Environment Variables

intents = discord.Intents.default()
bot = discord.Client(intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print("Bot is running in idle mode — all commands disabled.")

bot.run(TOKEN)
