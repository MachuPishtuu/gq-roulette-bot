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

# === Settings ===
COOLDOWN_REROLLTEAM = timedelta(minutes=5)
COOLDOWN_REROLLLEAD = timedelta(minutes=5)
COOLDOWN_REROLLSIDE1 = timedelta(minutes=5)
COOLDOWN_REROLLSIDE2 = timedelta(minutes=5)
SCORES_FILE = "scores.csv"
TEAMS_FILE = "current_teams.csv"

# per-user cooldown trackers
last_used_rerollteam = {}
last_used_rerolllead = {}
last_used_rerollside1 = {}
last_used_rerollside2 = {}

# In-memory “last rolled” to prevent immediate repeats per slot (per user)
last_rolled = {}   # {user_id: {"lead": X, "side1": Y, "side2": Z}}

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

def choose_unit(pool, previous=None, exclude=None):
    exclude = exclude or []
    options = [u for u in pool if u != previous and u not in exclude]
    return random.choice(options) if options else None

# ------------------ CURRENT TEAM PERSISTENCE ------------------

def ensure_teams_file():
    if not os.path.exists(TEAMS_FILE):
        with open(TEAMS_FILE, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["user_id","username","phase","lead","side1","side2","updated_at"])

def load_current_team(user_id: str, phase: str):
    ensure_teams_file()
    with open(TEAMS_FILE, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["user_id"] == user_id and row["phase"].lower() == phase.lower():
                return {"lead": row["lead"] or None, "side1": row["side1"] or None, "side2": row["side2"] or None}
    return {"lead": None, "side1": None, "side2": None}

def save_current_team(user_id: str, username: str, phase: str, lead: str, side1: str, side2: str):
    ensure_teams_file()
    rows = []
    found = False
    with open(TEAMS_FILE, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["user_id"] == user_id and row["phase"].lower() == phase.lower():
                row["username"] = username
                row["lead"] = lead or ""
                row["side1"] = side1 or ""
                row["side2"] = side2 or ""
                row["updated_at"] = datetime.utcnow().isoformat()
                found = True
            rows.append(row)
    if not found:
        rows.append({
            "user_id": user_id,
            "username": username,
            "phase": phase,
            "lead": lead or "",
            "side1": side1 or "",
            "side2": side2 or "",
            "updated_at": datetime.utcnow().isoformat()
        })
    with open(TEAMS_FILE, "w", newline='', encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["user_id","username","phase","lead","side1","side2","updated_at"])
        writer.writeheader()
        writer.writerows(rows)

# ------------------ BOT EVENTS ------------------

@bot.event
async def on_ready():
    print(f"Bot connected as {bot.user}")

# ------------------ COMMANDS: TEAM REROLLS WITH INDEPENDENT COOLDOWNS ------------------

def check_cooldown(user_id, last_used_dict, cooldown_period):
    now = datetime.utcnow()
    if user_id in last_used_dict:
        elapsed = now - last_used_dict[user_id]
        if elapsed < cooldown_period:
            remaining = cooldown_period - elapsed
            return int(remaining.total_seconds() // 60)
    last_used_dict[user_id] = now
    return 0

@bot.command()
async def rerollteam(ctx, *, phase: str):
    user_id = ctx.author.id
    remaining = check_cooldown(user_id, last_used_rerollteam, COOLDOWN_REROLLTEAM)
    if remaining > 0:
        await ctx.send(f"⏳ You can use this command again in {remaining} minutes.")
        return

    units = load_units()
    phase = phase.strip()
    if phase not in units:
        await ctx.send("❌ Invalid phase name.")
        return

    lead_pool = units[phase].get("Lead", [])
    side_pool = units[phase].get("Side", []) + lead_pool
    current = load_current_team(str(user_id), phase)
    prev = last_rolled.get(user_id, {})

    lead = choose_unit(lead_pool, previous=prev.get("lead"), exclude=[current.get("side1"), current.get("side2")])
    if not lead:
        await ctx.send("⚠️ Not enough unique leads.")
        return

    filtered_side_pool = [u for u in side_pool if u != lead]
    side1 = choose_unit(filtered_side_pool, previous=prev.get("side1"), exclude=[current.get("lead"), current.get("side2")])
    if not side1:
        await ctx.send("⚠️ Not enough side units for Side 1.")
        return

    filtered_side_pool2 = [u for u in filtered_side_pool if u != side1]
    side2 = choose_unit(filtered_side_pool2, previous=prev.get("side2"), exclude=[current.get("lead"), current.get("side1")])
    if not side2:
        await ctx.send("⚠️ Not enough side units for Side 2.")
        return

    last_rolled[user_id] = {"lead": lead, "side1": side1, "side2": side2}
    save_current_team(str(user_id), str(ctx.author), phase, lead, side1, side2)

    embed = discord.Embed(title=f"🎲 Your GQ Team – {phase}", color=0x00ffcc)
    embed.add_field(name="🔹 Lead (SP)", value=lead, inline=False)
    embed.add_field(name="🔸 Side 1", value=side1, inline=True)
    embed.add_field(name="🔸 Side 2", value=side2, inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def rerolllead(ctx, *, phase: str):
    user_id = ctx.author.id
    remaining = check_cooldown(user_id, last_used_rerolllead, COOLDOWN_REROLLLEAD)
    if remaining > 0:
        await ctx.send(f"⏳ You can reroll your lead again in {remaining} minutes.")
        return

    units = load_units()
    phase = phase.strip()
    if phase not in units:
        await ctx.send("❌ Invalid phase name.")
        return

    lead_pool = units[phase].get("Lead", [])
    current = load_current_team(str(user_id), phase)
    prev = last_rolled.get(user_id, {})

    lead = choose_unit(lead_pool, previous=prev.get("lead"), exclude=[current.get("side1"), current.get("side2")])
    if not lead:
        await ctx.send("⚠️ No unique lead found.")
        return

    save_current_team(str(user_id), str(ctx.author), phase, lead, current.get("side1"), current.get("side2"))
    last_rolled.setdefault(user_id, {})["lead"] = lead
    await ctx.send(f"🎯 **Your Lead unit for {phase}**: `{lead}`")

@bot.command()
async def rerollside1(ctx, *, phase: str):
    user_id = ctx.author.id
    remaining = check_cooldown(user_id, last_used_rerollside1, COOLDOWN_REROLLSIDE1)
    if remaining > 0:
        await ctx.send(f"⏳ You can reroll Side 1 again in {remaining} minutes.")
        return

    units = load_units()
    phase = phase.strip()
    if phase not in units:
        await ctx.send("❌ Invalid phase name.")
        return

    pool = units[phase].get("Side", []) + units[phase].get("Lead", [])
    current = load_current_team(str(user_id), phase)
    prev = last_rolled.get(user_id, {})

    options = [u for u in pool if u != current.get("lead") and u != current.get("side2")]
    side1 = choose_unit(options, previous=prev.get("side1"))
    if not side1:
        await ctx.send("⚠️ No unique Side 1 unit found.")
        return

    save_current_team(str(user_id), str(ctx.author), phase, current.get("lead"), side1, current.get("side2"))
    last_rolled.setdefault(user_id, {})["side1"] = side1
    await ctx.send(f"🛡️ **Your Side 1 unit for {phase}**: `{side1}`")

@bot.command()
async def rerollside2(ctx, *, phase: str):
    user_id = ctx.author.id
    remaining = check_cooldown(user_id, last_used_rerollside2, COOLDOWN_REROLLSIDE2)
    if remaining > 0:
        await ctx.send(f"⏳ You can reroll Side 2 again in {remaining} minutes.")
        return

    units = load_units()
    phase = phase.strip()
    if phase not in units:
        await ctx.send("❌ Invalid phase name.")
        return

    pool = units[phase].get("Side", []) + units[phase].get("Lead", [])
    current = load_current_team(str(user_id), phase)
    prev = last_rolled.get(user_id, {})

    options = [u for u in pool if u != current.get("lead") and u != current.get("side1")]
    side2 = choose_unit(options, previous=prev.get("side2"))
    if not side2:
        await ctx.send("⚠️ No unique Side 2 unit found.")
        return

    save_current_team(str(user_id), str(ctx.author), phase, current.get("lead"), current.get("side1"), side2)
    last_rolled.setdefault(user_id, {})["side2"] = side2
    await ctx.send(f"🛡️ **Your Side 2 unit for {phase}**: `{side2}`")
    # ------------------ OTHER COMMANDS ------------------

@bot.command()
async def submit(ctx, *, args=None):
    # Replace this logic with your actual submit code
    await ctx.send("✅ Submit command received!")

@bot.command()
async def submitp1(ctx, *, args=None):
    # Replace this logic with your actual submitp1 code
    await ctx.send("✅ SubmitP1 command received!")

@bot.command()
async def gqhelp(ctx):
    # Replace this logic with your actual gqhelp code
    help_text = """
🎮 **GQ Roulette Bot Commands**
!rerollteam <phase> - Reroll your team
!rerolllead <phase> - Reroll your lead
!rerollside1 <phase> - Reroll side 1
!rerollside2 <phase> - Reroll side 2
!submit - Submit scores
!submitp1 - Submit Phase 1 score
!leaderboard - Show leaderboard
!phases - List all phases
!myscore - Show your score
"""
    await ctx.send(help_text)

@bot.command()
async def leaderboard(ctx):
    # Replace with actual leaderboard logic
    await ctx.send("📊 Leaderboard coming soon!")

@bot.command()
async def phases(ctx):
    # Replace with actual phases listing
    await ctx.send("🗂️ List of all phases coming soon!")

@bot.command()
async def myscore(ctx):
    # Replace with actual user score logic
    await ctx.send("🎯 Your current score coming soon!")


bot.run(TOKEN)
