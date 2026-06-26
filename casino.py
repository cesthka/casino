"""
================================================================================
  DISCORD CASINO BOT — image-based, fully interactive (virtual currency only)
--------------------------------------------------------------------------------
  Flow for EVERY game:  &game  ->  "Place your bet" screen (buttons + modal)
                        ->  Play  ->  generated game IMAGE + control buttons
                        ->  image updates on each action  ->  result image.
--------------------------------------------------------------------------------
  Games : Mines · Crash · Dice · Limbo · Plinko · Wheel · Slots · Keno
          Diamonds · Cases · Coinflip · Hilo · Dragon Tower · Chicken · Pump
          Blackjack · Roulette · Baccarat · Video Poker
  Economy: balance · daily · work · give · leaderboard · shop · admin
--------------------------------------------------------------------------------
  Deps  : discord.py 2.x  +  Pillow      (pip install -U discord.py Pillow)
  Run   : set DISCORD_TOKEN, then  python casino_bot.py
          Optional env: CASINO_PREFIX (default "&"), CASINO_DB (default casino.db)
================================================================================
"""

import os
import math
import random
import asyncio
import sqlite3
import datetime
import urllib.request
import re
from io import BytesIO

import discord
from discord.ext import commands

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    PIL_OK = True
except ImportError:
    PIL_OK = False

# ==============================================================================
#  CONFIG
# ==============================================================================

TOKEN = os.environ.get("DISCORD_TOKEN", "PASTE_YOUR_TOKEN_HERE")
PREFIX = os.environ.get("CASINO_PREFIX", "&")
DB_PATH = os.environ.get("CASINO_DB", "casino.db")

# Bot owners (full control, anywhere — even without server admin perms).
# Set them on Railway with the variable CASINO_OWNERS (comma/space separated IDs),
# e.g.  CASINO_OWNERS = 142365250803466240, 987654321012345678
# You can also hardcode IDs in the list below if you prefer.
OWNER_IDS_HARDCODED = []


def _parse_ids(raw):
    out = set()
    for part in re.split(r"[,\s;]+", raw or ""):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


OWNER_IDS = set(OWNER_IDS_HARDCODED) | _parse_ids(os.environ.get("CASINO_OWNERS", ""))

CURRENCY = "chips"
SYMBOL = "🪙"
STARTING_BALANCE = 1000
MIN_BET = 1
DEFAULT_BET = 100

DAILY_AMOUNT = 1000
DAILY_STREAK_BONUS = 250
DAILY_STREAK_MAX = 7
WORK_MIN, WORK_MAX = 50, 350
WORK_COOLDOWN = 600
DAILY_COOLDOWN = 86400

HOUSE_EDGE = 0.01

C_WIN = discord.Color.green()
C_LOSE = discord.Color.red()
C_INFO = discord.Color.blurple()
C_GOLD = discord.Color.gold()
C_GREY = discord.Color.dark_grey()

# Per-game accent color (R,G,B) + icon
THEMES = {
    "mines":     ((39, 174, 96),  "💎"),
    "crash":     ((231, 76, 60),  "🚀"),
    "dice":      ((52, 152, 219), "🎲"),
    "limbo":     ((155, 89, 182), "🚀"),
    "plinko":    ((241, 196, 15), "🟡"),
    "wheel":     ((26, 188, 156), "🎡"),
    "slots":     ((230, 126, 34), "🎰"),
    "keno":      ((52, 152, 219), "🎱"),
    "diamonds":  ((155, 89, 182), "💎"),
    "case":      ((243, 156, 18), "📦"),
    "coinflip":  ((241, 196, 15), "🪙"),
    "hilo":      ((39, 174, 96),  "🃏"),
    "dragon":    ((211, 84, 0),   "🐉"),
    "chicken":   ((243, 156, 18), "🐔"),
    "pump":      ((231, 76, 60),  "🎈"),
    "blackjack": ((192, 57, 43),  "🃏"),
    "roulette":  ((192, 57, 43),  "🎡"),
    "baccarat":  ((142, 68, 173), "🀄"),
    "videopoker":((41, 128, 185), "🎴"),
}

# ==============================================================================
#  DATABASE  /  ECONOMY
# ==============================================================================

