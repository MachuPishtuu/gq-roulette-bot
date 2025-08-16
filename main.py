from keep_alive import keep_alive
keep_alive()

import discord
from discord.ext import commands
import csv, os, json
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import re
import math
import random

# ========= CONFIG =========
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
COMMAND_PREFIX = "!"
UAETZ = ZoneInfo("Asia/Dubai")

COOLDOWN = timedelta(minutes=5)

SCORES_FILE = "scores.csv"
TEAMS_FILE = "current_teams.csv"
PHASES_FILE = "phases.json"   # maps week_start -> {"phase1": "...", "phase2": "..."}
UNITS_FILE = "units.csv"      # Phase,Affiliation,Range(0/1),Role(Lead/Side),UnitName

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

# ========= UTIL: FILES =========
def ensure_scores_file():
    if not os.path.exists(SCORES_FILE):
        with open(SCORES_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["user_id", "username", "week_start", "phase1", "phase2", "total"])

def ensure_teams_file():
    if not os.path.exists(TEAMS_FILE):
        with open(TEAMS_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["user_id","username","phase","lead","side1","side2","updated_at"])

def load_phases_map():
    if not os.path.exists(PHASES_FILE):
        return {}
    try:
        with open(PHASES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_phases_map(d):
    with open(PHASES_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

# ========= UTIL: TIME WINDOWS =========
def current_uae_now():
    return datetime.now(UAETZ)

def week_info(now_uae: datetime):
    """
    Weekly schedule (UAE time):
      Phase 1: Mon 19:00 -> Thu 19:00
      Phase 2: Thu 19:00 -> Sun 19:00
      Gap:     Sun 19:00 -> next Mon 19:00
    Returns: (week_start_date, active_slot) where active_slot in {"phase1","phase2",None}
    week_start_date is the Monday date (YYYY-MM-DD) aligned with that week's Mon 19:00 anchor.
    """
    # Find Monday of this calendar week
    monday = now_uae.date() - timedelta(days=now_uae.weekday())
    phase1_start = datetime.combine(monday, time(19,0), tzinfo=UAETZ)

    # If we're before Mon 19:00, we still belong to the previous week
    if now_uae < phase1_start:
        monday = monday - timedelta(days=7)
        phase1_start = datetime.combine(monday, time(19,0), tzinfo=UAETZ)

    phase1_end = phase1_start + timedelta(days=3)  # Thu 19:00
    phase2_end = phase1_start + timedelta(days=6)  # Sun 19:00

    if phase1_start <= now_uae < phase1_end:
        active = "phase1"
    elif phase1_end <= now_uae < phase2_end:
        active = "phase2"
    else:
        active = None  # Sunday eve -> Monday eve gap

    week_start_str = monday.isoformat()
    return week_start_str, active, phase1_start, phase1_end, phase2_end

# ========= UNITS LOADING =========
def load_units_index():
    """
    Build an index: { phase_name_lower: {"Lead": [...], "Side": [...]} }
    Role 'Side' contains only Side rows; we'll add Leads when choosing sides.
    """
    index = {}
    with open(UNITS_FILE, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        # If the first row looks like headers, ignore it; otherwise treat it as data
        def looks_like_header(row):
            joined = ",".join([c.lower() for c in row])
            return "phase" in joined and "role" in joined and "unit" in joined
        if header and not looks_like_header(header):
            # header was actually data
            f.seek(0)
            reader = csv.reader(f)

        for row in reader:
            if len(row) < 5:
                continue
            phase, affiliation, rng, role, unit = [c.strip() for c in row[:5]]
            if not phase or not role or not unit:
                continue
            ph_key = phase.lower()
            if ph_key not in index:
                index[ph_key] = {"Lead": [], "Side": []}
            if role.lower() == "lead":
                index[ph_key]["Lead"].append(unit)
            elif role.lower() == "side":
                index[ph_key]["Side"].append(unit)
    return index

# ========= TEAM PERSISTENCE =========
def load_current_team(user_id: int, phase_name: str):
    ensure_teams_file()
    with open(TEAMS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["user_id"] == str(user_id) and row["phase"].lower() == phase_name.lower():
                return {"lead": row["lead"] or None, "side1": row["side1"] or None, "side2": row["side2"] or None}
    return {"lead": None, "side1": None, "side2": None}

def save_current_team(user_id: int, username: str, phase_name: str, lead, side1, side2):
    ensure_teams_file()
    rows = []
    found = False
    with open(TEAMS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["user_id"] == str(user_id) and row["phase"].lower() == phase_name.lower():
                row["username"] = username
                row["lead"] = lead or ""
                row["side1"] = side1 or ""
                row["side2"] = side2 or ""
                row["updated_at"] = datetime.utcnow().isoformat()
                found = True
            rows.append(row)
    if not found:
        rows.append({
            "user_id": str(user_id),
            "username": username,
            "phase": phase_name,
            "lead": lead or "",
            "side1": side1 or "",
            "side2": side2 or "",
            "updated_at": datetime.utcnow().isoformat()
        })
    with open(TEAMS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["user_id","username","phase","lead","side1","side2","updated_at"])
        writer.writeheader()
        writer.writerows(rows)

# ========= COOLDOWNS =========
last_used = {
    "team": {},
    "lead": {},
    "side1": {},
    "side2": {},
}
def check_cooldown(user_id: int, bucket: str):
    now = datetime.utcnow()
    prev = last_used[bucket].get(user_id)
    if prev:
        elapsed = now - prev
        if elapsed < COOLDOWN:
            remain = COOLDOWN - elapsed
            return math.ceil(remain.total_seconds()/60)
    last_used[bucket][user_id] = now
    return 0

# ========= HELPERS =========
def normalize_phase_name(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())

def pick_random(pool, exclude=None):
    exclude = set([e for e in (exclude or []) if e])
    candidates = [x for x in pool if x not in exclude]
    if not candidates:
        return None
    return random.choice(candidates)

def get_active_phase_name_for_now():
    now = current_uae_now()
    week_start, active, *_ = week_info(now)
    phases_map = load_phases_map()
    entry = phases_map.get(week_start)
    if not entry:
        return week_start, active, None
    if active == "phase1":
        return week_start, active, entry.get("phase1")
    elif active == "phase2":
        return week_start, active, entry.get("phase2")
    else:
        return week_start, active, None

# ========= BOT EVENTS =========
@bot.event
async def on_ready():
    print(f"Bot connected as {bot.user}")

# ========= ADMIN: SET PHASES =========
@bot.command(name="setphases")
@commands.has_permissions(administrator=True)
async def setphases(ctx, *, args: str):
    """
    Usage:
      !setphases Phase One | Phase Two
    Quotes are optional; we split on the first '|'.
    """
    parts = [normalize_phase_name(p) for p in args.split("|")]
    if len(parts) < 2:
        await ctx.send("❌ Please provide two phases separated by `|`.\nExample: `!setphases Soul Reaper Melee | Arrancar Ranged`")
        return

    phase1, phase2 = parts[0], parts[1]
    now = current_uae_now()
    week_start, active, *_ = week_info(now)
    mp = load_phases_map()
    mp[week_start] = {"phase1": phase1, "phase2": phase2}
    save_phases_map(mp)

    await ctx.send(f"✅ Phases set for week starting **{week_start}** (UAE):\n**Phase 1:** {phase1}\n**Phase 2:** {phase2}\nActive window: **{active or 'None (gap)'}**")

@setphases.error
async def setphases_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Admins only.")

# ========= INFO: SHOW PHASES/CURRENT =========
@bot.command(name="phases")
async def phases_cmd(ctx):
    now = current_uae_now()
    week_start, active, p1_start, p1_end, p2_end = week_info(now)
    mp = load_phases_map()
    entry = mp.get(week_start, {})
    p1 = entry.get("phase1", "— not set —")
    p2 = entry.get("phase2", "— not set —")

    def fmt(dt): return dt.astimezone(UAETZ).strftime("%a %d %b %Y %H:%M")
    msg = (
        f"📆 **Week start (UAE): {week_start}**\n"
        f"**Phase 1:** {p1}  _(Mon 19:00 → Thu 19:00)_\n"
        f"**Phase 2:** {p2}  _(Thu 19:00 → Sun 19:00)_\n"
        f"🔔 **Active now:** {active or 'None (Sun 19:00 → Mon 19:00 gap)'}"
    )
    await ctx.send(msg)

# ========= SCORE SUBMISSION =========
def get_or_create_score_row(user_id: int, username: str, week_start: str):
    ensure_scores_file()
    rows = []
    found = None
    with open(SCORES_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
            if row["user_id"] == str(user_id) and row["week_start"] == week_start:
                found = row

    if not found:
        found = {
            "user_id": str(user_id),
            "username": username,
            "week_start": week_start,
            "phase1": "0",
            "phase2": "0",
            "total": "0",
        }
        rows.append(found)

    return rows, found

def write_scores(rows):
    with open(SCORES_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["user_id","username","week_start","phase1","phase2","total"])
        writer.writeheader()
        writer.writerows(rows)

def parse_score_arg(arg: str):
    # accept digits only; people sometimes paste with commas; strip them
    cleaned = re.sub(r"[^\d]", "", arg or "")
    if cleaned == "":
        return None
    try:
        return int(cleaned)
    except Exception:
        return None

@bot.command(name="submitp1")
async def submitp1(ctx, score: str):
    score_val = parse_score_arg(score)
    if score_val is None:
        await ctx.send("❌ Please provide a numeric score. Example: `!submitp1 524698600`")
        return
    now = current_uae_now()
    week_start, *_ = week_info(now)
    rows, row = get_or_create_score_row(ctx.author.id, str(ctx.author), week_start)
    row["username"] = str(ctx.author)
    row["phase1"] = str(score_val)
    total = int(row.get("phase1", "0") or 0) + int(row.get("phase2", "0") or 0)
    row["total"] = str(total)
    write_scores(rows)
    await ctx.send(f"✅ Saved **Phase 1** score `{score_val}` for **{ctx.author.display_name}** (week {week_start}). Total now `{total}`.")

@bot.command(name="submitp2")
async def submitp2(ctx, score: str):
    score_val = parse_score_arg(score)
    if score_val is None:
        await ctx.send("❌ Please provide a numeric score. Example: `!submitp2 372798271`")
        return
    now = current_uae_now()
    week_start, *_ = week_info(now)
    rows, row = get_or_create_score_row(ctx.author.id, str(ctx.author), week_start)
    row["username"] = str(ctx.author)
    row["phase2"] = str(score_val)
    total = int(row.get("phase1", "0") or 0) + int(row.get("phase2", "0") or 0)
    row["total"] = str(total)
    write_scores(rows)
    await ctx.send(f"✅ Saved **Phase 2** score `{score_val}` for **{ctx.author.display_name}** (week {week_start}). Total now `{total}`.")

@bot.command(name="myscore")
async def myscore(ctx):
    ensure_scores_file()
    now = current_uae_now()
    week_start, *_ = week_info(now)
    with open(SCORES_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["user_id"] == str(ctx.author.id) and row["week_start"] == week_start:
                p1 = int(row.get("phase1","0") or 0)
                p2 = int(row.get("phase2","0") or 0)
                tot = int(row.get("total","0") or 0)
                await ctx.send(f"🎯 **{ctx.author.display_name}** – Week {week_start}\nPhase 1: `{p1}`\nPhase 2: `{p2}`\n**Total:** `{tot}`")
                return
    await ctx.send(f"ℹ️ No scores yet for **{ctx.author.display_name}** (week {week_start}). Use `!submitp1` / `!submitp2`.")

@bot.command(name="leaderboard")
async def leaderboard(ctx):
    ensure_scores_file()
    now = current_uae_now()
    week_start, *_ = week_info(now)
    rows = []
    with open(SCORES_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["week_start"] == week_start:
                rows.append({
                    "username": row["username"],
                    "p1": int(row.get("phase1","0") or 0),
                    "p2": int(row.get("phase2","0") or 0),
                    "total": int(row.get("total","0") or 0),
                })
    if not rows:
        await ctx.send(f"📊 No entries yet for week {week_start}.")
        return
    rows.sort(key=lambda r: r["total"], reverse=True)
    lines = [f"**Week {week_start} Leaderboard**"]
    for i, r in enumerate(rows[:10], start=1):
        lines.append(f"{i}. {r['username']} — Total `{r['total']}` (P1 `{r['p1']}`, P2 `{r['p2']}`)")
    await ctx.send("\n".join(lines))

# ========= REROLL COMMANDS =========
_last_rolls = {}  # {user_id: {"lead": x, "side1": y, "side2": z}}

def choose_sets_for_phase(phase_name: str):
    idx = load_units_index()
    rec = idx.get(phase_name.lower())
    if not rec:
        return None, None
    leads = rec.get("Lead", [])
    sides = rec.get("Side", [])
    return leads, sides

async def _resolve_phase_for_command(ctx, provided_phase: str | None):
    if provided_phase and provided_phase.strip():
        return normalize_phase_name(provided_phase)
    week_start, active, active_name = get_active_phase_name_for_now()
    if active_name:
        return active_name
    await ctx.send("ℹ️ No active phase window right now (Sun 19:00 → Mon 19:00 UAE). Please specify a phase name, e.g. `!rerollteam Soul Reaper Melee`.")
    return None

@bot.command(name="rerollteam")
async def rerollteam(ctx, *, phase: str = None):
    # cooldown
    left = check_cooldown(ctx.author.id, "team")
    if left > 0:
        await ctx.send(f"⏳ You can use this command again in {left} minute(s).")
        return

    phase_name = await _resolve_phase_for_command(ctx, phase)
    if not phase_name:
        return

    leads, sides = choose_sets_for_phase(phase_name)
    if leads is None:
        await ctx.send("❌ Invalid phase name.")
        return

    # sides can include leads (pool for sides = Side + Lead)
    side_pool = list(sides) + list(leads)
    current = load_current_team(ctx.author.id, phase_name)
    prev = _last_rolls.get(ctx.author.id, {})

    lead = pick_random(leads, exclude=[prev.get("lead"), current.get("side1"), current.get("side2")])
    if not lead:
        await ctx.send("⚠️ Not enough unique leads.")
        return

    filtered1 = [u for u in side_pool if u != lead]
    side1 = pick_random(filtered1, exclude=[prev.get("side1"), current.get("lead"), current.get("side2")])
    if not side1:
        await ctx.send("⚠️ Not enough side options for Side 1.")
        return

    filtered2 = [u for u in filtered1 if u != side1]
    side2 = pick_random(filtered2, exclude=[prev.get("side2"), current.get("lead"), current.get("side1")])
    if not side2:
        await ctx.send("⚠️ Not enough side options for Side 2.")
        return

    _last_rolls[ctx.author.id] = {"lead": lead, "side1": side1, "side2": side2}
    save_current_team(ctx.author.id, str(ctx.author), phase_name, lead, side1, side2)

    embed = discord.Embed(title=f"🎲 Your GQ Team – {phase_name}", color=0x00ffcc)
    embed.add_field(name="🔹 Lead (SP)", value=lead, inline=False)
    embed.add_field(name="🔸 Side 1", value=side1, inline=True)
    embed.add_field(name="🔸 Side 2", value=side2, inline=True)
    await ctx.send(embed=embed)

@bot.command(name="rerolllead")
async def rerolllead(ctx, *, phase: str = None):
    left = check_cooldown(ctx.author.id, "lead")
    if left > 0:
        await ctx.send(f"⏳ You can reroll your lead again in {left} minute(s).")
        return

    phase_name = await _resolve_phase_for_command(ctx, phase)
    if not phase_name:
        return

    leads, sides = choose_sets_for_phase(phase_name)
    if leads is None:
        await ctx.send("❌ Invalid phase name.")
        return

    current = load_current_team(ctx.author.id, phase_name)
    prev = _last_rolls.get(ctx.author.id, {})

    lead = pick_random(leads, exclude=[prev.get("lead"), current.get("side1"), current.get("side2")])
    if not lead:
        await ctx.send("⚠️ No unique lead found.")
        return

    save_current_team(ctx.author.id, str(ctx.author), phase_name, lead, current.get("side1"), current.get("side2"))
    _last_rolls.setdefault(ctx.author.id, {})["lead"] = lead
    await ctx.send(f"🎯 **Lead ({phase_name})**: `{lead}`")

@bot.command(name="rerollside1")
async def rerollside1(ctx, *, phase: str = None):
    left = check_cooldown(ctx.author.id, "side1")
    if left > 0:
        await ctx.send(f"⏳ You can reroll Side 1 again in {left} minute(s).")
        return

    phase_name = await _resolve_phase_for_command(ctx, phase)
    if not phase_name:
        return

    leads, sides = choose_sets_for_phase(phase_name)
    if leads is None:
        await ctx.send("❌ Invalid phase name.")
        return

    pool = list(sides) + list(leads)
    current = load_current_team(ctx.author.id, phase_name)
    prev = _last_rolls.get(ctx.author.id, {})

    options = [u for u in pool if u != current.get("lead") and u != current.get("side2")]
    side1 = pick_random(options, exclude=[prev.get("side1")])
    if not side1:
        await ctx.send("⚠️ No unique Side 1 found.")
        return

    save_current_team(ctx.author.id, str(ctx.author), phase_name, current.get("lead"), side1, current.get("side2"))
    _last_rolls.setdefault(ctx.author.id, {})["side1"] = side1
    await ctx.send(f"🛡️ **Side 1 ({phase_name})**: `{side1}`")

@bot.command(name="rerollside2")
async def rerollside2(ctx, *, phase: str = None):
    left = check_cooldown(ctx.author.id, "side2")
    if left > 0:
        await ctx.send(f"⏳ You can reroll Side 2 again in {left} minute(s).")
        return

    phase_name = await _resolve_phase_for_command(ctx, phase)
    if not phase_name:
        return

    leads, sides = choose_sets_for_phase(phase_name)
    if leads is None:
        await ctx.send("❌ Invalid phase name.")
        return

    pool = list(sides) + list(leads)
    current = load_current_team(ctx.author.id, phase_name)
    prev = _last_rolls.get(ctx.author.id, {})

    options = [u for u in pool if u != current.get("lead") and u != current.get("side1")]
    side2 = pick_random(options, exclude=[prev.get("side2")])
    if not side2:
        await ctx.send("⚠️ No unique Side 2 found.")
        return

    save_current_team(ctx.author.id, str(ctx.author), phase_name, current.get("lead"), current.get("side1"), side2)
    _last_rolls.setdefault(ctx.author.id, {})["side2"] = side2
    await ctx.send(f"🛡️ **Side 2 ({phase_name})**: `{side2}`")

# ========= HELP =========
@bot.command(name="gqhelp")
async def gqhelp(ctx):
    msg = f"""
🎮 **GQ Roulette Bot Commands**
• `!phases` — Show this week's phases & which window is active (UAE).
• `!setphases Phase One | Phase Two` — **Admin only**, set both phases for the week.
• `!rerollteam [phase]` — Roll Lead + Side1 + Side2 (cooldown 5m). If no phase given, uses the active one.
• `!rerolllead [phase]` — Reroll Lead only (cooldown 5m).
• `!rerollside1 [phase]` — Reroll Side 1 only (cooldown 5m).
• `!rerollside2 [phase]` — Reroll Side 2 only (cooldown 5m).
• `!submitp1 <score>` — Save Phase 1 score for the **current week**.
• `!submitp2 <score>` — Save Phase 2 score for the **current week**.
• `!myscore` — Show your scores for the **current week**.
• `!leaderboard` — Top totals for the **current week**.

🕒 Windows (UAE):
• Phase 1: Mon 19:00 → Thu 19:00
• Phase 2: Thu 19:00 → Sun 19:00
"""
    await ctx.send(msg)

# ========= RUN =========
if not TOKEN:
    raise SystemExit("Environment variable DISCORD_BOT_TOKEN is not set.")
bot.run(TOKEN)
