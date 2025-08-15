from keep_alive import keep_alive

keep_alive()
https://github.com/MachuPishtuu/gq-roulette-bot/blob/main/main.py
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
COOLDOWN_PERIOD = timedelta(hours=0.25)  # set to 4 later if you want
SCORES_FILE = "scores.csv"
TEAMS_FILE = "current_teams.csv"   # new: persistent per-user team storage

# In-memory “last rolled” to prevent immediate repeats per slot (per user)
last_rolled = {}   # {user_id: {"lead": X, "side1": Y, "side2": Z}}
last_used = {}     # cooldown tracker for !rerollteam

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
                return {
                    "lead": row["lead"] or None,
                    "side1": row["side1"] or None,
                    "side2": row["side2"] or None
                }
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

# ------------------ SCORES PERSISTENCE (unchanged base + new partial helpers) ------------------

def get_week_start():
    # You can switch to timezone-aware if you want; utc is fine for now
    today = datetime.utcnow()
    start = today - timedelta(days=today.weekday())
    return start.date().isoformat()

def ensure_scores_file():
    if not os.path.exists(SCORES_FILE):
        with open(SCORES_FILE, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["user_id", "username", "week_start", "phase1", "phase2", "total"])

def load_user_scores_this_week(user_id: str):
    ensure_scores_file()
    week = get_week_start()
    with open(SCORES_FILE, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["user_id"] == user_id and row["week_start"] == week:
                return row
    return None

def upsert_user_scores(user_id: str, username: str, phase1: str | None, phase2: str | None):
    ensure_scores_file()
    week = get_week_start()
    rows = []
    found = False
    with open(SCORES_FILE, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["user_id"] == user_id and row["week_start"] == week:
                if phase1 is not None:
                    row["phase1"] = phase1
                if phase2 is not None:
                    row["phase2"] = phase2
                p1 = int(row["phase1"]) if row["phase1"].isdigit() else 0
                p2 = int(row["phase2"]) if row["phase2"].isdigit() else 0
                row["total"] = str(p1 + p2)
                row["username"] = username
                found = True
            rows.append(row)
    if not found:
        p1 = int(phase1) if (phase1 and phase1.isdigit()) else 0
        p2 = int(phase2) if (phase2 and phase2.isdigit()) else 0
        rows.append({
            "user_id": user_id,
            "username": username,
            "week_start": week,
            "phase1": phase1 or "",
            "phase2": phase2 or "",
            "total": str(p1 + p2)
        })
    with open(SCORES_FILE, "w", newline='', encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["user_id","username","week_start","phase1","phase2","total"])
        writer.writeheader()
        writer.writerows(rows)

# ------------------ BOT EVENTS ------------------

@bot.event
async def on_ready():
    print(f"Bot connected as {bot.user}")

# ------------------ COMMANDS: TEAM REROLLS ------------------

@bot.command()
async def rerollteam(ctx, *, phase: str):
    now = datetime.utcnow()
    user_id = ctx.author.id

    # Cooldown
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
    # sides may include leads (as you requested)
    side_pool = units[phase].get("Side", []) + lead_pool

    # Respect current team to avoid conflicts in the same roll
    current = load_current_team(str(user_id), phase)  # returns dict

    prev = last_rolled.get(user_id, {})
    lead = choose_unit(
        lead_pool,
        previous=prev.get("lead"),
        exclude=[x for x in [current.get("side1"), current.get("side2")] if x]
    )
    if not lead:
        await ctx.send("⚠️ Not enough unique leads.")
        return

    # Sides cannot duplicate the lead or the other side; also avoid previous per-slot repeat
    filtered_side_pool = [u for u in side_pool if u != lead]
    side1 = choose_unit(
        filtered_side_pool,
        previous=prev.get("side1"),
        exclude=[x for x in [current.get("lead"), current.get("side2")] if x]
    )
    if not side1:
        await ctx.send("⚠️ Not enough side units for Side 1.")
        return

    filtered_side_pool2 = [u for u in filtered_side_pool if u != side1]
    side2 = choose_unit(
        filtered_side_pool2,
        previous=prev.get("side2"),
        exclude=[x for x in [current.get("lead"), current.get("side1")] if x]
    )
    if not side2:
        await ctx.send("⚠️ Not enough side units for Side 2.")
        return

    # Save last-rolled prevention AND persist as current team
    last_rolled[user_id] = {"lead": lead, "side1": side1, "side2": side2}
    last_used[user_id] = now
    save_current_team(str(user_id), str(ctx.author), phase, lead, side1, side2)

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
    current = load_current_team(str(user_id), phase)
    prev = last_rolled.get(user_id, {})

    # Exclude current sides from being rolled as a lead (and avoid immediate repeat)
    lead = choose_unit(
        lead_pool,
        previous=prev.get("lead"),
        exclude=[x for x in [current.get("side1"), current.get("side2")] if x]
    )
    if not lead:
        await ctx.send("⚠️ No unique lead found.")
        return

    # Save into current team (keep existing sides)
    save_current_team(str(user_id), str(ctx.author), phase, lead, current.get("side1"), current.get("side2"))
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

    # sides can include leads pool too (as requested)
    pool = units[phase].get("Side", []) + units[phase].get("Lead", [])
    current = load_current_team(str(user_id), phase)
    prev = last_rolled.get(user_id, {})

    # Exclude current lead and current side2, and avoid immediate repeat for side1
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
    units = load_units()
    phase = phase.strip()
    if phase not in units:
        await ctx.send("❌ Invalid phase name.")
        return

    pool = units[phase].get("Side", []) + units[phase].get("Lead", [])
    current = load_current_team(str(user_id), phase)
    prev = last_rolled.get(user_id, {})

    # Exclude current lead and current side1, and avoid immediate repeat for side2
    options = [u for u in pool if u != current.get("lead") and u != current.get("side1")]
    side2 = choose_unit(options, previous=prev.get("side2"))
    if not side2:
        await ctx.send("⚠️ No unique Side 2 unit found.")
        return

    save_current_team(str(user_id), str(ctx.author), phase, current.get("lead"), current.get("side1"), side2)
    last_rolled.setdefault(user_id, {})["side2"] = side2
    await ctx.send(f"🛡️ **Your Side 2 unit for {phase}**: `{side2}`")

@bot.command()
async def currentteam(ctx, *, phase: str):
    """Show your saved team for a phase."""
    phase = phase.strip()
    team = load_current_team(str(ctx.author.id), phase)
    if not any(team.values()):
        await ctx.send("❌ You haven't rolled a team for this phase yet.")
        return
    embed = discord.Embed(title=f"📎 Your Current Team – {phase}", color=0x00ffcc)
    embed.add_field(name="🔹 Lead", value=team.get("lead") or "—", inline=False)
    embed.add_field(name="🔸 Side 1", value=team.get("side1") or "—", inline=True)
    embed.add_field(name="🔸 Side 2", value=team.get("side2") or "—", inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def phases(ctx):
    units = load_units()
    phase_list = sorted(units.keys())
    embed = discord.Embed(title="📚 Available Guild Quest Phases", color=0x00ffff)
    embed.description = "\n".join(f"• {phase}" for phase in phase_list)
    await ctx.send(embed=embed)

# ------------------ SCORE SYSTEM SECTION ------------------

@bot.command()
async def submit(ctx, p1: str, p2: str):
    if not (p1.isdigit() and p2.isdigit()):
        await ctx.send("❌ Both scores must be numeric.")
        return
    if len(p1) < 9 or len(p2) < 9:
        await ctx.send("❌ Each score must be at least 9 digits.")
        return

    user_id = str(ctx.author.id)
    username = str(ctx.author)

    upsert_user_scores(user_id, username, p1, p2)
    row = load_user_scores_this_week(user_id)
    total = int(row["total"]) if row else (int(p1) + int(p2))
    await ctx.send(f"✅ Score submitted for **{username}**! Total: **{total:,}**")

@bot.command()
async def submitp1(ctx, p1: str):
    """Submit/replace Phase 1 score only (9+ digits)."""
    if not p1.isdigit() or len(p1) < 9:
        await ctx.send("❌ Phase 1 score must be numeric and at least 9 digits.")
        return
    user_id = str(ctx.author.id)
    username = str(ctx.author)
    upsert_user_scores(user_id, username, p1, None)
    row = load_user_scores_this_week(user_id)
    await ctx.send(f"✅ Phase 1 saved: **{int(p1):,}**. Current total: **{int(row['total']):,}**" if row else "✅ Phase 1 saved.")

@bot.command()
async def submitp2(ctx, p2: str):
    """Submit/replace Phase 2 score only (9+ digits)."""
    if not p2.isdigit() or len(p2) < 9:
        await ctx.send("❌ Phase 2 score must be numeric and at least 9 digits.")
        return
    user_id = str(ctx.author.id)
    username = str(ctx.author)
    upsert_user_scores(user_id, username, None, p2)
    row = load_user_scores_this_week(user_id)
    await ctx.send(f"✅ Phase 2 saved: **{int(p2):,}**. Current total: **{int(row['total']):,}**" if row else "✅ Phase 2 saved.")

@bot.command()
async def leaderboard(ctx):
    ensure_scores_file()
    week = get_week_start()
    with open(SCORES_FILE, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        filtered = [r for r in reader if r["week_start"] == week]
        ranked = sorted(filtered, key=lambda x: int(x["total"] or 0), reverse=True)[:10]

    if not ranked:
        await ctx.send("📉 No scores submitted this week yet.")
        return

    desc = ""
    for i, row in enumerate(ranked, 1):
        name = row["username"]
        total = int(row["total"]) if (row["total"] or "0").isdigit() else 0
        desc += f"**{i}. {name}** – {total:,}\n"

    embed = discord.Embed(title=f"🏆 GQ Leaderboard – Week of {week}", description=desc, color=0xffd700)
    await ctx.send(embed=embed)

@bot.command()
async def myscore(ctx):
    row = load_user_scores_this_week(str(ctx.author.id))
    if row:
        p1 = int(row["phase1"]) if row["phase1"].isdigit() else 0
        p2 = int(row["phase2"]) if row["phase2"].isdigit() else 0
        total = int(row["total"]) if row["total"].isdigit() else (p1 + p2)
        await ctx.send(f"📊 Your score this week:\nPhase 1: {p1:,}\nPhase 2: {p2:,}\nTotal: {total:,}")
    else:
        await ctx.send("❌ You haven't submitted a score this week.")

# ------------------ HELP ------------------

@bot.command(name="gqhelp")
async def gq_help(ctx):
    embed = discord.Embed(title="📖 GQ Roulette Bot Commands", color=0x7289da)
    embed.add_field(name="!rerollteam <phase>", value="Roll a full team & save it (Lead + Side1 + Side2).", inline=False)
    embed.add_field(name="!rerolllead <phase>", value="Reroll only the lead (won’t conflict with your current sides).", inline=False)
    embed.add_field(name="!rerollside1 <phase>", value="Reroll only Side 1 (won’t conflict with your current lead/Side 2).", inline=False)
    embed.add_field(name="!rerollside2 <phase>", value="Reroll only Side 2 (won’t conflict with your current lead/Side 1).", inline=False)
    embed.add_field(name="!currentteam <phase>", value="Show your saved team for a phase.", inline=False)
    embed.add_field(name="!submit <p1> <p2>", value="Submit both scores (9+ digits each).", inline=False)
    embed.add_field(name="!submitp1 <p1>", value="Submit/update Phase 1 only (9+ digits).", inline=False)
    embed.add_field(name="!submitp2 <p2>", value="Submit/update Phase 2 only (9+ digits).", inline=False)
    embed.add_field(name="!leaderboard", value="Shows the weekly leaderboard.", inline=False)
    embed.add_field(name="!myscore", value="Shows your submitted scores for this week.", inline=False)
    embed.add_field(name="!phases", value="Lists all available phases.", inline=False)
    await ctx.send(embed=embed)

# ------------------ RUN ------------------

bot.run(TOKEN)
