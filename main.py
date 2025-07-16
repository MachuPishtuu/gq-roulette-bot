from keep_alive import keep_alive

keep_alive()

import discord
from discord.ext import commands
import csv
import random
import os
from datetime import datetime, timedelta

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

COOLDOWN_PERIOD = timedelta(hours=0)
last_used = {}
last_rolled = {}  # For preventing duplicates in roles
SCORES_FILE = "scores.csv"

# ------------------ UNIT REROLL SECTION ------------------

def load_units():
    units_by_phase = {}
    with open("units.csv", newline='', encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            phase = row["Phase"].strip()
            if not phase:
                continue
            role = row["Role"]
            unit = row["UnitName"]
            if not unit.strip():
                continue
            if phase not in units_by_phase:
                units_by_phase[phase] = {"Lead": [], "Side": []}
            if role in units_by_phase[phase]:
                units_by_phase[phase][role].append(unit)
    return units_by_phase

@bot.event
async def on_ready():
    print(f"Bot connected as {bot.user}")

def choose_unit(pool, previous=None, exclude=None):
    options = [u for u in pool if u != previous and (exclude is None or u not in exclude)]
    return random.choice(options) if options else None

@bot.command()
async def rerollteam(ctx, *, phase: str):
    now = datetime.utcnow()
    user_id = ctx.author.id
    if user_id in last_used:
        time_since = now - last_used[user_id]
        if time_since < COOLDOWN_PERIOD:
            remaining = COOLDOWN_PERIOD - time_since
            mins = int(remaining.total_seconds() // 60)
            await ctx.send(f"⏳ You can use this command again in {mins} minutes.")
            return

    units = load_units()
    phase = phase.strip()
    if phase not in units:
        await ctx.send("❌ Invalid phase name.")
        return

    lead_pool = units[phase].get("Lead", [])
    side_pool = units[phase].get("Side", []) + lead_pool

    prev = last_rolled.get(user_id, {})
    lead = choose_unit(lead_pool, previous=prev.get("lead"))
    if not lead:
        await ctx.send("⚠️ Not enough unique leads.")
        return

    side_pool_filtered = [u for u in side_pool if u != lead]
    side1 = choose_unit(side_pool_filtered, previous=prev.get("side1"))
    side2 = choose_unit(side_pool_filtered, previous=prev.get("side2"), exclude=[side1])
    if not side1 or not side2:
        await ctx.send("⚠️ Not enough side units.")
        return

    last_rolled[user_id] = {"lead": lead, "side1": side1, "side2": side2}
    last_used[user_id] = now

    embed = discord.Embed(title=f"🎲 Your GQ Team – {phase}", color=0x00ffcc)
    embed.add_field(name="🔹 Lead (SP)", value=lead, inline=False)
    embed.add_field(name="🔸 Side 1", value=side1, inline=True)
    embed.add_field(name="🔸 Side 2", value=side2, inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def rerolllead(ctx, *, phase: str):
    user_id = ctx.author.id
    units = load_units()
    phase = phase.strip()
    if phase not in units:
        await ctx.send("❌ Invalid phase name.")
        return
    lead_pool = units[phase].get("Lead", [])
    prev = last_rolled.get(user_id, {})
    lead = choose_unit(lead_pool, previous=prev.get("lead"))
    if not lead:
        await ctx.send("⚠️ No unique lead found.")
        return
    last_rolled.setdefault(user_id, {})["lead"] = lead
    await ctx.send(f"🎯 **Your Lead unit for {phase}**: `{lead}`")

@bot.command()
async def rerollside1(ctx, *, phase: str):
    user_id = ctx.author.id
    units = load_units()
    phase = phase.strip()
    if phase not in units:
        await ctx.send("❌ Invalid phase name.")
        return
    pool = units[phase].get("Side", []) + units[phase].get("Lead", [])
    prev = last_rolled.get(user_id, {})
    side2 = prev.get("side2")
    lead = prev.get("lead")
    options = [u for u in pool if u != side2 and u != lead]
    side1 = choose_unit(options, previous=prev.get("side1"))
    if not side1:
        await ctx.send("⚠️ No unique Side 1 unit found.")
        return
    last_rolled.setdefault(user_id, {})["side1"] = side1
    await ctx.send(f"🛡️ **Your Side 1 unit for {phase}**: `{side1}`")

@bot.command()
async def rerollside2(ctx, *, phase: str):
    user_id = ctx.author.id
    units = load_units()
    phase = phase.strip()
    if phase not in units:
        await ctx.send("❌ Invalid phase name.")
        return
    pool = units[phase].get("Side", []) + units[phase].get("Lead", [])
    prev = last_rolled.get(user_id, {})
    side1 = prev.get("side1")
    lead = prev.get("lead")
    options = [u for u in pool if u != side1 and u != lead]
    side2 = choose_unit(options, previous=prev.get("side2"))
    if not side2:
        await ctx.send("⚠️ No unique Side 2 unit found.")
        return
    last_rolled.setdefault(user_id, {})["side2"] = side2
    await ctx.send(f"🛡️ **Your Side 2 unit for {phase}**: `{side2}`")

@bot.command()
async def phases(ctx):
    units = load_units()
    phase_list = sorted(units.keys())
    embed = discord.Embed(title="📚 Available Guild Quest Phases", color=0x00ffff)
    embed.description = "\n".join(f"• {phase}" for phase in phase_list)
    await ctx.send(embed=embed)

# ------------------ SCORE SYSTEM SECTION ------------------

def get_week_start():
    today = datetime.utcnow()
    start = today - timedelta(days=today.weekday())
    return start.date().isoformat()

def ensure_scores_file():
    if not os.path.exists(SCORES_FILE):
        with open(SCORES_FILE, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["user_id", "username", "week_start", "phase1", "phase2", "total"])

@bot.command()
async def submit(ctx, p1: str, p2: str):
    if not (p1.isdigit() and p2.isdigit()):
        await ctx.send("❌ Both scores must be numeric.")
        return
    if len(p1) < 9 or len(p2) < 9:
        await ctx.send("❌ Each score must be at least 9 digits.")
        return

    p1_int = int(p1)
    p2_int = int(p2)
    total = p1_int + p2_int

    ensure_scores_file()
    week = get_week_start()
    user_id = str(ctx.author.id)
    username = str(ctx.author)

    updated = False
    entries = []
    with open(SCORES_FILE, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["user_id"] == user_id and row["week_start"] == week:
                row["phase1"] = p1
                row["phase2"] = p2
                row["total"] = str(total)
                updated = True
            entries.append(row)

    if not updated:
        entries.append({
            "user_id": user_id,
            "username": username,
            "week_start": week,
            "phase1": p1,
            "phase2": p2,
            "total": str(total)
        })

    with open(SCORES_FILE, "w", newline='', encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["user_id", "username", "week_start", "phase1", "phase2", "total"])
        writer.writeheader()
        writer.writerows(entries)

    await ctx.send(f"✅ Score submitted for **{username}**! Total: **{total:,}**")

@bot.command()
async def leaderboard(ctx):
    ensure_scores_file()
    week = get_week_start()
    with open(SCORES_FILE, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        filtered = [r for r in reader if r["week_start"] == week]
        ranked = sorted(filtered, key=lambda x: int(x["total"]), reverse=True)[:10]

    if not ranked:
        await ctx.send("📉 No scores submitted this week yet.")
        return

    desc = ""
    for i, row in enumerate(ranked, 1):
        desc += f"**{i}. {row['username']}** – {int(row['total']):,}\n"

    embed = discord.Embed(title=f"🏆 GQ Leaderboard – Week of {week}", description=desc, color=0xffd700)
    await ctx.send(embed=embed)

@bot.command()
async def myscore(ctx):
    ensure_scores_file()
    week = get_week_start()
    user_id = str(ctx.author.id)
    with open(SCORES_FILE, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["user_id"] == user_id and row["week_start"] == week:
                await ctx.send(f"📊 Your score this week:\nPhase 1: {int(row['phase1']):,}\nPhase 2: {int(row['phase2']):,}\nTotal: {int(row['total']):,}")
                return
    await ctx.send("❌ You haven't submitted a score this week.")

# ------------------ HELP COMMAND ------------------

@bot.command(name="gqhelp")
async def gq_help(ctx):
    embed = discord.Embed(title="📖 GQ Roulette Bot Commands", color=0x7289da)
    embed.add_field(name="!rerollteam <phase>", value="Roll a full team. Cooldown: 4 hours.", inline=False)
    embed.add_field(name="!rerolllead <phase>", value="Reroll only the lead.", inline=False)
    embed.add_field(name="!rerollside1 <phase>", value="Reroll side 1 only.", inline=False)
    embed.add_field(name="!rerollside2 <phase>", value="Reroll side 2 only.", inline=False)
    embed.add_field(name="!submit <score1> <score2>", value="Submit your weekly scores.", inline=False)
    embed.add_field(name="!leaderboard", value="See top scores this week.", inline=False)
    embed.add_field(name="!myscore", value="View your submitted scores.", inline=False)
    embed.add_field(name="!phases", value="List all GQ phases.", inline=False)
    await ctx.send(embed=embed)

# ------------------ RUN BOT ------------------

bot.run(TOKEN)