def db():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = db()
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER NOT NULL DEFAULT 0,
        last_daily INTEGER NOT NULL DEFAULT 0,
        last_work INTEGER NOT NULL DEFAULT 0,
        streak INTEGER NOT NULL DEFAULT 0,
        wagered INTEGER NOT NULL DEFAULT 0,
        won INTEGER NOT NULL DEFAULT 0
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS shop (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price INTEGER NOT NULL,
        role_id INTEGER,
        description TEXT
    )""")
    conn.commit(); conn.close()


def ensure_user(uid):
    conn = db()
    if conn.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone() is None:
        conn.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (uid, STARTING_BALANCE))
        conn.commit()
    conn.close()


def get_user(uid):
    ensure_user(uid)
    conn = db()
    row = conn.execute("SELECT user_id, balance, last_daily, last_work, streak, wagered, won "
                       "FROM users WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    return dict(zip(("user_id", "balance", "last_daily", "last_work", "streak", "wagered", "won"), row))


def get_balance(uid):
    return get_user(uid)["balance"]


def set_balance(uid, value):
    ensure_user(uid)
    conn = db(); conn.execute("UPDATE users SET balance=? WHERE user_id=?", (max(0, int(value)), uid))
    conn.commit(); conn.close()


def add_balance(uid, delta):
    ensure_user(uid)
    conn = db()
    conn.execute("UPDATE users SET balance = MAX(0, balance + ?) WHERE user_id=?", (int(delta), uid))
    bal = conn.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()[0]
    conn.commit(); conn.close()
    return bal


def add_stats(uid, wagered=0, won=0):
    ensure_user(uid)
    conn = db()
    conn.execute("UPDATE users SET wagered = wagered + ?, won = won + ? WHERE user_id=?",
                 (int(wagered), int(won), uid))
    conn.commit(); conn.close()


def set_cooldown(uid, field, ts, streak=None):
    ensure_user(uid)
    conn = db()
    if streak is None:
        conn.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (ts, uid))
    else:
        conn.execute(f"UPDATE users SET {field}=?, streak=? WHERE user_id=?", (ts, streak, uid))
    conn.commit(); conn.close()


def top_balances(limit=10):
    conn = db()
    rows = conn.execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,)).fetchall()
    conn.close(); return rows


def shop_list():
    conn = db()
    rows = conn.execute("SELECT item_id, name, price, role_id, description FROM shop ORDER BY price ASC").fetchall()
    conn.close(); return rows


def shop_add(name, price, role_id, description):
    conn = db()
    conn.execute("INSERT INTO shop (name, price, role_id, description) VALUES (?,?,?,?)",
                 (name, price, role_id, description))
    conn.commit(); conn.close()


def shop_get(item_id):
    conn = db()
    row = conn.execute("SELECT item_id, name, price, role_id, description FROM shop WHERE item_id=?",
                       (item_id,)).fetchone()
    conn.close(); return row


def shop_del(item_id):
    conn = db(); cur = conn.execute("DELETE FROM shop WHERE item_id=?", (item_id,))
    conn.commit(); n = cur.rowcount; conn.close(); return n


init_db()

# ==============================================================================
#  HELPERS
# ==============================================================================

def now_ts():
    return int(datetime.datetime.now(datetime.timezone.utc).timestamp())


def fmt(n):
    return f"{int(n):,}".replace(",", " ")


def money(n):
    return f"**{fmt(n)}** {SYMBOL}"


def parse_bet(arg, balance):
    if arg is None:
        return None
    a = str(arg).strip().lower().replace(",", "").replace(" ", "")
    if a in ("all", "max", "allin", "all-in"):
        return balance if balance > 0 else None
    if a in ("half", "h"):
        return balance // 2 if balance >= 2 else None
    if a.endswith("%"):
        try:
            return max(1, int(balance * float(a[:-1]) / 100)) if balance > 0 else None
        except ValueError:
            return None
    mult = 1
    if a and a[-1] in "kmb":
        mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[a[-1]]
        a = a[:-1]
    try:
        val = int(float(a) * mult)
    except ValueError:
        return None
    return val if val > 0 else None


async def resolve_member(ctx, ref):
    if ref is None:
        return ctx.author
    import re
    s = str(ref).strip()
    m = re.match(r"^<@!?(\d+)>$", s)
    uid = int(m.group(1)) if m else (int(s) if s.isdigit() else None)
    if uid is not None:
        if ctx.guild:
            mem = ctx.guild.get_member(uid)
            if mem:
                return mem
        try:
            return await bot.fetch_user(uid)
        except Exception:
            return None
    if ctx.guild:
        low = s.lower().lstrip("@")
        for mm in ctx.guild.members:
            if mm.name.lower() == low or mm.display_name.lower() == low:
                return mm
    return None


# --- Cards ---
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["♠", "♥", "♦", "♣"]
RED_SUITS = ("♥", "♦")


def fresh_deck():
    deck = [(r, s) for s in SUITS for r in RANKS]
    random.shuffle(deck)
    return deck


def card_str(c):
    return f"{c[0]}{c[1]}"


def bj_value(cards):
    total, aces = 0, 0
    for r, _ in cards:
        if r == "A":
            total += 11; aces += 1
        elif r in ("K", "Q", "J", "10"):
            total += 10
        else:
            total += int(r)
    while total > 21 and aces:
        total -= 10; aces -= 1
    return total


# ==============================================================================
#  FONTS + IMAGE ENGINE
# ==============================================================================

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONT_URLS = {
    "Poppins-ExtraBold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-ExtraBold.ttf",
    "Poppins-Bold.ttf":      "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Bold.ttf",
    "Poppins-SemiBold.ttf":  "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-SemiBold.ttf",
    "Poppins-Medium.ttf":    "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Medium.ttf",
    "Poppins-Regular.ttf":   "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Regular.ttf",
}
_SYS = {
    "ExtraBold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "Bold":      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "SemiBold":  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "Medium":    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "Regular":   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
}
_FONT_CACHE = {}


def ensure_fonts():
    if not PIL_OK:
        return
    try:
        os.makedirs(FONTS_DIR, exist_ok=True)
    except Exception:
        return
    for name, url in FONT_URLS.items():
        path = os.path.join(FONTS_DIR, name)
        if os.path.exists(path):
            continue
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                data = r.read()
            with open(path, "wb") as f:
                f.write(data)
        except Exception:
            pass


def F(size, weight="Regular"):
    key = (size, weight)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    font = None
    path = os.path.join(FONTS_DIR, f"Poppins-{weight}.ttf")
    if os.path.exists(path):
        try:
            font = ImageFont.truetype(path, size)
        except Exception:
            font = None
    if font is None:
        try:
            font = ImageFont.truetype(_SYS.get(weight, _SYS["Regular"]), size)
        except Exception:
            font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


W, H = 880, 500
WHITE = (255, 255, 255)
GREY = (170, 178, 190)


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _gradient(w, h, c1, c2):
    base = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(base)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=_mix(c1, c2, y / max(1, h - 1)))
    return base


def _fit(d, text, font, maxw):
    if d.textlength(text, font=font) <= maxw:
        return text
    while text and d.textlength(text + "…", font=font) > maxw:
        text = text[:-1]
    return text + "…"


def base_canvas(theme, title):
    """Common header/footer frame. Returns (img, draw). Center area is (40,96)-(W-40,H-86)."""
    accent = theme
    img = _gradient(W, H, _mix(accent, (20, 20, 26), 0.82), (10, 10, 14))
    d = ImageDraw.Draw(img)
    # top accent bar
    d.rectangle([0, 0, W, 6], fill=accent)
    # title (strip emoji glyphs that the font can't render)
    title = "".join(c for c in title if ord(c) < 0x2190).strip()
    d.text((38, 26), title, font=F(34, "ExtraBold"), fill=WHITE)
    # center panel
    d.rounded_rectangle([34, 92, W - 34, H - 88], radius=22, fill=(0, 0, 0, 0),
                        outline=_mix(accent, (255, 255, 255), 0.1), width=2)
    return img, d


def draw_footer(d, accent, bet, balance, status):
    y = H - 70
    d.line([(40, y), (W - 40, y)], fill=(60, 64, 72), width=1)
    d.text((40, y + 12), f"Bet  {fmt(bet)}", font=F(22, "SemiBold"), fill=WHITE)
    bal_txt = f"Balance  {fmt(balance)}"
    d.text((W - 40 - d.textlength(bal_txt, font=F(22, "SemiBold")), y + 12),
           bal_txt, font=F(22, "SemiBold"), fill=GREY)
    if status:
        d.text((W // 2, 70), status, font=F(20, "Medium"), fill=accent, anchor="mm")


def img_file(img, name="game.png"):
    buf = BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return discord.File(buf, filename=name)


def game_embed(title, color, name="game.png"):
    e = discord.Embed(color=color)
    e.set_image(url=f"attachment://{name}")
    return e


# Big centered multiplier / value readout used by many games
def draw_big(d, x, y, w, h, big_text, accent, sub=None):
    d.text((x + w / 2, y + h / 2 - (16 if sub else 0)), big_text,
           font=F(86, "ExtraBold"), fill=accent, anchor="mm")
    if sub:
        d.text((x + w / 2, y + h / 2 + 56), sub, font=F(24, "Medium"), fill=GREY, anchor="mm")


def draw_card(d, x, y, w, h, card, face_up=True):
    d.rounded_rectangle([x, y, x + w, y + h], radius=12, fill=(245, 246, 248) if face_up else (40, 52, 88),
                        outline=(20, 20, 24), width=2)
    if not face_up:
        d.rounded_rectangle([x + 8, y + 8, x + w - 8, y + h - 8], radius=8,
                            fill=(28, 38, 70), outline=(90, 110, 170), width=2)
        for off in range(-h, w, 14):
            d.line([(x + 10 + off, y + h - 10), (x + 10 + off + h, y + 10)], fill=(60, 80, 140), width=2)
        return
    rank, suit = card
    col = (200, 40, 40) if suit in RED_SUITS else (20, 20, 24)
    d.text((x + 10, y + 6), rank, font=F(int(h * 0.26), "Bold"), fill=col)
    d.text((x + w / 2, y + h / 2 + 6), suit, font=F(int(h * 0.42), "Bold"), fill=col, anchor="mm")


def result_status(delta, payout):
    if delta > 0:
        return f"✅ WON +{fmt(delta)}  (returned {fmt(payout)})"
    if delta == 0:
        return "➖ PUSH — bet returned"
    return f"❌ LOST {fmt(-delta)}"


# ==============================================================================
#  BOT + BASE VIEWS
# ==============================================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)


def is_owner_id(uid):
    return uid in OWNER_IDS


def owner_or_admin():
    """Passes if the user is a bot owner OR has server administrator permission.
    Otherwise fails silently (the bot does not react at all)."""
    async def predicate(ctx):
        if is_owner_id(ctx.author.id):
            return True
        perms = getattr(ctx.author, "guild_permissions", None)
        if perms is not None and perms.administrator:
            return True
        raise commands.CheckFailure("no_access")
    return commands.check(predicate)


def owner_only():
    """Passes only for bot owners. Otherwise fails silently."""
    async def predicate(ctx):
        if is_owner_id(ctx.author.id):
            return True
        raise commands.CheckFailure("no_access")
    return commands.check(predicate)


class OwnerView(discord.ui.View):
    """Only the player who launched the game can press the buttons."""
    def __init__(self, author, timeout=180):
        super().__init__(timeout=timeout)
        self.author = author
        self.message = None

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("This isn't your game 🙂", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


def settle(uid, payout):
    if payout > 0:
        add_balance(uid, payout)
        add_stats(uid, won=payout)


# ==============================================================================
#  BET-SETUP FLOW  (the "place your bet" screen shown before every game)
# ==============================================================================

# Filled in PART 2+ : maps game key -> async launcher(interaction, author, bet)
GAME_LAUNCHERS = {}


def bet_image(theme, gname, bet, balance):
    img, d = base_canvas(theme, gname)
    cx, cy = W / 2, (96 + (H - 88)) / 2
    d.text((cx, cy - 70), "PLACE YOUR BET", font=F(30, "SemiBold"), fill=GREY, anchor="mm")
    d.text((cx, cy + 6), f"{fmt(bet)}", font=F(76, "ExtraBold"), fill=theme, anchor="mm")
    d.text((cx, cy + 70), "Adjust below, then press Play", font=F(22, "Medium"), fill=GREY, anchor="mm")
    draw_footer(d, theme, bet, balance, None)
    return img


class CustomBetModal(discord.ui.Modal, title="Custom bet"):
    value = discord.ui.TextInput(label="Amount", placeholder="e.g. 250, 1k, 50%, all", max_length=20)

    def __init__(self, view):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction):
        bal = get_balance(self.view_ref.author.id)
        v = parse_bet(str(self.value), bal)
        if v is None:
            await interaction.response.send_message("Invalid amount.", ephemeral=True); return
        self.view_ref.bet = max(MIN_BET, min(v, max(MIN_BET, bal)))
        await self.view_ref.refresh(interaction)


class BetSetupView(OwnerView):
    def __init__(self, author, game_key, bet=DEFAULT_BET):
        super().__init__(author, timeout=120)
        self.game_key = game_key
        bal = get_balance(author.id)
        self.bet = max(MIN_BET, min(bet, max(MIN_BET, bal)))

    def _clamp(self):
        bal = get_balance(self.author.id)
        self.bet = max(MIN_BET, min(self.bet, max(MIN_BET, bal)))

    def render(self):
        theme = THEMES[self.game_key][0]
        gname = f"{THEMES[self.game_key][1]} {self.game_key.capitalize()}"
        img = bet_image(theme, gname, self.bet, get_balance(self.author.id))
        return img_file(img), game_embed(gname, C_INFO)

    async def refresh(self, interaction):
        self._clamp()
        file, embed = self.render()
        await interaction.response.edit_message(attachments=[file], embed=embed, view=self)

    async def send(self, ctx):
        file, embed = self.render()
        self.message = await ctx.send(file=file, embed=embed, view=self)

    # row 0 : quick adjust
    @discord.ui.button(label="-100", style=discord.ButtonStyle.secondary, row=0)
    async def m100(self, i, b): self.bet -= 100; await self.refresh(i)
    @discord.ui.button(label="-10", style=discord.ButtonStyle.secondary, row=0)
    async def m10(self, i, b): self.bet -= 10; await self.refresh(i)
    @discord.ui.button(label="+10", style=discord.ButtonStyle.secondary, row=0)
    async def p10(self, i, b): self.bet += 10; await self.refresh(i)
    @discord.ui.button(label="+100", style=discord.ButtonStyle.secondary, row=0)
    async def p100(self, i, b): self.bet += 100; await self.refresh(i)

    # row 1 : multipliers
    @discord.ui.button(label="½", style=discord.ButtonStyle.secondary, row=1)
    async def half(self, i, b): self.bet = max(MIN_BET, self.bet // 2); await self.refresh(i)
    @discord.ui.button(label="2×", style=discord.ButtonStyle.secondary, row=1)
    async def dbl(self, i, b): self.bet *= 2; await self.refresh(i)
    @discord.ui.button(label="Max", style=discord.ButtonStyle.secondary, row=1)
    async def mx(self, i, b): self.bet = max(MIN_BET, get_balance(self.author.id)); await self.refresh(i)
    @discord.ui.button(label="✏️ Custom", style=discord.ButtonStyle.secondary, row=1)
    async def custom(self, i, b): await i.response.send_modal(CustomBetModal(self))

    # row 2 : play / cancel
    @discord.ui.button(label="▶ Play", style=discord.ButtonStyle.success, row=2)
    async def play(self, i, b):
        self._clamp()
        bal = get_balance(self.author.id)
        if self.bet < MIN_BET or self.bet > bal:
            await i.response.send_message(f"You only have {money(bal)}.", ephemeral=True); return
        add_balance(self.author.id, -self.bet)
        add_stats(self.author.id, wagered=self.bet)
        launcher = GAME_LAUNCHERS.get(self.game_key)
        if launcher is None:
            add_balance(self.author.id, self.bet)
            await i.response.send_message("This game isn't available.", ephemeral=True); return
        self.stop()
        await launcher(i, self.author, self.bet)

    @discord.ui.button(label="✖", style=discord.ButtonStyle.danger, row=2)
    async def cancel(self, i, b):
        for c in self.children:
            c.disabled = True
        await i.response.edit_message(content="Cancelled.", view=self)
        self.stop()


async def open_bet_setup(ctx, game_key, bet=DEFAULT_BET):
    if not PIL_OK:
        await ctx.send("⚠️ Pillow isn't installed. Run `pip install Pillow`."); return
    view = BetSetupView(ctx.author, game_key, bet)
    await view.send(ctx)


class PlayAgainView(OwnerView):
    """Shown after an instant game: replay (re-opens bet setup) or quit."""
    def __init__(self, author, game_key, bet):
        super().__init__(author, timeout=120)
        self.game_key = game_key
        self.bet = bet

    @discord.ui.button(label="🔁 Play again", style=discord.ButtonStyle.success)
    async def again(self, i, b):
        self.stop()
        view = BetSetupView(self.author, self.game_key, self.bet)
        file, embed = view.render()
        await i.response.edit_message(attachments=[file], embed=embed, view=view)
        view.message = self.message

    @discord.ui.button(label="✖", style=discord.ButtonStyle.danger)
    async def quit(self, i, b):
        for c in self.children:
            c.disabled = True
        await i.response.edit_message(view=self)
        self.stop()


# ==============================================================================
#  ECONOMY COMMANDS
# ==============================================================================

@bot.command(name="balance", aliases=["bal", "wallet", "coins", "chips"])
async def balance_cmd(ctx, *, member: str = None):
    target = await resolve_member(ctx, member)
    if target is None:
        await ctx.send("❌ User not found."); return
    u = get_user(target.id)
    e = discord.Embed(title=f"{SYMBOL} Wallet — {target.display_name}", color=C_GOLD)
    e.add_field(name="Balance", value=money(u["balance"]), inline=True)
    e.add_field(name="Total wagered", value=money(u["wagered"]), inline=True)
    e.add_field(name="Total won", value=money(u["won"]), inline=True)
    e.set_thumbnail(url=target.display_avatar.url)
    await ctx.send(embed=e)


@bot.command(name="daily")
async def daily_cmd(ctx):
    u = get_user(ctx.author.id); now = now_ts(); elapsed = now - u["last_daily"]
    if elapsed < DAILY_COOLDOWN:
        await ctx.send(f"⏳ Already claimed. Come back <t:{now + (DAILY_COOLDOWN - elapsed)}:R>."); return
    streak = u["streak"] + 1 if elapsed < 2 * DAILY_COOLDOWN else 1
    bonus = min(streak, DAILY_STREAK_MAX) * DAILY_STREAK_BONUS
    total = DAILY_AMOUNT + bonus
    add_balance(ctx.author.id, total)
    set_cooldown(ctx.author.id, "last_daily", now, streak=streak)
    e = discord.Embed(title="🎁 Daily reward", color=C_WIN, description=f"You received {money(total)}!")
    e.add_field(name="Base", value=money(DAILY_AMOUNT), inline=True)
    e.add_field(name=f"Streak x{streak}", value=money(bonus), inline=True)
    e.add_field(name="New balance", value=money(get_balance(ctx.author.id)), inline=True)
    await ctx.send(embed=e)


@bot.command(name="work", aliases=["grind"])
async def work_cmd(ctx):
    u = get_user(ctx.author.id); now = now_ts(); elapsed = now - u["last_work"]
    if elapsed < WORK_COOLDOWN:
        await ctx.send(f"⏳ You're tired. Work again <t:{now + (WORK_COOLDOWN - elapsed)}:R>."); return
    amount = random.randint(WORK_MIN, WORK_MAX)
    add_balance(ctx.author.id, amount)
    set_cooldown(ctx.author.id, "last_work", now)
    jobs = ["dealt cards", "cleaned the slot machines", "served drinks to high rollers",
            "counted the vault", "ran the roulette wheel", "valeted some cars"]
    await ctx.send(f"💼 You {random.choice(jobs)} and earned {money(amount)}. "
                   f"Balance: {money(get_balance(ctx.author.id))}.")


@bot.command(name="give", aliases=["pay", "transfer"])
async def give_cmd(ctx, member: str = None, amount: str = None):
    if member is None or amount is None:
        await ctx.send(f"Usage: `{PREFIX}give @user <amount>`"); return
    target = await resolve_member(ctx, member)
    if target is None or getattr(target, "bot", False):
        await ctx.send("❌ Invalid recipient."); return
    if target.id == ctx.author.id:
        await ctx.send("You can't pay yourself."); return
    bal = get_balance(ctx.author.id); amt = parse_bet(amount, bal)
    if amt is None or amt <= 0:
        await ctx.send("❌ Invalid amount."); return
    if amt > bal:
        await ctx.send(f"❌ Not enough {CURRENCY} (you have {money(bal)})."); return
    add_balance(ctx.author.id, -amt); add_balance(target.id, amt)
    await ctx.send(f"✅ {ctx.author.mention} gave {money(amt)} to {target.mention}.")


@bot.command(name="leaderboard", aliases=["lb", "rich"])
async def leaderboard_cmd(ctx):
    rows = top_balances(10)
    if not rows:
        await ctx.send("No players yet."); return
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = []
    for i, (uid, bal) in enumerate(rows, 1):
        m = ctx.guild.get_member(uid) if ctx.guild else None
        name = m.display_name if m else f"User {uid}"
        lines.append(f"{medals.get(i, f'**{i}.**')} {name} — {money(bal)}")
    await ctx.send(embed=discord.Embed(title="🏆 Richest players", description="\n".join(lines), color=C_GOLD))


@bot.command(name="shop", aliases=["store"])
async def shop_cmd(ctx):
    items = shop_list()
    e = discord.Embed(title="🛒 Shop", color=C_INFO,
                      description=f"Buy with `{PREFIX}buy <id>`." if items else
                      f"The shop is empty. An admin can add items with `{PREFIX}additem`.")
    for item_id, name, price, role_id, desc in items:
        role_txt = f" — grants <@&{role_id}>" if role_id else ""
        e.add_field(name=f"#{item_id} · {name} — {money(price)}", value=(desc or "—") + role_txt, inline=False)
    await ctx.send(embed=e)


@bot.command(name="buy")
async def buy_cmd(ctx, item_id: int = None):
    if item_id is None:
        await ctx.send(f"Usage: `{PREFIX}buy <id>`"); return
    item = shop_get(item_id)
    if item is None:
        await ctx.send("❌ No such item."); return
    _id, name, price, role_id, desc = item
    bal = get_balance(ctx.author.id)
    if bal < price:
        await ctx.send(f"❌ Too expensive. You have {money(bal)}, it costs {money(price)}."); return
    if role_id and ctx.guild:
        role = ctx.guild.get_role(role_id)
        if role is None:
            await ctx.send("❌ The linked role no longer exists."); return
        if role in ctx.author.roles:
            await ctx.send("You already own this item."); return
        try:
            await ctx.author.add_roles(role, reason=f"Bought shop item #{_id}")
        except discord.Forbidden:
            await ctx.send("⛔ I can't assign that role."); return
    add_balance(ctx.author.id, -price)
    await ctx.send(f"✅ You bought **{name}** for {money(price)}! Balance: {money(get_balance(ctx.author.id))}.")


@bot.command(name="additem")
@owner_or_admin()
async def additem_cmd(ctx, price: int = None, role: discord.Role = None, *, name: str = None):
    if price is None or name is None:
        await ctx.send(f"Usage: `{PREFIX}additem <price> [@role] <name>`"); return
    shop_add(name.strip(), price, role.id if role else None, None)
    await ctx.send(f"✅ Added **{name.strip()}** for {money(price)}" + (f" (grants {role.mention})." if role else "."))


@bot.command(name="delitem", aliases=["removeitem"])
@owner_or_admin()
async def delitem_cmd(ctx, item_id: int = None):
    if item_id is None:
        await ctx.send(f"Usage: `{PREFIX}delitem <id>`"); return
    await ctx.send("✅ Item removed." if shop_del(item_id) else "❌ No such item.")


@bot.command(name="addmoney", aliases=["addcoins"])
@owner_or_admin()
async def addmoney_cmd(ctx, member: str = None, amount: int = None):
    if member is None or amount is None:
        await ctx.send(f"Usage: `{PREFIX}addmoney @user <amount>`"); return
    t = await resolve_member(ctx, member)
    if t is None:
        await ctx.send("❌ User not found."); return
    add_balance(t.id, amount)
    await ctx.send(f"✅ Added {money(amount)} to {t.mention}. Balance: {money(get_balance(t.id))}.")


@bot.command(name="removemoney", aliases=["removecoins"])
@owner_or_admin()
async def removemoney_cmd(ctx, member: str = None, amount: int = None):
    if member is None or amount is None:
        await ctx.send(f"Usage: `{PREFIX}removemoney @user <amount>`"); return
    t = await resolve_member(ctx, member)
    if t is None:
        await ctx.send("❌ User not found."); return
    add_balance(t.id, -amount)
    await ctx.send(f"✅ Removed {money(amount)} from {t.mention}. Balance: {money(get_balance(t.id))}.")


@bot.command(name="setmoney", aliases=["setcoins", "setbalance"])
@owner_or_admin()
async def setmoney_cmd(ctx, member: str = None, amount: int = None):
    if member is None or amount is None:
        await ctx.send(f"Usage: `{PREFIX}setmoney @user <amount>`"); return
    t = await resolve_member(ctx, member)
    if t is None:
        await ctx.send("❌ User not found."); return
    set_balance(t.id, amount)
    await ctx.send(f"✅ {t.mention}'s balance set to {money(amount)}.")


# ---- OWNER-ONLY ----------------------------------------------------------------

@bot.command(name="resetbalance", aliases=["resetbal", "resetuser"])
@owner_or_admin()
async def resetbalance_cmd(ctx, member: str = None):
    if member is None:
        await ctx.send(f"Usage: `{PREFIX}resetbalance @user`"); return
    t = await resolve_member(ctx, member)
    if t is None:
        await ctx.send("❌ User not found."); return
    set_balance(t.id, STARTING_BALANCE)
    await ctx.send(f"✅ {t.mention} reset to {money(STARTING_BALANCE)}.")


@bot.command(name="wipeeconomy", aliases=["ecoreset", "resetall"])
@owner_only()
async def wipeeconomy_cmd(ctx, confirm: str = None):
    if confirm != "confirm":
        await ctx.send(f"⚠️ This resets **everyone's** balance to {money(STARTING_BALANCE)}.\n"
                       f"Type `{PREFIX}wipeeconomy confirm` to proceed."); return
    conn = db()
    n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.execute("UPDATE users SET balance=?, wagered=0, won=0", (STARTING_BALANCE,))
    conn.commit(); conn.close()
    await ctx.send(f"✅ Economy wiped — {n} account(s) reset to {money(STARTING_BALANCE)}.")


@bot.command(name="owners", aliases=["ownerlist"])
async def owners_cmd(ctx):
    if not OWNER_IDS:
        await ctx.send("No bot owners are configured. Set the `CASINO_OWNERS` variable on Railway."); return
    lines = [f"• <@{uid}> (`{uid}`)" for uid in OWNER_IDS]
    is_o = "✅ You are an owner." if is_owner_id(ctx.author.id) else "You are not an owner."
    await ctx.send(embed=discord.Embed(title="👑 Bot owners",
                                       description="\n".join(lines) + f"\n\n{is_o}", color=C_GOLD))


# ==============================================================================
#  INSTANT GAMES — shared result helper
# ==============================================================================

async def show_result(interaction, author, game_key, bet, img):
    """Edit the message to the result image + a Play Again view."""
    again = PlayAgainView(author, game_key, bet)
    await interaction.response.edit_message(
        attachments=[img_file(img)], embed=game_embed("", C_INFO), view=again)
    again.message = interaction.message


# ----- COINFLIP -----------------------------------------------------------------
class CoinflipView(OwnerView):
    def __init__(self, author, bet):
        super().__init__(author, timeout=120)
        self.bet = bet

    def render(self, face="?", status="Heads or Tails?"):
        theme = THEMES["coinflip"][0]
        img, d = base_canvas(theme, "Coinflip")
        cx, cy = W / 2, (96 + H - 88) / 2
        d.ellipse([cx - 70, cy - 70, cx + 70, cy + 70], fill=_mix(theme, (255, 255, 255), 0.15),
                  outline=(120, 90, 10), width=6)
        d.text((cx, cy), face, font=F(70, "ExtraBold"), fill=(60, 45, 5), anchor="mm")
        draw_footer(d, theme, self.bet, get_balance(self.author.id), status)
        return img

    async def _flip(self, interaction, side):
        result = random.choice(["heads", "tails"])
        if result == side:
            payout = int(self.bet * 2 * (1 - HOUSE_EDGE))
            settle(self.author.id, payout); delta = payout - self.bet
        else:
            payout = 0; delta = -self.bet
        face = "H" if result == "heads" else "T"
        img = self.render(face=face, status=result_status(delta, payout))
        await show_result(interaction, self.author, "coinflip", self.bet, img)
        self.stop()

    @discord.ui.button(label="Heads", emoji="🔵", style=discord.ButtonStyle.primary)
    async def heads(self, i, b): await self._flip(i, "heads")
    @discord.ui.button(label="Tails", emoji="🔴", style=discord.ButtonStyle.primary)
    async def tails(self, i, b): await self._flip(i, "tails")


async def launch_coinflip(interaction, author, bet):
    view = CoinflipView(author, bet)
    await interaction.response.edit_message(attachments=[img_file(view.render())],
                                            embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["coinflip"] = launch_coinflip


# ----- DICE ---------------------------------------------------------------------
class DiceView(OwnerView):
    def __init__(self, author, bet):
        super().__init__(author, timeout=150)
        self.bet = bet
        self.direction = "over"
        self.target = 50.0
        self.roll = None

    def _chance(self):
        return (100 - self.target) if self.direction == "over" else self.target

    def _mult(self):
        return (100 / max(0.01, self._chance())) * (1 - HOUSE_EDGE)

    def render(self, status=None):
        theme = THEMES["dice"][0]
        img, d = base_canvas(theme, "🎲 Dice")
        x, y, w = 70, 150, W - 140
        # number line
        d.rounded_rectangle([x, y, x + w, y + 26], radius=13, fill=(40, 44, 52))
        tx = x + w * (self.target / 100)
        # win zone
        if self.direction == "over":
            d.rounded_rectangle([tx, y, x + w, y + 26], radius=13, fill=_mix(theme, (255, 255, 255), 0.1))
        else:
            d.rounded_rectangle([x, y, tx, y + 26], radius=13, fill=_mix(theme, (255, 255, 255), 0.1))
        d.line([(tx, y - 12), (tx, y + 38)], fill=WHITE, width=3)
        d.text((tx, y - 26), f"{self.target:.0f}", font=F(22, "Bold"), fill=WHITE, anchor="mm")
        d.text((x, y + 44), "0", font=F(18, "Medium"), fill=GREY)
        d.text((x + w, y + 44), "100", font=F(18, "Medium"), fill=GREY, anchor="ra")
        # readout
        if self.roll is not None:
            d.text((W / 2, y + 110), f"{self.roll:.2f}", font=F(64, "ExtraBold"), fill=theme, anchor="mm")
        d.text((W / 2, y + 165),
               f"{self.direction.upper()} {self.target:.0f}   ·   {self._chance():.1f}%   ·   x{self._mult():.3f}",
               font=F(22, "SemiBold"), fill=GREY, anchor="mm")
        draw_footer(d, theme, self.bet, get_balance(self.author.id), status)
        return img

    async def _refresh(self, i):
        self.target = min(98, max(1, self.target))
        await i.response.edit_message(attachments=[img_file(self.render())],
                                      embed=game_embed("", C_INFO), view=self)

    @discord.ui.button(label="Over/Under", style=discord.ButtonStyle.secondary, row=0)
    async def flip_dir(self, i, b):
        self.direction = "under" if self.direction == "over" else "over"; await self._refresh(i)
    @discord.ui.button(label="-10", style=discord.ButtonStyle.secondary, row=0)
    async def t_m10(self, i, b): self.target -= 10; await self._refresh(i)
    @discord.ui.button(label="-1", style=discord.ButtonStyle.secondary, row=0)
    async def t_m1(self, i, b): self.target -= 1; await self._refresh(i)
    @discord.ui.button(label="+1", style=discord.ButtonStyle.secondary, row=0)
    async def t_p1(self, i, b): self.target += 1; await self._refresh(i)
    @discord.ui.button(label="+10", style=discord.ButtonStyle.secondary, row=0)
    async def t_p10(self, i, b): self.target += 10; await self._refresh(i)

    @discord.ui.button(label="🎲 Roll", style=discord.ButtonStyle.success, row=1)
    async def roll_btn(self, i, b):
        self.roll = round(random.uniform(0, 100), 2)
        win = (self.roll > self.target) if self.direction == "over" else (self.roll < self.target)
        if win:
            payout = int(self.bet * self._mult()); settle(self.author.id, payout); delta = payout - self.bet
        else:
            payout = 0; delta = -self.bet
        img = self.render(status=result_status(delta, payout))
        await show_result(i, self.author, "dice", self.bet, img)
        self.stop()


async def launch_dice(interaction, author, bet):
    view = DiceView(author, bet)
    await interaction.response.edit_message(attachments=[img_file(view.render())],
                                            embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["dice"] = launch_dice


# ----- LIMBO --------------------------------------------------------------------
class LimboView(OwnerView):
    def __init__(self, author, bet):
        super().__init__(author, timeout=150)
        self.bet = bet
        self.target = 2.0
        self.result = None

    def render(self, status=None):
        theme = THEMES["limbo"][0]
        img, d = base_canvas(theme, "🚀 Limbo")
        cx, cy = W / 2, (96 + H - 88) / 2
        if self.result is None:
            d.text((cx, cy - 30), "TARGET", font=F(26, "SemiBold"), fill=GREY, anchor="mm")
            d.text((cx, cy + 30), f"{self.target:.2f}x", font=F(80, "ExtraBold"), fill=theme, anchor="mm")
        else:
            col = theme if self.result >= self.target else (231, 76, 60)
            d.text((cx, cy - 30), f"target {self.target:.2f}x", font=F(24, "Medium"), fill=GREY, anchor="mm")
            d.text((cx, cy + 30), f"{self.result:.2f}x", font=F(86, "ExtraBold"), fill=col, anchor="mm")
        draw_footer(d, theme, self.bet, get_balance(self.author.id), status)
        return img

    async def _refresh(self, i):
        self.target = max(1.01, round(self.target, 2))
        await i.response.edit_message(attachments=[img_file(self.render())],
                                      embed=game_embed("", C_INFO), view=self)

    @discord.ui.button(label="-1", style=discord.ButtonStyle.secondary, row=0)
    async def m1(self, i, b): self.target -= 1; await self._refresh(i)
    @discord.ui.button(label="-0.1", style=discord.ButtonStyle.secondary, row=0)
    async def m01(self, i, b): self.target -= 0.1; await self._refresh(i)
    @discord.ui.button(label="+0.1", style=discord.ButtonStyle.secondary, row=0)
    async def p01(self, i, b): self.target += 0.1; await self._refresh(i)
    @discord.ui.button(label="+1", style=discord.ButtonStyle.secondary, row=0)
    async def p1(self, i, b): self.target += 1; await self._refresh(i)

    @discord.ui.button(label="🚀 Play", style=discord.ButtonStyle.success, row=1)
    async def play(self, i, b):
        u = random.random()
        self.result = round(max(1.0, (1 - HOUSE_EDGE) / u) if u > 0 else 1e6, 2)
        if self.result >= self.target:
            payout = int(self.bet * self.target); settle(self.author.id, payout); delta = payout - self.bet
        else:
            payout = 0; delta = -self.bet
        img = self.render(status=result_status(delta, payout))
        await show_result(i, self.author, "limbo", self.bet, img)
        self.stop()


async def launch_limbo(interaction, author, bet):
    view = LimboView(author, bet)
    await interaction.response.edit_message(attachments=[img_file(view.render())],
                                            embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["limbo"] = launch_limbo


# ----- WHEEL --------------------------------------------------------------------
WHEEL_SEGMENTS = {
    "low":    [1.5, 1.2, 1.2, 1.2, 0, 1.2, 1.5, 1.2, 1.2, 1.2, 0, 1.2, 1.5, 1.2, 1.2, 1.2],
    "medium": [0, 1.9, 0, 1.5, 0, 2, 0, 1.5, 0, 3, 0, 1.5, 0, 2, 0, 1.8],
    "high":   [0, 0, 0, 0, 0, 0, 0, 9.9, 0, 0, 0, 0, 0, 0, 0, 19.8],
}


class WheelView(OwnerView):
    def __init__(self, author, bet):
        super().__init__(author, timeout=150)
        self.bet = bet
        self.risk = "medium"
        self.angle = 0.0
        self.landed = None

    def render(self, status=None):
        theme = THEMES["wheel"][0]
        img, d = base_canvas(theme, "🎡 Wheel")
        seg = WHEEL_SEGMENTS[self.risk]
        n = len(seg)
        cx, cy, r = W / 2, (96 + H - 88) / 2 + 6, 130
        for k in range(n):
            a0 = self.angle + k * 360 / n
            a1 = self.angle + (k + 1) * 360 / n
            mult = seg[k]
            col = _mix(theme, (10, 10, 14), 0.7) if mult == 0 else _mix(theme, (255, 255, 255), min(0.6, mult / 6))
            d.pieslice([cx - r, cy - r, cx + r, cy + r], a0, a1, fill=col, outline=(15, 15, 18))
        d.ellipse([cx - 34, cy - 34, cx + 34, cy + 34], fill=(20, 22, 26), outline=theme, width=3)
        if self.landed is not None:
            d.text((cx, cy), f"{self.landed:g}x", font=F(28, "ExtraBold"), fill=theme, anchor="mm")
        else:
            d.text((cx, cy), self.risk[:3].upper(), font=F(24, "Bold"), fill=GREY, anchor="mm")
        # pointer
        d.polygon([(cx, cy - r - 18), (cx - 14, cy - r + 4), (cx + 14, cy - r + 4)], fill=WHITE)
        draw_footer(d, theme, self.bet, get_balance(self.author.id), status)
        return img

    async def _refresh(self, i):
        await i.response.edit_message(attachments=[img_file(self.render())],
                                      embed=game_embed("", C_INFO), view=self)

    @discord.ui.button(label="Low", style=discord.ButtonStyle.secondary, row=0)
    async def low(self, i, b): self.risk = "low"; await self._refresh(i)
    @discord.ui.button(label="Medium", style=discord.ButtonStyle.secondary, row=0)
    async def med(self, i, b): self.risk = "medium"; await self._refresh(i)
    @discord.ui.button(label="High", style=discord.ButtonStyle.secondary, row=0)
    async def high(self, i, b): self.risk = "high"; await self._refresh(i)

    @discord.ui.button(label="🎡 Spin", style=discord.ButtonStyle.success, row=1)
    async def spin(self, i, b):
        seg = WHEEL_SEGMENTS[self.risk]
        idx = random.randrange(len(seg))
        self.landed = seg[idx]
        self.angle = (-(idx + 0.5) * 360 / len(seg)) - 90 + random.uniform(-3, 3)
        payout = int(self.bet * self.landed); settle(self.author.id, payout); delta = payout - self.bet
        img = self.render(status=result_status(delta, payout))
        await show_result(i, self.author, "wheel", self.bet, img)
        self.stop()


async def launch_wheel(interaction, author, bet):
    view = WheelView(author, bet)
    await interaction.response.edit_message(attachments=[img_file(view.render())],
                                            embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["wheel"] = launch_wheel


# ----- SLOTS --------------------------------------------------------------------
SLOT_SYMBOLS = [("🍒", 28), ("🍋", 24), ("🍇", 18), ("🔔", 14), ("⭐", 9), ("💎", 5), ("7️⃣", 2)]
SLOT_TRIPLE = {"🍒": 5, "🍋": 8, "🍇": 12, "🔔": 18, "⭐": 30, "💎": 60, "7️⃣": 150}
SLOT_DISPLAY = {
    "🍒": ("C", (231, 76, 60)), "🍋": ("L", (241, 196, 15)), "🍇": ("G", (155, 89, 182)),
    "🔔": ("B", (243, 156, 18)), "⭐": ("★", (241, 196, 15)), "💎": ("◆", (52, 152, 219)),
    "7️⃣": ("7", (231, 76, 60)),
}


class SlotsView(OwnerView):
    def __init__(self, author, bet):
        super().__init__(author, timeout=120)
        self.bet = bet
        self.reels = ["❔", "❔", "❔"]

    def render(self, status="Press Spin!"):
        theme = THEMES["slots"][0]
        img, d = base_canvas(theme, "Slots")
        cx, cy = W / 2, (96 + H - 88) / 2
        bw, gap = 120, 22
        total = bw * 3 + gap * 2
        x0 = cx - total / 2
        for k in range(3):
            x = x0 + k * (bw + gap)
            d.rounded_rectangle([x, cy - 70, x + bw, cy + 70], radius=16, fill=(245, 246, 248),
                                outline=theme, width=4)
            glyph, col = SLOT_DISPLAY.get(self.reels[k], ("?", (120, 120, 120)))
            d.text((x + bw / 2, cy), glyph, font=F(70, "ExtraBold"), fill=col, anchor="mm")
        draw_footer(d, theme, self.bet, get_balance(self.author.id), status)
        return img

    @discord.ui.button(label="🎰 Spin", style=discord.ButtonStyle.success)
    async def spin(self, i, b):
        syms = [s for s, _ in SLOT_SYMBOLS]; weights = [w for _, w in SLOT_SYMBOLS]
        self.reels = random.choices(syms, weights=weights, k=3)
        if self.reels[0] == self.reels[1] == self.reels[2]:
            mult = SLOT_TRIPLE[self.reels[0]]
        elif self.reels.count("🍒") == 2:
            mult = 2
        elif self.reels.count("🍒") == 1:
            mult = 1
        else:
            mult = 0
        payout = int(self.bet * mult); settle(self.author.id, payout); delta = payout - self.bet
        img = self.render(status=f"x{mult}   ·   " + result_status(delta, payout))
        await show_result(i, self.author, "slots", self.bet, img)
        self.stop()


async def launch_slots(interaction, author, bet):
    view = SlotsView(author, bet)
    await interaction.response.edit_message(attachments=[img_file(view.render())],
                                            embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["slots"] = launch_slots


# ----- PLINKO -------------------------------------------------------------------
PLINKO_TABLES = {
    8:  {"low":   [5.6, 2.1, 1.1, 1.0, 0.5, 1.0, 1.1, 2.1, 5.6],
         "medium":[13, 3, 1.3, 0.7, 0.4, 0.7, 1.3, 3, 13],
         "high":  [29, 4, 1.5, 0.3, 0.2, 0.3, 1.5, 4, 29]},
    12: {"low":   [10, 3, 1.6, 1.4, 1.1, 1.0, 0.5, 1.0, 1.1, 1.4, 1.6, 3, 10],
         "medium":[24, 5, 3, 1.6, 0.9, 0.7, 0.5, 0.7, 0.9, 1.6, 3, 5, 24],
         "high":  [58, 8, 3, 1.4, 0.5, 0.2, 0.2, 0.2, 0.5, 1.4, 3, 8, 58]},
    16: {"low":   [16, 9, 2, 1.4, 1.4, 1.2, 1.1, 1.0, 0.5, 1.0, 1.1, 1.2, 1.4, 1.4, 2, 9, 16],
         "medium":[110, 41, 10, 5, 3, 1.5, 1.0, 0.5, 0.3, 0.5, 1.0, 1.5, 3, 5, 10, 41, 110],
         "high":  [1000, 130, 26, 9, 4, 2, 0.2, 0.2, 0.2, 0.2, 0.2, 2, 4, 9, 26, 130, 1000]},
}


class PlinkoView(OwnerView):
    def __init__(self, author, bet):
        super().__init__(author, timeout=150)
        self.bet = bet
        self.risk = "medium"
        self.rows = 12
        self.landed = None

    def render(self, status=None):
        theme = THEMES["plinko"][0]
        img, d = base_canvas(theme, "🟡 Plinko")
        table = PLINKO_TABLES[self.rows][self.risk]
        n = len(table)
        x0, x1, ytop = 90, W - 90, 120
        ybot = H - 150
        # pegs
        for row in range(self.rows):
            count = row + 2
            yy = ytop + (ybot - ytop) * row / max(1, self.rows)
            spanw = (x1 - x0) * (count) / (n + 1)
            sx = (W - spanw) / 2
            for c in range(count):
                px = sx + spanw * c / max(1, count - 1)
                d.ellipse([px - 3, yy - 3, px + 3, yy + 3], fill=(120, 126, 138))
        # buckets
        bw = (x1 - x0) / n
        for k in range(n):
            bx = x0 + k * bw
            mult = table[k]
            col = _mix(theme, (10, 10, 14), 0.7) if mult < 1 else _mix(theme, (255, 80, 60), min(0.8, mult / 30))
            if self.landed == k:
                col = (255, 255, 255)
            d.rounded_rectangle([bx + 2, ybot + 8, bx + bw - 2, ybot + 40], radius=6, fill=col)
            d.text((bx + bw / 2, ybot + 24), f"{mult:g}",
                   font=F(13, "Bold"), fill=(20, 20, 24) if self.landed == k else WHITE, anchor="mm")
        d.text((W / 2, 96 + 4), f"risk {self.risk} · {self.rows} rows",
               font=F(18, "Medium"), fill=GREY, anchor="mm")
        draw_footer(d, theme, self.bet, get_balance(self.author.id), status)
        return img

    async def _refresh(self, i):
        await i.response.edit_message(attachments=[img_file(self.render())],
                                      embed=game_embed("", C_INFO), view=self)

    @discord.ui.button(label="Low", style=discord.ButtonStyle.secondary, row=0)
    async def low(self, i, b): self.risk = "low"; await self._refresh(i)
    @discord.ui.button(label="Med", style=discord.ButtonStyle.secondary, row=0)
    async def med(self, i, b): self.risk = "medium"; await self._refresh(i)
    @discord.ui.button(label="High", style=discord.ButtonStyle.secondary, row=0)
    async def high(self, i, b): self.risk = "high"; await self._refresh(i)
    @discord.ui.button(label="Rows 8/12/16", style=discord.ButtonStyle.secondary, row=0)
    async def rows_btn(self, i, b):
        self.rows = {8: 12, 12: 16, 16: 8}[self.rows]; await self._refresh(i)

    @discord.ui.button(label="🟡 Drop", style=discord.ButtonStyle.success, row=1)
    async def drop(self, i, b):
        rights = sum(1 for _ in range(self.rows) if random.random() < 0.5)
        self.landed = rights
        mult = PLINKO_TABLES[self.rows][self.risk][rights]
        payout = int(self.bet * mult); settle(self.author.id, payout); delta = payout - self.bet
        img = self.render(status=f"x{mult:g}   ·   " + result_status(delta, payout))
        await show_result(i, self.author, "plinko", self.bet, img)
        self.stop()


async def launch_plinko(interaction, author, bet):
    view = PlinkoView(author, bet)
    await interaction.response.edit_message(attachments=[img_file(view.render())],
                                            embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["plinko"] = launch_plinko


# ----- DIAMONDS -----------------------------------------------------------------
DIAMOND_GEMS = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "⚪"]
GEM_RGB = {"🔴": (231, 76, 60), "🟠": (230, 126, 34), "🟡": (241, 196, 15), "🟢": (46, 204, 113),
           "🔵": (52, 152, 219), "🟣": (155, 89, 182), "⚪": (236, 240, 241)}


class DiamondsView(OwnerView):
    def __init__(self, author, bet):
        super().__init__(author, timeout=120)
        self.bet = bet
        self.draw = None

    def render(self, status="Press Reveal!"):
        theme = THEMES["diamonds"][0]
        img, d = base_canvas(theme, "💎 Diamonds")
        cy = (96 + H - 88) / 2
        gems = self.draw or ["⚪"] * 5
        gap, gw = 26, 86
        total = gw * 5 + gap * 4
        x0 = W / 2 - total / 2
        for k in range(5):
            x = x0 + k * (gw + gap)
            col = GEM_RGB.get(gems[k], (120, 120, 120)) if self.draw else (60, 64, 72)
            d.polygon([(x + gw / 2, cy - 44), (x + gw, cy), (x + gw / 2, cy + 44), (x, cy)],
                      fill=col, outline=(15, 15, 18))
        draw_footer(d, theme, self.bet, get_balance(self.author.id), status)
        return img

    @discord.ui.button(label="💎 Reveal", style=discord.ButtonStyle.success)
    async def reveal(self, i, b):
        self.draw = [random.choice(DIAMOND_GEMS) for _ in range(5)]
        counts = sorted((self.draw.count(g) for g in set(self.draw)), reverse=True)
        if counts[0] == 5:
            mult, lab = 60, "FIVE OF A KIND"
        elif counts[0] == 4:
            mult, lab = 18, "Four of a kind"
        elif counts[0] == 3 and len(counts) > 1 and counts[1] == 2:
            mult, lab = 12, "Full house"
        elif counts[0] == 3:
            mult, lab = 3, "Three of a kind"
        elif counts[0] == 2 and len(counts) > 1 and counts[1] == 2:
            mult, lab = 1.6, "Two pair"
        elif counts[0] == 2:
            mult, lab = 0.5, "One pair"
        else:
            mult, lab = 0, "No match"
        payout = int(self.bet * mult); settle(self.author.id, payout); delta = payout - self.bet
        img = self.render(status=f"{lab} (x{mult})   ·   " + result_status(delta, payout))
        await show_result(i, self.author, "diamonds", self.bet, img)
        self.stop()


async def launch_diamonds(interaction, author, bet):
    view = DiamondsView(author, bet)
    await interaction.response.edit_message(attachments=[img_file(view.render())],
                                            embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["diamonds"] = launch_diamonds


# ----- CASE ---------------------------------------------------------------------
CASE_REWARDS = [(0.0, 35), (0.4, 22), (0.8, 14), (1.2, 10), (1.6, 7),
                (2.5, 5), (4.0, 3), (8.0, 2), (20.0, 1), (75.0, 0.4)]


class CaseView(OwnerView):
    def __init__(self, author, bet):
        super().__init__(author, timeout=120)
        self.bet = bet
        self.reward = None

    def render(self, status="Press Open!"):
        theme = THEMES["case"][0]
        img, d = base_canvas(theme, "📦 Cases")
        cx, cy = W / 2, (96 + H - 88) / 2
        d.rounded_rectangle([cx - 80, cy - 60, cx + 80, cy + 60], radius=14,
                            fill=_mix(theme, (40, 30, 10), 0.5), outline=theme, width=4)
        if self.reward is None:
            d.line([(cx - 80, cy - 18), (cx + 80, cy - 18)], fill=theme, width=4)
            d.rounded_rectangle([cx - 22, cy - 30, cx + 22, cy - 6], radius=6, fill=theme)
            d.text((cx, cy + 26), "CASE", font=F(28, "ExtraBold"), fill=WHITE, anchor="mm")
        else:
            d.text((cx, cy), f"{self.reward:g}x", font=F(54, "ExtraBold"), fill=theme, anchor="mm")
        draw_footer(d, theme, self.bet, get_balance(self.author.id), status)
        return img

    @discord.ui.button(label="📦 Open", style=discord.ButtonStyle.success)
    async def open_case(self, i, b):
        mults = [m for m, _ in CASE_REWARDS]; weights = [w for _, w in CASE_REWARDS]
        self.reward = random.choices(mults, weights=weights, k=1)[0]
        payout = int(self.bet * self.reward); settle(self.author.id, payout); delta = payout - self.bet
        img = self.render(status=result_status(delta, payout))
        await show_result(i, self.author, "case", self.bet, img)
        self.stop()


async def launch_case(interaction, author, bet):
    view = CaseView(author, bet)
    await interaction.response.edit_message(attachments=[img_file(view.render())],
                                            embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["case"] = launch_case


# ----- KENO ---------------------------------------------------------------------
KENO_TABLE = {
    5:  [0, 0.25, 1.4, 4.1, 16.5, 36],
    8:  [0, 0, 0, 2.2, 4, 13, 22, 55, 70],
    10: [0, 0, 0, 1.4, 2.25, 4.5, 8, 17, 50, 80, 100],
}


class KenoView(OwnerView):
    def __init__(self, author, bet):
        super().__init__(author, timeout=150)
        self.bet = bet
        self.spots = 8
        self.picks = sorted(random.sample(range(1, 41), self.spots))
        self.drawn = None

    def render(self, status=None):
        theme = THEMES["keno"][0]
        img, d = base_canvas(theme, "🎱 Keno")
        cols = 10
        gx, gy = 90, 130
        cw, ch = (W - 180) / cols, 56
        for n in range(1, 41):
            r, c = (n - 1) // cols, (n - 1) % cols
            x, y = gx + c * cw, gy + r * ch
            picked = n in self.picks
            hit = self.drawn is not None and n in self.drawn
            if hit and picked:
                fill, tcol = theme, (10, 10, 14)
            elif hit:
                fill, tcol = _mix(theme, (10, 10, 14), 0.55), WHITE
            elif picked:
                fill, tcol = _mix(theme, (255, 255, 255), 0.12), WHITE
            else:
                fill, tcol = (38, 42, 50), GREY
            d.rounded_rectangle([x + 3, y + 3, x + cw - 3, y + ch - 3], radius=8, fill=fill)
            d.text((x + cw / 2, y + ch / 2), str(n), font=F(20, "SemiBold"), fill=tcol, anchor="mm")
        draw_footer(d, theme, self.bet, get_balance(self.author.id),
                    status or f"{self.spots} spots — Draw to play")
        return img

    async def _refresh(self, i):
        await i.response.edit_message(attachments=[img_file(self.render())],
                                      embed=game_embed("", C_INFO), view=self)

    @discord.ui.button(label="5 spots", style=discord.ButtonStyle.secondary, row=0)
    async def s5(self, i, b):
        self.spots = 5; self.picks = sorted(random.sample(range(1, 41), 5)); await self._refresh(i)
    @discord.ui.button(label="8 spots", style=discord.ButtonStyle.secondary, row=0)
    async def s8(self, i, b):
        self.spots = 8; self.picks = sorted(random.sample(range(1, 41), 8)); await self._refresh(i)
    @discord.ui.button(label="10 spots", style=discord.ButtonStyle.secondary, row=0)
    async def s10(self, i, b):
        self.spots = 10; self.picks = sorted(random.sample(range(1, 41), 10)); await self._refresh(i)
    @discord.ui.button(label="🔀 Re-pick", style=discord.ButtonStyle.secondary, row=0)
    async def repick(self, i, b):
        self.picks = sorted(random.sample(range(1, 41), self.spots)); await self._refresh(i)

    @discord.ui.button(label="🎱 Draw", style=discord.ButtonStyle.success, row=1)
    async def draw_btn(self, i, b):
        self.drawn = set(random.sample(range(1, 41), 10))
        hits = len(set(self.picks) & self.drawn)
        mult = KENO_TABLE[self.spots][hits]
        payout = int(self.bet * mult); settle(self.author.id, payout); delta = payout - self.bet
        img = self.render(status=f"{hits}/{self.spots} hits (x{mult}) · " + result_status(delta, payout))
        await show_result(i, self.author, "keno", self.bet, img)
        self.stop()


async def launch_keno(interaction, author, bet):
    view = KenoView(author, bet)
    await interaction.response.edit_message(attachments=[img_file(view.render())],
                                            embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["keno"] = launch_keno


# ----- ROULETTE -----------------------------------------------------------------
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
ROULETTE_BETS = {
    "Red": 2, "Black": 2, "Even": 2, "Odd": 2, "Low": 2, "High": 2,
    "1st12": 3, "2nd12": 3, "3rd12": 3,
}


class RouletteNumberModal(discord.ui.Modal, title="Straight-up number"):
    value = discord.ui.TextInput(label="Number (0-36)", placeholder="e.g. 17", max_length=2)

    def __init__(self, view):
        super().__init__(); self.view_ref = view

    async def on_submit(self, interaction):
        try:
            n = int(str(self.value))
        except ValueError:
            await interaction.response.send_message("Invalid number.", ephemeral=True); return
        if not (0 <= n <= 36):
            await interaction.response.send_message("Number must be 0-36.", ephemeral=True); return
        self.view_ref.choice = str(n)
        await self.view_ref.refresh(interaction)


class RouletteView(OwnerView):
    def __init__(self, author, bet):
        super().__init__(author, timeout=150)
        self.bet = bet
        self.choice = "Red"
        self.result = None

    def _win_mult(self):
        if self.choice.isdigit():
            return (int(self.choice) == self.result), 36
        c = self.choice
        r = self.result
        if c == "Red":
            return (r in RED_NUMBERS), 2
        if c == "Black":
            return (r != 0 and r not in RED_NUMBERS), 2
        if c == "Even":
            return (r != 0 and r % 2 == 0), 2
        if c == "Odd":
            return (r % 2 == 1), 2
        if c == "Low":
            return (1 <= r <= 18), 2
        if c == "High":
            return (19 <= r <= 36), 2
        if c == "1st12":
            return (1 <= r <= 12), 3
        if c == "2nd12":
            return (13 <= r <= 24), 3
        if c == "3rd12":
            return (25 <= r <= 36), 3
        return False, 0

    def render(self, status=None):
        theme = THEMES["roulette"][0]
        img, d = base_canvas(theme, "🎡 Roulette")
        cx, cy = W / 2, (96 + H - 88) / 2
        if self.result is None:
            d.text((cx, cy - 20), "BET ON", font=F(26, "SemiBold"), fill=GREY, anchor="mm")
            d.text((cx, cy + 34), self.choice, font=F(64, "ExtraBold"), fill=theme, anchor="mm")
        else:
            color = "green" if self.result == 0 else ("red" if self.result in RED_NUMBERS else "black")
            ring = {"red": (231, 76, 60), "black": (50, 54, 62), "green": (46, 204, 113)}[color]
            d.ellipse([cx - 78, cy - 78, cx + 78, cy + 78], fill=ring, outline=WHITE, width=4)
            d.text((cx, cy), str(self.result), font=F(64, "ExtraBold"), fill=WHITE, anchor="mm")
            d.text((cx, cy + 104), f"bet: {self.choice}", font=F(22, "Medium"), fill=GREY, anchor="mm")
        draw_footer(d, theme, self.bet, get_balance(self.author.id), status)
        return img

    async def refresh(self, i):
        await i.response.edit_message(attachments=[img_file(self.render())],
                                      embed=game_embed("", C_INFO), view=self)

    @discord.ui.button(label="Red", style=discord.ButtonStyle.danger, row=0)
    async def red(self, i, b): self.choice = "Red"; await self.refresh(i)
    @discord.ui.button(label="Black", style=discord.ButtonStyle.secondary, row=0)
    async def black(self, i, b): self.choice = "Black"; await self.refresh(i)
    @discord.ui.button(label="Even", style=discord.ButtonStyle.secondary, row=0)
    async def even(self, i, b): self.choice = "Even"; await self.refresh(i)
    @discord.ui.button(label="Odd", style=discord.ButtonStyle.secondary, row=0)
    async def odd(self, i, b): self.choice = "Odd"; await self.refresh(i)

    @discord.ui.button(label="Low 1-18", style=discord.ButtonStyle.secondary, row=1)
    async def low(self, i, b): self.choice = "Low"; await self.refresh(i)
    @discord.ui.button(label="High 19-36", style=discord.ButtonStyle.secondary, row=1)
    async def high(self, i, b): self.choice = "High"; await self.refresh(i)
    @discord.ui.button(label="1st12", style=discord.ButtonStyle.secondary, row=1)
    async def d1(self, i, b): self.choice = "1st12"; await self.refresh(i)
    @discord.ui.button(label="2nd12", style=discord.ButtonStyle.secondary, row=1)
    async def d2(self, i, b): self.choice = "2nd12"; await self.refresh(i)
    @discord.ui.button(label="3rd12", style=discord.ButtonStyle.secondary, row=1)
    async def d3(self, i, b): self.choice = "3rd12"; await self.refresh(i)

    @discord.ui.button(label="# Number", style=discord.ButtonStyle.primary, row=2)
    async def number(self, i, b): await i.response.send_modal(RouletteNumberModal(self))
    @discord.ui.button(label="🎡 Spin", style=discord.ButtonStyle.success, row=2)
    async def spin(self, i, b):
        self.result = random.randint(0, 36)
        win, mult = self._win_mult()
        if win:
            payout = self.bet * mult; settle(self.author.id, payout); delta = payout - self.bet
        else:
            payout = 0; delta = -self.bet
        img = self.render(status=result_status(delta, payout))
        await show_result(i, self.author, "roulette", self.bet, img)
        self.stop()


async def launch_roulette(interaction, author, bet):
    view = RouletteView(author, bet)
    await interaction.response.edit_message(attachments=[img_file(view.render())],
                                            embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["roulette"] = launch_roulette


# ----- BACCARAT -----------------------------------------------------------------
def bacc_value(cards):
    total = 0
    for r, _ in cards:
        v = 0 if r in ("10", "J", "Q", "K") else (1 if r == "A" else int(r))
        total += v
    return total % 10


def _bacc_pip(card):
    r = card[0]
    return 0 if r in ("10", "J", "Q", "K") else (1 if r == "A" else int(r))


def play_baccarat():
    deck = fresh_deck()
    player = [deck.pop(), deck.pop()]
    banker = [deck.pop(), deck.pop()]
    pv, bv = bacc_value(player), bacc_value(banker)
    if pv < 8 and bv < 8:
        p_third = None
        if pv <= 5:
            p_third = deck.pop(); player.append(p_third)
        pv = bacc_value(player)
        if p_third is None:
            draw_b = bv <= 5
        else:
            pip = _bacc_pip(p_third)
            if bv <= 2:
                draw_b = True
            elif bv == 3:
                draw_b = pip != 8
            elif bv == 4:
                draw_b = pip in (2, 3, 4, 5, 6, 7)
            elif bv == 5:
                draw_b = pip in (4, 5, 6, 7)
            elif bv == 6:
                draw_b = pip in (6, 7)
            else:
                draw_b = False
        if draw_b:
            banker.append(deck.pop())
        bv = bacc_value(banker)
    winner = "player" if pv > bv else ("banker" if bv > pv else "tie")
    return player, banker, pv, bv, winner


class BaccaratView(OwnerView):
    def __init__(self, author, bet):
        super().__init__(author, timeout=120)
        self.bet = bet
        self.state = None  # (player, banker, pv, bv, winner)

    def render(self, status="Player, Banker or Tie?"):
        theme = THEMES["baccarat"][0]
        img, d = base_canvas(theme, "🀄 Baccarat")
        if self.state is None:
            d.text((W / 2, (96 + H - 88) / 2), "Choose your side", font=F(40, "Bold"), fill=GREY, anchor="mm")
        else:
            player, banker, pv, bv, winner = self.state
            cw, chh = 70, 100

            def row(cards, label, yy, val, win):
                d.text((90, yy - 26), f"{label} ({val})", font=F(22, "SemiBold"),
                       fill=theme if win else GREY)
                for k, c in enumerate(cards):
                    draw_card(d, 90 + k * (cw + 12), yy, cw, chh, c)
            row(player, "Player", 150, pv, winner == "player")
            row(banker, "Banker", 300, bv, winner == "banker")
            d.text((W - 80, 150), winner.upper(), font=F(30, "ExtraBold"),
                   fill=theme, anchor="ra")
        draw_footer(d, theme, self.bet, get_balance(self.author.id), status)
        return img

    async def _bet_on(self, i, side):
        player, banker, pv, bv, winner = play_baccarat()
        self.state = (player, banker, pv, bv, winner)
        if side == winner:
            if winner == "tie":
                payout = self.bet * 9
            elif winner == "banker":
                payout = int(self.bet * 1.95)
            else:
                payout = self.bet * 2
            settle(self.author.id, payout); delta = payout - self.bet
        else:
            payout = 0; delta = -self.bet
        img = self.render(status=f"{winner.upper()} wins · " + result_status(delta, payout))
        await show_result(i, self.author, "baccarat", self.bet, img)
        self.stop()

    @discord.ui.button(label="Player", style=discord.ButtonStyle.primary)
    async def player(self, i, b): await self._bet_on(i, "player")
    @discord.ui.button(label="Banker", style=discord.ButtonStyle.danger)
    async def banker(self, i, b): await self._bet_on(i, "banker")
    @discord.ui.button(label="Tie", style=discord.ButtonStyle.secondary)
    async def tie(self, i, b): await self._bet_on(i, "tie")


async def launch_baccarat(interaction, author, bet):
    view = BaccaratView(author, bet)
    await interaction.response.edit_message(attachments=[img_file(view.render())],
                                            embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["baccarat"] = launch_baccarat


# ==============================================================================
#  INTERACTIVE GAMES — MINES
# ==============================================================================

MINES_COLS, MINES_ROWS = 5, 4
MINES_TILES = MINES_COLS * MINES_ROWS  # 20


def mines_multiplier(picks, mines):
    m = 1.0
    for i in range(picks):
        m *= (MINES_TILES - i) / (MINES_TILES - mines - i)
    return m * (1 - HOUSE_EDGE)


def _gem(d, cx, cy, s, col):
    d.polygon([(cx, cy - s), (cx + s, cy), (cx, cy + s), (cx - s, cy)], fill=col, outline=(15, 15, 18))


def _bomb(d, cx, cy, s):
    d.ellipse([cx - s, cy - s, cx + s, cy + s], fill=(20, 20, 24))
    d.line([(cx, cy - s), (cx, cy - s - 7)], fill=(200, 80, 40), width=3)


class MineButton(discord.ui.Button):
    def __init__(self, index):
        super().__init__(label="\u200b", style=discord.ButtonStyle.secondary, row=index // MINES_COLS)
        self.index = index

    async def callback(self, interaction):
        v = self.view
        if v.ended or self.index in v.revealed:
            await interaction.response.defer(); return
        if self.index in v.mines:
            v.ended = True
            for c in v.children:
                c.disabled = True
            img = v.render(status=f"💥 BOOM — lost {fmt(v.bet)}", reveal_all=True)
            await show_result(interaction, v.author, "mines", v.bet, img)
            v.stop(); return
        v.revealed.add(self.index)
        self.label = "💎"; self.style = discord.ButtonStyle.success; self.disabled = True
        picks = len(v.revealed)
        v.mult = mines_multiplier(picks, len(v.mines))
        if picks >= MINES_TILES - len(v.mines):
            v.ended = True
            payout = int(v.bet * v.mult); settle(v.author.id, payout)
            for c in v.children:
                c.disabled = True
            img = v.render(status=f"CLEARED x{v.mult:.2f} · +{fmt(payout - v.bet)}", reveal_all=True)
            await show_result(interaction, v.author, "mines", v.bet, img)
            v.stop(); return
        v.cash.label = f"💰 Cash Out  {v.mult:.2f}x → {fmt(int(v.bet * v.mult))}"
        img = v.render(status=f"{picks} gem(s) · x{v.mult:.2f} · potential {fmt(int(v.bet * v.mult))}")
        await interaction.response.edit_message(attachments=[img_file(img)], embed=game_embed("", C_INFO), view=v)


class MinesCashOut(discord.ui.Button):
    def __init__(self):
        super().__init__(label="💰 Cash Out", style=discord.ButtonStyle.success, row=4)

    async def callback(self, interaction):
        v = self.view
        if v.ended:
            await interaction.response.defer(); return
        if not v.revealed:
            await interaction.response.send_message("Reveal at least one gem first!", ephemeral=True); return
        v.ended = True
        payout = int(v.bet * v.mult); settle(v.author.id, payout)
        for c in v.children:
            c.disabled = True
        img = v.render(status=f"Cashed out x{v.mult:.2f} · +{fmt(payout - v.bet)}", reveal_all=True)
        await show_result(interaction, v.author, "mines", v.bet, img)
        v.stop()


class MinesView(OwnerView):
    def __init__(self, author, bet, num_mines):
        super().__init__(author, timeout=200)
        self.bet = bet
        self.num_mines = num_mines
        self.mines = set(random.sample(range(MINES_TILES), num_mines))
        self.revealed = set()
        self.mult = 1.0
        self.ended = False
        for i in range(MINES_TILES):
            self.add_item(MineButton(i))
        self.cash = MinesCashOut()
        self.add_item(self.cash)

    def render(self, status=None, reveal_all=False):
        theme = THEMES["mines"][0]
        img, d = base_canvas(theme, "Mines")
        ax, ay = 250, 110
        tile, gap = 66, 12
        for i in range(MINES_TILES):
            c, r = i % MINES_COLS, i // MINES_COLS
            x = ax + c * (tile + gap)
            y = ay + r * (tile + gap)
            is_mine = i in self.mines
            is_rev = i in self.revealed
            if is_rev:
                d.rounded_rectangle([x, y, x + tile, y + tile], radius=10,
                                    fill=_mix(theme, (10, 10, 14), 0.55), outline=theme, width=2)
                _gem(d, x + tile / 2, y + tile / 2, tile * 0.26, theme)
            elif reveal_all and is_mine:
                d.rounded_rectangle([x, y, x + tile, y + tile], radius=10,
                                    fill=(120, 30, 26), outline=(231, 76, 60), width=2)
                _bomb(d, x + tile / 2, y + tile / 2, tile * 0.2)
            else:
                d.rounded_rectangle([x, y, x + tile, y + tile], radius=10,
                                    fill=(40, 44, 52), outline=(60, 64, 72), width=2)
                d.ellipse([x + tile / 2 - 4, y + tile / 2 - 4, x + tile / 2 + 4, y + tile / 2 + 4],
                          fill=(60, 64, 72))
        # side info
        d.text((70, 150), f"{self.num_mines}", font=F(60, "ExtraBold"), fill=theme)
        d.text((70, 220), "mines", font=F(22, "Medium"), fill=GREY)
        d.text((70, 270), f"x{self.mult:.2f}", font=F(40, "ExtraBold"), fill=WHITE)
        draw_footer(d, theme, self.bet, get_balance(self.author.id), status)
        return img


class MinesCountModal(discord.ui.Modal, title="Number of mines"):
    value = discord.ui.TextInput(label="Mines (1-19)", placeholder="3", max_length=2)

    def __init__(self, author, bet, message):
        super().__init__(); self.author = author; self.bet = bet; self.msg = message

    async def on_submit(self, interaction):
        try:
            n = int(str(self.value))
        except ValueError:
            await interaction.response.send_message("Invalid number.", ephemeral=True); return
        n = max(1, min(MINES_TILES - 1, n))
        view = MinesView(self.author, self.bet, n)
        img = view.render(status=f"{n} mines hidden — reveal gems!")
        await interaction.response.edit_message(attachments=[img_file(img)], embed=game_embed("", C_INFO), view=view)
        view.message = interaction.message


class MinesSetupView(OwnerView):
    """After betting, pick the number of mines, then start."""
    def __init__(self, author, bet):
        super().__init__(author, timeout=120)
        self.bet = bet

    def render(self):
        theme = THEMES["mines"][0]
        img, d = base_canvas(theme, "Mines")
        cy = (96 + H - 88) / 2
        d.text((W / 2, cy - 20), "HOW MANY MINES?", font=F(30, "SemiBold"), fill=GREY, anchor="mm")
        d.text((W / 2, cy + 36), "more mines = higher payout", font=F(22, "Medium"), fill=theme, anchor="mm")
        draw_footer(d, theme, self.bet, get_balance(self.author.id), None)
        return img

    async def _start(self, interaction, n):
        view = MinesView(self.author, self.bet, n)
        img = view.render(status=f"{n} mines hidden — reveal gems!")
        await interaction.response.edit_message(attachments=[img_file(img)], embed=game_embed("", C_INFO), view=view)
        view.message = interaction.message
        self.stop()

    @discord.ui.button(label="1", style=discord.ButtonStyle.secondary)
    async def m1(self, i, b): await self._start(i, 1)
    @discord.ui.button(label="3", style=discord.ButtonStyle.primary)
    async def m3(self, i, b): await self._start(i, 3)
    @discord.ui.button(label="5", style=discord.ButtonStyle.secondary)
    async def m5(self, i, b): await self._start(i, 5)
    @discord.ui.button(label="10", style=discord.ButtonStyle.secondary)
    async def m10(self, i, b): await self._start(i, 10)
    @discord.ui.button(label="Custom", style=discord.ButtonStyle.secondary)
    async def custom(self, i, b):
        await i.response.send_modal(MinesCountModal(self.author, self.bet, self.message))


async def launch_mines(interaction, author, bet):
    view = MinesSetupView(author, bet)
    await interaction.response.edit_message(attachments=[img_file(view.render())],
                                            embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["mines"] = launch_mines


# ==============================================================================
#  INTERACTIVE GAMES — CRASH (live multiplier)
# ==============================================================================

class CrashView(OwnerView):
    def __init__(self, author, bet, crash_point):
        super().__init__(author, timeout=90)
        self.bet = bet
        self.crash = crash_point
        self.mult = 1.0
        self.ended = False
        self.history = [1.0]

    def render(self, status=None, crashed=False):
        theme = THEMES["crash"][0]
        col = (231, 76, 60) if crashed else theme
        img, d = base_canvas(col, "Crash")
        # plot area
        px0, py0, px1, py1 = 80, 130, W - 80, H - 130
        d.line([(px0, py1), (px1, py1)], fill=(60, 64, 72), width=2)
        d.line([(px0, py0), (px0, py1)], fill=(60, 64, 72), width=2)
        pts = self.history
        if len(pts) >= 2:
            top = max(2.0, max(pts))
            coords = []
            for k, m in enumerate(pts):
                x = px0 + (px1 - px0) * k / max(1, len(pts) - 1)
                y = py1 - (py1 - py0) * (m - 1) / (top - 1)
                coords.append((x, y))
            d.line(coords, fill=col, width=5, joint="curve")
            d.ellipse([coords[-1][0] - 6, coords[-1][1] - 6, coords[-1][0] + 6, coords[-1][1] + 6], fill=WHITE)
        d.text((W / 2, (py0 + py1) / 2), f"{self.mult:.2f}x",
               font=F(90, "ExtraBold"), fill=col, anchor="mm")
        draw_footer(d, col, self.bet, get_balance(self.author.id), status)
        return img

    @discord.ui.button(label="💰 Cash Out", style=discord.ButtonStyle.success)
    async def cashout(self, interaction, button):
        if self.ended:
            await interaction.response.defer(); return
        self.ended = True
        payout = int(self.bet * self.mult); settle(self.author.id, payout)
        button.disabled = True
        img = self.render(status=f"Cashed out {self.mult:.2f}x · +{fmt(payout - self.bet)}")
        await show_result(interaction, self.author, "crash", self.bet, img)
        self.stop()


async def run_crash(view):
    await asyncio.sleep(1.0)
    while not view.ended:
        view.mult = round(view.mult * 1.11 + 0.05, 2)
        view.history.append(view.mult)
        if view.mult >= view.crash:
            view.ended = True
            for c in view.children:
                c.disabled = True
            view.mult = view.crash
            img = view.render(status=f"💥 CRASHED at {view.crash:.2f}x · lost {fmt(view.bet)}", crashed=True)
            if view.message:
                try:
                    await view.message.edit(attachments=[img_file(img)], embed=game_embed("", C_INFO),
                                            view=PlayAgainView(view.author, "crash", view.bet))
                except Exception:
                    pass
            view.stop(); return
        img = view.render(status="Cash out before it crashes!")
        if view.message:
            try:
                await view.message.edit(attachments=[img_file(img)], embed=game_embed("", C_INFO), view=view)
            except Exception:
                pass
        await asyncio.sleep(1.3)


async def launch_crash(interaction, author, bet):
    u = random.random()
    crash_point = round(min(max(1.0, (1 - HOUSE_EDGE) / u) if u > 0 else 50.0, 50.0), 2)
    view = CrashView(author, bet, crash_point)
    img = view.render(status="Cash out before it crashes!")
    await interaction.response.edit_message(attachments=[img_file(img)], embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
    bot.loop.create_task(run_crash(view))
GAME_LAUNCHERS["crash"] = launch_crash


# ==============================================================================
#  INTERACTIVE — HILO
# ==============================================================================
HILO_ORDER = RANKS  # A..K low->high


class HiloView(OwnerView):
    def __init__(self, author, bet):
        super().__init__(author, timeout=200)
        self.bet = bet
        self.card = random.choice(RANKS), random.choice(SUITS)
        self.last = None
        self.mult = 1.0
        self.ended = False

    def _idx(self, card):
        return HILO_ORDER.index(card[0])

    def _p_higher(self):
        return (12 - self._idx(self.card)) / 13

    def _p_lower(self):
        return self._idx(self.card) / 13

    def render(self, status=None):
        theme = THEMES["hilo"][0]
        img, d = base_canvas(theme, "Hi-Lo")
        cy = (96 + H - 88) / 2
        draw_card(d, 130, cy - 80, 120, 168, self.card)
        d.text((130, cy - 112), "current", font=F(20, "Medium"), fill=GREY)
        if self.last is not None:
            draw_card(d, 340, cy - 80, 120, 168, self.last)
            d.text((340, cy - 112), "drawn", font=F(20, "Medium"), fill=GREY)
        ph, pl = self._p_higher(), self._p_lower()
        d.text((W - 90, cy - 70), f"Higher  x{((1 - HOUSE_EDGE) / ph) if ph else 0:.2f}",
               font=F(22, "SemiBold"), fill=theme, anchor="ra")
        d.text((W - 90, cy - 30), f"Lower   x{((1 - HOUSE_EDGE) / pl) if pl else 0:.2f}",
               font=F(22, "SemiBold"), fill=GREY, anchor="ra")
        d.text((W - 90, cy + 30), f"x{self.mult:.2f}", font=F(46, "ExtraBold"), fill=WHITE, anchor="ra")
        d.text((W - 90, cy + 78), f"pot {fmt(int(self.bet * self.mult))}", font=F(20, "Medium"),
               fill=GREY, anchor="ra")
        draw_footer(d, theme, self.bet, get_balance(self.author.id), status)
        return img

    async def _guess(self, interaction, higher):
        p = self._p_higher() if higher else self._p_lower()
        new = random.choice(RANKS), random.choice(SUITS)
        self.last = new
        ni, ci = self._idx(new), self._idx(self.card)
        win = (ni > ci) if higher else (ni < ci)
        if win and p > 0:
            self.mult *= (1 - HOUSE_EDGE) / p
            self.card = new
            self.cash.label = f"💰 Cash Out {self.mult:.2f}x → {fmt(int(self.bet * self.mult))}"
            img = self.render(status=f"Correct! x{self.mult:.2f} · pot {fmt(int(self.bet * self.mult))}")
            await interaction.response.edit_message(attachments=[img_file(img)],
                                                    embed=game_embed("", C_INFO), view=self)
        else:
            self.ended = True
            for c in self.children:
                c.disabled = True
            img = self.render(status=f"Wrong — lost {fmt(self.bet)}")
            await show_result(interaction, self.author, "hilo", self.bet, img)
            self.stop()

    @discord.ui.button(label="▲ Higher", style=discord.ButtonStyle.success)
    async def higher(self, i, b): await self._guess(i, True)
    @discord.ui.button(label="▼ Lower", style=discord.ButtonStyle.primary)
    async def lower(self, i, b): await self._guess(i, False)

    @discord.ui.button(label="💰 Cash Out", style=discord.ButtonStyle.danger)
    async def cash(self, i, b):
        if self.ended:
            await i.response.defer(); return
        if self.mult <= 1.0:
            await i.response.send_message("Make at least one correct guess first!", ephemeral=True); return
        self.ended = True
        payout = int(self.bet * self.mult); settle(self.author.id, payout)
        for c in self.children:
            c.disabled = True
        img = self.render(status=f"Cashed out x{self.mult:.2f} · +{fmt(payout - self.bet)}")
        await show_result(i, self.author, "hilo", self.bet, img)
        self.stop()


async def launch_hilo(interaction, author, bet):
    view = HiloView(author, bet)
    await interaction.response.edit_message(attachments=[img_file(view.render(status="Higher or lower?"))],
                                            embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["hilo"] = launch_hilo


# ==============================================================================
#  INTERACTIVE — DRAGON TOWER
# ==============================================================================
DRAGON_DIFF = {
    "easy":   (4, 3), "medium": (3, 2), "hard": (2, 1), "expert": (3, 1), "master": (4, 1),
}
DRAGON_ROWS = 9


class DragonTile(discord.ui.Button):
    def __init__(self, col):
        super().__init__(label="\u200b", style=discord.ButtonStyle.secondary, row=0)
        self.col = col

    async def callback(self, interaction):
        v = self.view
        if v.ended:
            await interaction.response.defer(); return
        safe = v.safe_cols[v.level]
        if self.col in safe:
            v.path.append((v.level, self.col))
            v.level += 1
            v.mult *= v.step_mult
            if v.level >= DRAGON_ROWS:
                v.ended = True
                payout = int(v.bet * v.mult); settle(v.author.id, payout)
                for c in v.children:
                    c.disabled = True
                img = v.render(status=f"TOP! x{v.mult:.2f} · +{fmt(payout - v.bet)}", reveal=True)
                await show_result(interaction, v.author, "dragon", v.bet, img)
                v.stop(); return
            v.sync_buttons()
            v.cash.label = f"💰 Cash Out {v.mult:.2f}x → {fmt(int(v.bet * v.mult))}"
            img = v.render(status=f"Level {v.level} · x{v.mult:.2f} · pot {fmt(int(v.bet * v.mult))}")
            await interaction.response.edit_message(attachments=[img_file(img)],
                                                    embed=game_embed("", C_INFO), view=v)
        else:
            v.ended = True
            v.dead = (v.level, self.col)
            for c in v.children:
                c.disabled = True
            img = v.render(status=f"🐉 Burned — lost {fmt(v.bet)}", reveal=True)
            await show_result(interaction, v.author, "dragon", v.bet, img)
            v.stop()


class DragonView(OwnerView):
    def __init__(self, author, bet, diff):
        super().__init__(author, timeout=200)
        self.bet = bet
        self.diff = diff
        self.tiles, self.safe = DRAGON_DIFF[diff]
        self.step_mult = (self.tiles / self.safe) * (1 - HOUSE_EDGE)
        self.safe_cols = [set(random.sample(range(self.tiles), self.safe)) for _ in range(DRAGON_ROWS)]
        self.level = 0
        self.mult = 1.0
        self.ended = False
        self.path = []
        self.dead = None
        for c in range(self.tiles):
            self.add_item(DragonTile(c))
        self.cash = discord.ui.Button(label="💰 Cash Out", style=discord.ButtonStyle.danger, row=1)
        self.cash.callback = self._cashout
        self.add_item(self.cash)

    def sync_buttons(self):
        pass

    async def _cashout(self, interaction):
        if self.ended:
            await interaction.response.defer(); return
        if self.level == 0:
            await interaction.response.send_message("Climb at least one level first!", ephemeral=True); return
        self.ended = True
        payout = int(self.bet * self.mult); settle(self.author.id, payout)
        for c in self.children:
            c.disabled = True
        img = self.render(status=f"Cashed out x{self.mult:.2f} · +{fmt(payout - self.bet)}", reveal=True)
        await show_result(interaction, self.author, "dragon", self.bet, img)
        self.stop()

    def render(self, status=None, reveal=False):
        theme = THEMES["dragon"][0]
        img, d = base_canvas(theme, "Dragon Tower")
        rows_area_top, rows_area_bot = 108, H - 96
        rh = (rows_area_bot - rows_area_top) / DRAGON_ROWS
        cw = 92
        x0 = W / 2 - (self.tiles * cw) / 2
        for r in range(DRAGON_ROWS):
            disp_row = DRAGON_ROWS - 1 - r  # bottom = level 0
            y = rows_area_top + r * rh
            for c in range(self.tiles):
                x = x0 + c * cw
                box = [x + 4, y + 3, x + cw - 4, y + rh - 3]
                done = disp_row < self.level
                here = (disp_row == self.level and not self.ended)
                if done and (disp_row, c) in self.path:
                    d.rounded_rectangle(box, radius=8, fill=_mix(theme, (10, 10, 14), 0.5), outline=theme, width=2)
                    _gem(d, (x + x + cw) / 2, y + rh / 2, rh * 0.22, theme)
                elif reveal and c in self.safe_cols[disp_row]:
                    d.rounded_rectangle(box, radius=8, fill=(34, 40, 34),
                                        outline=(80, 120, 80), width=1)
                    _gem(d, (x + x + cw) / 2, y + rh / 2, rh * 0.16, (90, 150, 90))
                elif reveal:
                    d.rounded_rectangle(box, radius=8, fill=(70, 30, 26), outline=(150, 60, 50), width=1)
                else:
                    fill = (60, 64, 72) if here else (40, 44, 52)
                    d.rounded_rectangle(box, radius=8, fill=fill, outline=(70, 74, 82), width=1)
                if self.dead == (disp_row, c):
                    d.ellipse([(x + cw / 2) - rh * 0.18, y + rh / 2 - rh * 0.18,
                               (x + cw / 2) + rh * 0.18, y + rh / 2 + rh * 0.18], fill=(231, 76, 60))
        d.text((70, 140), self.diff.upper(), font=F(24, "Bold"), fill=theme)
        d.text((70, 180), f"x{self.mult:.2f}", font=F(40, "ExtraBold"), fill=WHITE)
        draw_footer(d, theme, self.bet, get_balance(self.author.id), status)
        return img


class DragonSetupView(OwnerView):
    def __init__(self, author, bet):
        super().__init__(author, timeout=120)
        self.bet = bet

    def render(self):
        theme = THEMES["dragon"][0]
        img, d = base_canvas(theme, "Dragon Tower")
        cy = (96 + H - 88) / 2
        d.text((W / 2, cy - 10), "CHOOSE DIFFICULTY", font=F(30, "SemiBold"), fill=GREY, anchor="mm")
        d.text((W / 2, cy + 40), "harder = fewer safe tiles, bigger payout",
               font=F(20, "Medium"), fill=theme, anchor="mm")
        draw_footer(d, theme, self.bet, get_balance(self.author.id), None)
        return img

    async def _start(self, i, diff):
        view = DragonView(self.author, self.bet, diff)
        img = view.render(status=f"{diff.capitalize()} — pick a tile to climb!")
        await i.response.edit_message(attachments=[img_file(img)], embed=game_embed("", C_INFO), view=view)
        view.message = i.message
        self.stop()

    @discord.ui.button(label="Easy", style=discord.ButtonStyle.success)
    async def easy(self, i, b): await self._start(i, "easy")
    @discord.ui.button(label="Medium", style=discord.ButtonStyle.primary)
    async def medium(self, i, b): await self._start(i, "medium")
    @discord.ui.button(label="Hard", style=discord.ButtonStyle.secondary)
    async def hard(self, i, b): await self._start(i, "hard")
    @discord.ui.button(label="Expert", style=discord.ButtonStyle.secondary)
    async def expert(self, i, b): await self._start(i, "expert")
    @discord.ui.button(label="Master", style=discord.ButtonStyle.danger)
    async def master(self, i, b): await self._start(i, "master")


async def launch_dragon(interaction, author, bet):
    view = DragonSetupView(author, bet)
    await interaction.response.edit_message(attachments=[img_file(view.render())],
                                            embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["dragon"] = launch_dragon


# ==============================================================================
#  INTERACTIVE — CHICKEN & PUMP  (shared ladder mechanic)
# ==============================================================================
LADDER_DIFF = {"easy": 0.95, "medium": 0.84, "hard": 0.68, "hardcore": 0.50}


class LadderView(OwnerView):
    def __init__(self, author, bet, game_key, diff):
        super().__init__(author, timeout=200)
        self.bet = bet
        self.game_key = game_key  # "chicken" or "pump"
        self.diff = diff
        self.p = LADDER_DIFF[diff]
        self.step = 0
        self.mult = 1.0
        self.ended = False
        self.dead = False
        self.advance.label = "🚶 Walk" if game_key == "chicken" else "🎈 Pump"

    def render(self, status=None):
        theme = THEMES[self.game_key][0]
        title = "Chicken" if self.game_key == "chicken" else "Pump"
        img, d = base_canvas(theme, title)
        cx, cy = W / 2, (96 + H - 88) / 2
        if self.game_key == "pump":
            r = 40 + min(120, self.step * 12)
            col = (231, 76, 60) if self.dead else theme
            d.ellipse([cx - r, cy - r - 10, cx + r, cy + r - 10], fill=_mix(col, (255, 255, 255), 0.15),
                      outline=col, width=4)
            d.line([(cx, cy + r - 10), (cx, cy + r + 26)], fill=GREY, width=3)
            if self.dead:
                d.text((cx, cy - 10), "POP!", font=F(40, "ExtraBold"), fill=WHITE, anchor="mm")
            else:
                d.text((cx, cy - 10), f"x{self.mult:.2f}", font=F(40, "ExtraBold"), fill=WHITE, anchor="mm")
        else:
            lanes = 10
            lw = (W - 160) / lanes
            for i in range(lanes):
                x = 80 + i * lw
                fill = theme if i < self.step else (40, 44, 52)
                d.rounded_rectangle([x + 4, cy - 24, x + lw - 4, cy + 24], radius=8, fill=fill)
            px = 80 + min(lanes, self.step) * lw
            d.ellipse([px - 16, cy - 16, px + 16, cy + 16],
                      fill=(231, 76, 60) if self.dead else (241, 196, 15))
            d.text((cx, cy - 70), f"x{self.mult:.2f}", font=F(40, "ExtraBold"),
                   fill=(231, 76, 60) if self.dead else theme, anchor="mm")
        nxt = self.mult * (1 - HOUSE_EDGE) / self.p
        d.text((W / 2, cy + 90), f"{self.diff} · next x{nxt:.2f} · {int(self.p*100)}% safe",
               font=F(20, "Medium"), fill=GREY, anchor="mm")
        draw_footer(d, theme, self.bet, get_balance(self.author.id), status)
        return img

    @discord.ui.button(label="Advance", style=discord.ButtonStyle.success)
    async def advance(self, i, b):
        if self.ended:
            await i.response.defer(); return
        if random.random() < self.p:
            self.step += 1
            self.mult *= (1 - HOUSE_EDGE) / self.p
            self.cash.label = f"💰 Cash Out {self.mult:.2f}x → {fmt(int(self.bet * self.mult))}"
            img = self.render(status=f"Safe! step {self.step} · x{self.mult:.2f}")
            await i.response.edit_message(attachments=[img_file(img)], embed=game_embed("", C_INFO), view=self)
        else:
            self.ended = True; self.dead = True
            for c in self.children:
                c.disabled = True
            verb = "popped" if self.game_key == "pump" else "got hit"
            img = self.render(status=f"You {verb} — lost {fmt(self.bet)}")
            await show_result(i, self.author, self.game_key, self.bet, img)
            self.stop()

    @discord.ui.button(label="💰 Cash Out", style=discord.ButtonStyle.danger)
    async def cash(self, i, b):
        if self.ended:
            await i.response.defer(); return
        if self.step == 0:
            await i.response.send_message("Advance at least once first!", ephemeral=True); return
        self.ended = True
        payout = int(self.bet * self.mult); settle(self.author.id, payout)
        for c in self.children:
            c.disabled = True
        img = self.render(status=f"Cashed out x{self.mult:.2f} · +{fmt(payout - self.bet)}")
        await show_result(i, self.author, self.game_key, self.bet, img)
        self.stop()


class LadderSetupView(OwnerView):
    def __init__(self, author, bet, game_key):
        super().__init__(author, timeout=120)
        self.bet = bet
        self.game_key = game_key

    def render(self):
        theme = THEMES[self.game_key][0]
        title = "Chicken" if self.game_key == "chicken" else "Pump"
        img, d = base_canvas(theme, title)
        cy = (96 + H - 88) / 2
        d.text((W / 2, cy - 10), "CHOOSE DIFFICULTY", font=F(30, "SemiBold"), fill=GREY, anchor="mm")
        d.text((W / 2, cy + 40), "riskier = bigger steps", font=F(20, "Medium"), fill=theme, anchor="mm")
        draw_footer(d, theme, self.bet, get_balance(self.author.id), None)
        return img

    async def _start(self, i, diff):
        view = LadderView(self.author, self.bet, self.game_key, diff)
        img = view.render(status=f"{diff.capitalize()} — go!")
        await i.response.edit_message(attachments=[img_file(img)], embed=game_embed("", C_INFO), view=view)
        view.message = i.message
        self.stop()

    @discord.ui.button(label="Easy", style=discord.ButtonStyle.success)
    async def easy(self, i, b): await self._start(i, "easy")
    @discord.ui.button(label="Medium", style=discord.ButtonStyle.primary)
    async def medium(self, i, b): await self._start(i, "medium")
    @discord.ui.button(label="Hard", style=discord.ButtonStyle.secondary)
    async def hard(self, i, b): await self._start(i, "hard")
    @discord.ui.button(label="Hardcore", style=discord.ButtonStyle.danger)
    async def hardcore(self, i, b): await self._start(i, "hardcore")


async def launch_chicken(interaction, author, bet):
    view = LadderSetupView(author, bet, "chicken")
    await interaction.response.edit_message(attachments=[img_file(view.render())],
                                            embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["chicken"] = launch_chicken


async def launch_pump(interaction, author, bet):
    view = LadderSetupView(author, bet, "pump")
    await interaction.response.edit_message(attachments=[img_file(view.render())],
                                            embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["pump"] = launch_pump


# ==============================================================================
#  INTERACTIVE — BLACKJACK
# ==============================================================================
class BlackjackView(OwnerView):
    def __init__(self, author, bet):
        super().__init__(author, timeout=200)
        self.bet = bet
        self.deck = fresh_deck()
        self.player = [self.deck.pop(), self.deck.pop()]
        self.dealer = [self.deck.pop(), self.deck.pop()]
        self.ended = False
        self.doubled = False
        self.stood = False

    def render(self, status=None, reveal=False):
        theme = THEMES["blackjack"][0]
        img, d = base_canvas(theme, "Blackjack")
        cw, chh = 78, 110

        def hand(cards, label, yy, val, hide_first=False):
            d.text((90, yy - 28), f"{label}" + ("" if hide_first else f"  ({val})"),
                   font=F(22, "SemiBold"), fill=GREY)
            for k, c in enumerate(cards):
                fu = not (hide_first and k == 0)
                draw_card(d, 90 + k * (cw + 12), yy, cw, chh, c, face_up=fu)
        hide = not (reveal or self.stood or self.ended)
        hand(self.dealer, "Dealer", 130, bj_value(self.dealer), hide_first=hide)
        hand(self.player, "Player", 300, bj_value(self.player))
        draw_footer(d, theme, self.bet, get_balance(self.author.id), status)
        return img

    async def _finish(self, interaction):
        while bj_value(self.dealer) < 17:
            self.dealer.append(self.deck.pop())
        pv, dv = bj_value(self.player), bj_value(self.dealer)
        stake = self.bet * (2 if self.doubled else 1)
        pbj = pv == 21 and len(self.player) == 2
        if pv > 21:
            payout = 0; res = "Bust"
        elif dv > 21 or pv > dv:
            payout = int(stake * 2.5) if pbj else stake * 2
            res = "Blackjack!" if pbj else "You win"
        elif pv < dv:
            payout = 0; res = "Dealer wins"
        else:
            payout = stake; res = "Push"
        if payout > 0:
            settle(self.author.id, payout)
        delta = payout - stake
        self.ended = True
        for c in self.children:
            c.disabled = True
        img = self.render(status=f"{res} · " + result_status(delta, payout), reveal=True)
        await show_result(interaction, self.author, "blackjack", self.bet, img)
        self.stop()

    @discord.ui.button(label="🃏 Hit", style=discord.ButtonStyle.primary)
    async def hit(self, i, b):
        if self.ended:
            await i.response.defer(); return
        self.player.append(self.deck.pop())
        if bj_value(self.player) >= 21:
            await self._finish(i); return
        img = self.render(status="Hit or Stand?")
        await i.response.edit_message(attachments=[img_file(img)], embed=game_embed("", C_INFO), view=self)

    @discord.ui.button(label="✋ Stand", style=discord.ButtonStyle.success)
    async def stand(self, i, b):
        if self.ended:
            await i.response.defer(); return
        self.stood = True
        await self._finish(i)

    @discord.ui.button(label="2× Double", style=discord.ButtonStyle.secondary)
    async def double(self, i, b):
        if self.ended:
            await i.response.defer(); return
        bal = get_balance(self.author.id)
        if bal < self.bet:
            await i.response.send_message("Not enough to double.", ephemeral=True); return
        if len(self.player) != 2:
            await i.response.send_message("You can only double on your first two cards.", ephemeral=True); return
        add_balance(self.author.id, -self.bet); add_stats(self.author.id, wagered=self.bet)
        self.doubled = True
        self.player.append(self.deck.pop())
        await self._finish(i)


async def launch_blackjack(interaction, author, bet):
    view = BlackjackView(author, bet)
    if bj_value(view.player) == 21:  # natural -> resolve immediately
        await view._finish(interaction); return
    img = view.render(status="Hit, Stand or Double?")
    await interaction.response.edit_message(attachments=[img_file(img)], embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["blackjack"] = launch_blackjack


# ==============================================================================
#  INTERACTIVE — VIDEO POKER (Jacks or Better)
# ==============================================================================
POKER_PAYTABLE = [
    ("Royal Flush", 250), ("Straight Flush", 50), ("Four of a Kind", 25),
    ("Full House", 9), ("Flush", 6), ("Straight", 4), ("Three of a Kind", 3),
    ("Two Pair", 2), ("Jacks or Better", 1),
]
_RVAL = {r: i for i, r in enumerate(["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"], start=2)}


def poker_evaluate(cards):
    ranks = sorted((_RVAL[r] for r, _ in cards))
    suits = [s for _, s in cards]
    counts = {}
    for v in ranks:
        counts[v] = counts.get(v, 0) + 1
    cc = sorted(counts.values(), reverse=True)
    flush = len(set(suits)) == 1
    uniq = sorted(set(ranks))
    straight = len(uniq) == 5 and uniq[-1] - uniq[0] == 4
    if set(ranks) == {14, 2, 3, 4, 5}:  # wheel A-5
        straight = True
    if straight and flush and min(ranks) == 10:
        return "Royal Flush", 250
    if straight and flush:
        return "Straight Flush", 50
    if cc[0] == 4:
        return "Four of a Kind", 25
    if cc[0] == 3 and cc[1] == 2:
        return "Full House", 9
    if flush:
        return "Flush", 6
    if straight:
        return "Straight", 4
    if cc[0] == 3:
        return "Three of a Kind", 3
    if cc[0] == 2 and cc[1] == 2:
        return "Two Pair", 2
    if cc[0] == 2:
        pair_val = [v for v, n in counts.items() if n == 2][0]
        if pair_val >= 11 or pair_val == 14:
            return "Jacks or Better", 1
    return "No win", 0


class HoldButton(discord.ui.Button):
    def __init__(self, index):
        super().__init__(label=f"Hold {index+1}", style=discord.ButtonStyle.secondary, row=0)
        self.index = index

    async def callback(self, interaction):
        v = self.view
        if v.ended:
            await interaction.response.defer(); return
        if self.index in v.held:
            v.held.discard(self.index); self.style = discord.ButtonStyle.secondary
        else:
            v.held.add(self.index); self.style = discord.ButtonStyle.success
        img = v.render(status="Toggle holds, then Draw")
        await interaction.response.edit_message(attachments=[img_file(img)], embed=game_embed("", C_INFO), view=v)


class VideoPokerView(OwnerView):
    def __init__(self, author, bet):
        super().__init__(author, timeout=200)
        self.bet = bet
        self.deck = fresh_deck()
        self.hand = [self.deck.pop() for _ in range(5)]
        self.held = set()
        self.ended = False
        self.drawn = False
        for k in range(5):
            self.add_item(HoldButton(k))
        self.draw_btn = discord.ui.Button(label="🎴 Draw", style=discord.ButtonStyle.primary, row=1)
        self.draw_btn.callback = self._draw
        self.add_item(self.draw_btn)

    def render(self, status=None):
        theme = THEMES["videopoker"][0]
        img, d = base_canvas(theme, "Video Poker")
        cw, chh = 120, 168
        gap = 18
        total = cw * 5 + gap * 4
        x0 = W / 2 - total / 2
        cy = (96 + H - 88) / 2 - 10
        for k in range(5):
            x = x0 + k * (cw + gap)
            draw_card(d, x, cy - chh / 2, cw, chh, self.hand[k])
            if k in self.held:
                d.rounded_rectangle([x, cy + chh / 2 + 8, x + cw, cy + chh / 2 + 34], radius=6, fill=theme)
                d.text((x + cw / 2, cy + chh / 2 + 21), "HELD", font=F(18, "Bold"), fill=(10, 10, 14), anchor="mm")
        draw_footer(d, theme, self.bet, get_balance(self.author.id), status)
        return img

    async def _draw(self, interaction):
        if self.ended:
            await interaction.response.defer(); return
        if not self.drawn:
            for k in range(5):
                if k not in self.held:
                    self.hand[k] = self.deck.pop()
            self.drawn = True
            label, mult = poker_evaluate(self.hand)
            payout = self.bet * mult
            if payout > 0:
                settle(self.author.id, payout)
            delta = payout - self.bet
            self.ended = True
            for c in self.children:
                c.disabled = True
            img = self.render(status=f"{label} (x{mult}) · " + result_status(delta, payout))
            await show_result(interaction, self.author, "videopoker", self.bet, img)
            self.stop()


async def launch_videopoker(interaction, author, bet):
    view = VideoPokerView(author, bet)
    img = view.render(status="Pick cards to hold, then Draw")
    await interaction.response.edit_message(attachments=[img_file(img)], embed=game_embed("", C_INFO), view=view)
    view.message = interaction.message
GAME_LAUNCHERS["videopoker"] = launch_videopoker


# ==============================================================================
#  GAME COMMANDS  (each just opens the bet-setup screen)
# ==============================================================================

GAME_ALIASES = {
    "mines": [], "crash": [], "dice": [], "limbo": [], "plinko": [],
    "wheel": [], "slots": ["slot"], "keno": [], "diamonds": ["diamond", "gems"],
    "case": ["cases", "unbox"], "coinflip": ["cf", "flip"], "hilo": ["highlow", "hl"],
    "dragon": ["dragontower", "tower"], "chicken": [], "pump": ["balloon"],
    "blackjack": ["bj", "21"], "roulette": ["roul"], "baccarat": ["bacc"],
    "videopoker": ["vp", "poker"],
}


def _make_game_command(key):
    async def _cmd(ctx, bet: str = None):
        prefill = DEFAULT_BET
        if bet is not None:
            parsed = parse_bet(bet, get_balance(ctx.author.id))
            if parsed:
                prefill = parsed
        await open_bet_setup(ctx, key, prefill)
    _cmd.__name__ = f"game_{key}"
    return _cmd


for _key, _aliases in GAME_ALIASES.items():
    bot.command(name=_key, aliases=_aliases)(_make_game_command(_key))


# ==============================================================================
#  HELP
# ==============================================================================

LEVEL_RANK = {"user": 0, "admin": 1, "owner": 2}


def user_level(member):
    if is_owner_id(member.id):
        return "owner"
    perms = getattr(member, "guild_permissions", None)
    if perms is not None and perms.administrator:
        return "admin"
    return "user"


def _help_cats():
    """Each command: (usage, description, min level)."""
    p = PREFIX
    return [
        {"key": "games", "label": "Games", "emoji": "🎲", "color": C_INFO, "commands": [
            (f"{p}mines [bet]", "Reveal gems, avoid the mines, cash out anytime.", "user"),
            (f"{p}crash [bet]", "Cash out before the rocket crashes.", "user"),
            (f"{p}dice [bet]", "Roll over or under a target number.", "user"),
            (f"{p}limbo [bet]", "Pick a target multiplier and beat the roll.", "user"),
            (f"{p}plinko [bet]", "Drop a ball through the pegs into a multiplier.", "user"),
            (f"{p}wheel [bet]", "Spin the wheel of fortune.", "user"),
            (f"{p}slots [bet]", "Classic 3-reel slot machine.", "user"),
            (f"{p}keno [bet]", "Pick spots and match the draw.", "user"),
            (f"{p}diamonds [bet]", "Reveal 5 gems and match them for combos.", "user"),
            (f"{p}case [bet]", "Open a case for a random multiplier.", "user"),
            (f"{p}coinflip [bet]", "Heads or tails, double or nothing.", "user"),
            (f"{p}hilo [bet]", "Guess if the next card is higher or lower.", "user"),
            (f"{p}dragon [bet]", "Climb the Dragon Tower, avoid the dragons.", "user"),
            (f"{p}chicken [bet]", "Cross the road, cash out before you get hit.", "user"),
            (f"{p}pump [bet]", "Pump the balloon, cash out before it pops.", "user"),
            (f"{p}blackjack [bet]", "Beat the dealer to 21 (Hit / Stand / Double).", "user"),
            (f"{p}roulette [bet]", "Bet on a number, color or section.", "user"),
            (f"{p}baccarat [bet]", "Bet on Player, Banker or Tie.", "user"),
            (f"{p}videopoker [bet]", "Jacks or Better — hold cards and draw.", "user"),
        ]},
        {"key": "economy", "label": "Economy", "emoji": "💰", "color": C_GOLD, "commands": [
            (f"{p}balance [@user]", "Check your wallet (or someone else's).", "user"),
            (f"{p}daily", "Claim your daily reward with a streak bonus.", "user"),
            (f"{p}work", "Earn some chips on a short cooldown.", "user"),
            (f"{p}give @user <amount>", "Send chips to another player.", "user"),
            (f"{p}leaderboard", "See the richest players.", "user"),
            (f"{p}shop", "Browse items and roles for sale.", "user"),
            (f"{p}buy <id>", "Buy an item from the shop.", "user"),
            (f"{p}games", "Quick list of every game.", "user"),
            (f"{p}owners", "Show the configured bot owners.", "user"),
        ]},
        {"key": "admin", "label": "Admin & Owner", "emoji": "🔧", "color": C_GREY, "commands": [
            (f"{p}addmoney @user <amount>", "Add chips to a user.", "admin"),
            (f"{p}removemoney @user <amount>", "Remove chips from a user.", "admin"),
            (f"{p}setmoney @user <amount>", "Set a user's balance.", "admin"),
            (f"{p}resetbalance @user", "Reset a user to the starting balance.", "admin"),
            (f"{p}additem <price> [@role] <name>", "Add a shop item (optional role).", "admin"),
            (f"{p}delitem <id>", "Remove a shop item.", "admin"),
            (f"{p}wipeeconomy confirm", "Reset EVERYONE's balance — owner only.", "owner"),
        ]},
    ]


def visible_categories(level):
    rank = LEVEL_RANK[level]
    out = []
    for cat in _help_cats():
        cmds = [c for c in cat["commands"] if LEVEL_RANK[c[2]] <= rank]
        if cmds:
            out.append({**cat, "commands": cmds})
    return out


class HelpSelect(discord.ui.Select):
    def __init__(self, parent):
        options = [discord.SelectOption(label="🏠 Home", value="home",
                                        description="Back to the categories overview")]
        options += [
            discord.SelectOption(label=f"{c['emoji']} {c['label']}", value=str(i),
                                 description=f"{len(c['commands'])} command(s)")
            for i, c in enumerate(parent.cats)
        ]
        super().__init__(placeholder="📂 Choose a category…", options=options, row=0)
        self.parent = parent

    async def callback(self, interaction):
        try:
            v = self.values[0]
            self.parent.cat_index = None if v == "home" else int(v)
            self.parent.page = 0
            await self.parent.update(interaction)
        except Exception:
            try:
                await interaction.response.defer()
            except Exception:
                pass


class HelpPrev(discord.ui.Button):
    def __init__(self):
        super().__init__(label="◀ Prev", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction):
        v = self.view
        if v.cat_index is None or v.page <= 0:
            await interaction.response.defer()  # already first page → nothing
            return
        v.page -= 1
        await v.update(interaction)


class HelpNext(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Next ▶", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction):
        v = self.view
        if v.cat_index is None or v.page >= v._pages() - 1:
            await interaction.response.defer()  # already last page → nothing
            return
        v.page += 1
        await v.update(interaction)


class HelpView(discord.ui.View):
    def __init__(self, author, level):
        super().__init__(timeout=180)
        self.author = author
        self.level = level
        self.cats = visible_categories(level)
        self.cat_index = None  # None = home screen
        self.page = 0
        self.message = None
        self.select = HelpSelect(self)
        self.prev = HelpPrev()
        self.next = HelpNext()
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        self.add_item(self.select)
        if self.cat_index is not None:  # pagination buttons only inside a category
            self.add_item(self.prev)
            self.add_item(self.next)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(f"Run your own `{PREFIX}help` 🙂", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    def _cat(self):
        return self.cats[self.cat_index]

    def _pages(self):
        return max(1, math.ceil(len(self._cat()["commands"]) / 5))

    def _home_embed(self):
        e = discord.Embed(
            title="🎰 Casino — help",
            description=(f"Virtual {CURRENCY} {SYMBOL} only — no real money.\n"
                         f"Pick a category in the menu below to see its commands."),
            color=C_GOLD)
        lines = [f"{c['emoji']}  **{c['label']}** — {len(c['commands'])} command(s)" for c in self.cats]
        e.add_field(name="📂 Categories", value="\n".join(lines), inline=False)
        e.set_footer(text=f"prefix {PREFIX}  ·  you are: {self.level}")
        self.select.placeholder = "📂 Choose a category…"
        return e

    def _category_embed(self):
        cat = self._cat()
        pages = self._pages()
        self.page = max(0, min(self.page, pages - 1))
        chunk = cat["commands"][self.page * 5:self.page * 5 + 5]
        e = discord.Embed(title=f"{cat['emoji']}  {cat['label']}",
                          description=f"Virtual {CURRENCY} {SYMBOL} only — no real money.",
                          color=cat["color"])
        for usage, desc, _lvl in chunk:
            e.add_field(name=f"`{usage}`", value=desc, inline=False)
        e.set_footer(text=f"Page {self.page + 1}/{pages}  ·  {cat['label']}  ·  pick 🏠 Home to go back")
        self.select.placeholder = f"📂 {cat['label']}"
        return e

    def embed(self):
        return self._home_embed() if self.cat_index is None else self._category_embed()

    async def update(self, interaction):
        self._rebuild()
        await interaction.response.edit_message(embed=self.embed(), view=self)


@bot.command(name="help", aliases=["commands", "casino", "menu", "h"])
async def help_cmd(ctx):
    try:
        view = HelpView(ctx.author, user_level(ctx.author))
        view.message = await ctx.send(embed=view.embed(), view=view)
    except Exception:
        import traceback
        traceback.print_exc()  # shows the real error in the Railway logs
        # Plain text fallback so help always works even if the menu fails
        lvl = user_level(ctx.author)
        e = discord.Embed(title="🎰 Casino — commands",
                          description=f"Virtual {CURRENCY} {SYMBOL} only — no real money.",
                          color=C_GOLD)
        for cat in visible_categories(lvl):
            cmds = cat["commands"]
            for i in range(0, len(cmds), 8):
                part = cmds[i:i + 8]
                val = "\n".join(f"`{u}` — {d}" for u, d, _l in part)
                title = f"{cat['emoji']} {cat['label']}" + ("" if i == 0 else " (cont.)")
                e.add_field(name=title, value=val, inline=False)
        e.set_footer(text=f"prefix {PREFIX}")
        await ctx.send(embed=e)


@bot.command(name="games")
async def games_cmd(ctx):
    p = PREFIX
    lines = []
    for k in GAME_ALIASES:
        icon = THEMES[k][1]
        lines.append(f"{icon} `{p}{k}`")
    await ctx.send(embed=discord.Embed(title="🎲 Available games",
                                       description="  ".join(lines), color=C_INFO))


# ==============================================================================
#  EVENTS
# ==============================================================================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id: {bot.user.id})")
    print(f"Prefix: {PREFIX}  ·  Pillow: {'OK' if PIL_OK else 'MISSING'}  ·  {len(bot.guilds)} guild(s)")
    print(f"Owners configured: {sorted(OWNER_IDS) if OWNER_IDS else 'NONE (set CASINO_OWNERS)'}")
    try:
        await bot.change_presence(activity=discord.Game(name=f"{PREFIX}help · 🎰"))
    except Exception:
        pass


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⛔ You don't have permission to use that command."); return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument. See `{PREFIX}help`."); return
    if isinstance(error, (commands.BadArgument, commands.BadUnionArgument)):
        await ctx.send("❌ Invalid argument."); return
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Slow down — try again in {error.retry_after:.0f}s."); return
    if isinstance(error, commands.CheckFailure):
        return
    raise error


# ==============================================================================
#  RUN
# ==============================================================================

if __name__ == "__main__":
    if not PIL_OK:
        print("WARNING: Pillow is not installed. Run: pip install -U Pillow")
    if not TOKEN or TOKEN == "PASTE_YOUR_TOKEN_HERE":
        print("ERROR: set the DISCORD_TOKEN environment variable (or edit TOKEN in the file).")
    else:
        ensure_fonts()
        bot.run(TOKEN)
