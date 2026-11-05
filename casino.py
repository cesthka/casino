"""
================================================================================
  BOT CASINO — style Stake (monnaie VIRTUELLE uniquement, aucune valeur réelle)
================================================================================
Même système / même DA que les autres bots (Buyer > Sys > Owner > Whitelist).

19 jeux en images générées : Mines · Crash · Dice · Limbo · Plinko · Wheel ·
Keno · Diamonds · Cases · Coinflip · Hi-Lo · Dragon Tower · Chicken · Pump ·
Slots · Blackjack · Roulette · Baccarat · Video Poker.

Garanties :
  - Provably fair (HMAC-SHA256 serveur/client/nonce, comme Stake) : =fair, =seed, =verify
  - Argent atomique : mise débitée en base AVANT de jouer, gain versé UNE SEULE fois
    (double-clic, spam de boutons, latence : impossible de doubler un gain)
  - Parties abandonnées : encaissement / remboursement automatique au timeout
  - Redémarrage du bot : les mises des parties en cours sont remboursées
  - RTP de chaque jeu vérifié et calé (le script d'origine avait des jeux à 110-185 %)
  - VIP + rakeback, profils, historique, classements, logs des gros gains

Variables d'environnement : TOKEN (ou DISCORD_TOKEN), DATA_DIR
Dépendances : discord.py>=2.3.2, Pillow
================================================================================
"""

import discord
from discord.ext import commands
import os
import re
import sys
import json
import math
import time
import hmac
import hashlib
import secrets
import asyncio
import sqlite3
import logging
import functools
import traceback
import urllib.request
from io import BytesIO
from itertools import product
from datetime import datetime, timezone

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("[ERREUR CRITIQUE] Pillow n'est pas installé : ajoute 'Pillow' dans requirements.txt.")
    sys.exit(1)

# ========================= CONFIG =========================
BOT_TOKEN = os.environ.get("TOKEN") or os.environ.get("DISCORD_TOKEN")
if not BOT_TOKEN:
    print("[ERREUR CRITIQUE] La variable d'environnement TOKEN n'est pas définie.")
    sys.exit(1)

DATA_DIR = os.environ.get("DATA_DIR")
if not DATA_DIR:
    print("[ERREUR CRITIQUE] DATA_DIR non défini. Configure DATA_DIR=/data dans Railway.")
    sys.exit(1)
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "casino.db")
FONTS_DIR = os.path.join(DATA_DIR, "fonts")

DEFAULT_BUYER_IDS = [142365250803466240]
DEFAULT_PREFIX = "$"

SYMBOL = "🪙"
HOUSE_EDGE = 0.01
GAME_TIMEOUT = 180          # secondes d'inactivité avant encaissement / remboursement auto
STALE_GAME_SECONDS = 1800   # une partie "fantôme" plus vieille que ça est remboursée

DEFAULT_SETTINGS = {
    "min_bet": 1, "max_bet": 0, "start_balance": 1000,
    "daily_amount": 1000, "daily_streak": 250, "work_min": 50, "work_max": 350,
    "work_cooldown": 600, "bigwin_mult": 10,
}
SETTINGS_META = {
    "min_bet":       ("Mise minimum", 1, 1_000_000),
    "max_bet":       ("Mise maximum (0 = illimitée)", 0, 10**12),
    "start_balance": ("Solde de départ", 0, 10**9),
    "daily_amount":  ("Daily · montant de base", 0, 10**9),
    "daily_streak":  ("Daily · bonus par jour de série", 0, 10**9),
    "work_min":      ("Work · gain minimum", 0, 10**9),
    "work_max":      ("Work · gain maximum", 0, 10**9),
    "work_cooldown": ("Work · cooldown (secondes)", 0, 86400),
    "bigwin_mult":   ("Log gros gain à partir de x", 2, 1_000_000),
}

VIP_LEVELS = [  # (misé total requis, nom, emoji, % du house edge reversé en rakeback)
    (0,          "Aucun",   "⚪", 0.00),
    (10_000,     "Bronze",  "🥉", 0.05),
    (50_000,     "Argent",  "🥈", 0.08),
    (250_000,    "Or",      "🥇", 0.10),
    (1_000_000,  "Platine", "💠", 0.12),
    (5_000_000,  "Diamant", "💎", 0.15),
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%d/%m/%Y %H:%M:%S")
log = logging.getLogger("casino")


# ========================= JEUX (métadonnées) =========================
# key: (nom, couleur RGB, emoji, description, catégorie)
GAMES = {
    "mines":      ("Mines",        (39, 174, 96),  "💣", "Révèle des gemmes, évite les mines, encaisse quand tu veux.", "originals"),
    "crash":      ("Crash",        (231, 76, 60),  "🚀", "Encaisse avant que la fusée n'explose (auto-cashout possible).", "originals"),
    "dice":       ("Dice",         (52, 152, 219), "🎲", "Au-dessus ou en dessous d'une cible.", "originals"),
    "limbo":      ("Limbo",        (155, 89, 182), "🎯", "Choisis un multiplicateur cible et bats le tirage.", "originals"),
    "plinko":     ("Plinko",       (241, 196, 15), "🟡", "Lâche la bille à travers les clous.", "originals"),
    "wheel":      ("Wheel",        (26, 188, 156), "🎡", "Fais tourner la roue (3 niveaux de risque).", "originals"),
    "keno":       ("Keno",         (52, 152, 219), "🎱", "Choisis tes numéros, 10 sont tirés sur 40.", "originals"),
    "diamonds":   ("Diamonds",     (155, 89, 182), "💎", "5 gemmes : fais des combinaisons.", "originals"),
    "case":       ("Cases",        (243, 156, 18), "📦", "Ouvre une caisse au multiplicateur aléatoire.", "originals"),
    "coinflip":   ("Coinflip",     (241, 196, 15), "🪙", "Pile ou face, quitte ou double.", "originals"),
    "hilo":       ("Hi-Lo",        (39, 174, 96),  "🃏", "Plus haut ou plus bas ? Enchaîne et encaisse.", "originals"),
    "dragon":     ("Dragon Tower", (211, 84, 0),   "🐉", "Grimpe la tour sans tomber sur un dragon.", "originals"),
    "chicken":    ("Chicken",      (243, 156, 18), "🐔", "Traverse la route, encaisse avant de te faire écraser.", "originals"),
    "pump":       ("Pump",         (231, 76, 60),  "🎈", "Gonfle le ballon, encaisse avant qu'il éclate.", "originals"),
    "slots":      ("Slots",        (230, 126, 34), "🎰", "Machine à sous 3 rouleaux.", "casino"),
    "blackjack":  ("Blackjack",    (192, 57, 43),  "♠️", "Bats le croupier (Hit / Stand / Double), BJ payé 3:2.", "casino"),
    "roulette":   ("Roulette",     (192, 57, 43),  "🔴", "Roulette européenne : numéro, couleur, douzaine…", "casino"),
    "baccarat":   ("Baccarat",     (142, 68, 173), "🀄", "Joueur, Banquier ou Égalité.", "casino"),
    "videopoker": ("Video Poker",  (41, 128, 185), "🎴", "Jacks or Better : garde tes cartes et tire.", "casino"),
}
GAME_ALIASES = {
    "mines": ["mine"], "crash": [], "dice": ["de"], "limbo": [], "plinko": [], "wheel": ["roue"],
    "keno": [], "diamonds": ["diamond", "gems"], "case": ["cases", "caisse"], "coinflip": ["cf", "flip", "pf"],
    "hilo": ["hl", "highlow"], "dragon": ["tower", "dragontower"], "chicken": ["poulet"], "pump": ["ballon"],
    "slots": ["slot", "machine"], "blackjack": ["bj", "21"], "roulette": ["roul"], "baccarat": ["bacc"],
    "videopoker": ["vp", "poker"],
}


# ========================= DATABASE =========================

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS ranks (user_id TEXT PRIMARY KEY, rank INTEGER NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS log_channels (guild_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS allowed_channels (guild_id TEXT NOT NULL, channel_id TEXT NOT NULL, PRIMARY KEY (guild_id, channel_id))")
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0,
        last_daily INTEGER NOT NULL DEFAULT 0, last_work INTEGER NOT NULL DEFAULT 0, streak INTEGER NOT NULL DEFAULT 0,
        wagered INTEGER NOT NULL DEFAULT 0, won INTEGER NOT NULL DEFAULT 0, profit INTEGER NOT NULL DEFAULT 0,
        games INTEGER NOT NULL DEFAULT 0, biggest_win INTEGER NOT NULL DEFAULT 0, rakeback REAL NOT NULL DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS active_games (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, game TEXT NOT NULL,
        bet INTEGER NOT NULL, base_bet INTEGER NOT NULL, ts INTEGER NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS bets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, game TEXT NOT NULL,
        bet INTEGER NOT NULL, payout INTEGER NOT NULL, mult REAL NOT NULL, nonce INTEGER, ts INTEGER NOT NULL)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_bets_user ON bets (user_id, ts DESC)")
    c.execute("""CREATE TABLE IF NOT EXISTS seeds (
        user_id TEXT PRIMARY KEY, server_seed TEXT NOT NULL, client_seed TEXT NOT NULL, nonce INTEGER NOT NULL DEFAULT 0,
        prev_server TEXT, prev_client TEXT, prev_nonce INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS shop (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, price INTEGER NOT NULL,
        role_id TEXT, description TEXT)""")
    c.execute("INSERT OR IGNORE INTO config VALUES ('prefix', ?)", (DEFAULT_PREFIX,))
    c.execute("INSERT OR REPLACE INTO config VALUES ('buyer_ids', ?)", (json.dumps([str(i) for i in DEFAULT_BUYER_IDS]),))
    conn.commit()
    conn.close()


def db_exec(sql, params=()):
    conn = get_db()
    cur = conn.execute(sql, params)
    conn.commit()
    rc, lid = cur.rowcount, cur.lastrowid
    conn.close()
    return rc, lid


def db_all(sql, params=()):
    conn = get_db()
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return rows


def db_one(sql, params=()):
    rows = db_all(sql, params)
    return rows[0] if rows else None


_config_cache = {}
_prefix_cache = {"value": None}


def get_config(key):
    if key not in _config_cache:
        row = db_one("SELECT value FROM config WHERE key = ?", (key,))
        _config_cache[key] = row["value"] if row else None
    return _config_cache[key]


def set_config(key, value):
    db_exec("INSERT OR REPLACE INTO config VALUES (?, ?)", (key, str(value)))
    _config_cache[key] = str(value)
    if key == "prefix":
        _prefix_cache["value"] = str(value)


def get_prefix_cached():
    if _prefix_cache["value"] is None:
        _prefix_cache["value"] = get_config("prefix") or DEFAULT_PREFIX
    return _prefix_cache["value"]


def setting(key):
    raw = get_config(f"set_{key}")
    try:
        return int(raw) if raw is not None else DEFAULT_SETTINGS[key]
    except ValueError:
        return DEFAULT_SETTINGS[key]


# ---- Rangs ----
_rank_cache = {}
_buyer_cache = set()


def load_ranks():
    _rank_cache.clear()
    for r in db_all("SELECT user_id, rank FROM ranks"):
        _rank_cache[r["user_id"]] = r["rank"]
    _buyer_cache.clear()
    try:
        _buyer_cache.update(str(i) for i in json.loads(get_config("buyer_ids") or "[]"))
    except (json.JSONDecodeError, TypeError):
        pass


def get_rank_db(user_id):
    uid = str(user_id)
    return 4 if uid in _buyer_cache else _rank_cache.get(uid, 0)


def set_rank_db(user_id, rank):
    uid = str(user_id)
    if rank == 0:
        db_exec("DELETE FROM ranks WHERE user_id = ?", (uid,))
        _rank_cache.pop(uid, None)
    else:
        db_exec("INSERT OR REPLACE INTO ranks VALUES (?, ?)", (uid, rank))
        _rank_cache[uid] = rank


def get_ranks_by_level(level):
    return [uid for uid, r in _rank_cache.items() if r == level]


def rank_name(level):
    return {4: "Buyer", 3: "Sys", 2: "Owner", 1: "Whitelist", 0: "Joueur"}.get(level, "Joueur")


def has_min_rank(user_id, minimum):
    return get_rank_db(user_id) >= minimum


# ========================= ÉCONOMIE (atomique) =========================

def ensure_user(uid):
    db_exec("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, ?)", (str(uid), setting("start_balance")))


def get_user(uid):
    ensure_user(uid)
    return db_one("SELECT * FROM users WHERE user_id = ?", (str(uid),))


def get_balance(uid):
    return get_user(uid)["balance"]


def credit(uid, amount):
    ensure_user(uid)
    db_exec("UPDATE users SET balance = balance + ? WHERE user_id = ?", (int(amount), str(uid)))


def debit(uid, amount):
    """Retire `amount` UNIQUEMENT si le solde suffit. Retourne True/False (atomique)."""
    ensure_user(uid)
    rc, _ = db_exec("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                    (int(amount), str(uid), int(amount)))
    return rc == 1


def set_balance(uid, value):
    ensure_user(uid)
    db_exec("UPDATE users SET balance = ? WHERE user_id = ?", (max(0, int(value)), str(uid)))


def vip_for(wagered):
    lvl = VIP_LEVELS[0]
    for entry in VIP_LEVELS:
        if wagered >= entry[0]:
            lvl = entry
    return lvl


def next_vip(wagered):
    for entry in VIP_LEVELS:
        if wagered < entry[0]:
            return entry
    return None


def active_game_of(uid):
    return db_one("SELECT * FROM active_games WHERE user_id = ?", (str(uid),))


def start_game(uid, key, bet):
    """Débite la mise et ouvre la partie. Retourne (game_id, None) ou (None, message d'erreur)."""
    bet = int(bet)
    cur = active_game_of(uid)
    if cur:
        if now_ts() - cur["ts"] > STALE_GAME_SECONDS:
            refund_game(cur["id"])
        else:
            return None, f"Tu as déjà une partie de **{GAMES.get(cur['game'], (cur['game'],))[0]}** en cours. Termine-la d'abord."
    mn, mx = setting("min_bet"), setting("max_bet")
    if bet < mn:
        return None, f"Mise minimum : {money(mn)}."
    if mx and bet > mx:
        return None, f"Mise maximum : {money(mx)}."
    if not debit(uid, bet):
        return None, f"Solde insuffisant : tu as {money(get_balance(uid))}."
    _, gid = db_exec("INSERT INTO active_games (user_id, game, bet, base_bet, ts) VALUES (?, ?, ?, ?, ?)",
                     (str(uid), key, bet, bet, now_ts()))
    return gid, None


def raise_bet(game_id, uid, extra):
    """Mise supplémentaire (double au blackjack). Atomique."""
    if not db_one("SELECT 1 FROM active_games WHERE id = ?", (game_id,)):
        return False
    if not debit(uid, extra):
        return False
    db_exec("UPDATE active_games SET bet = bet + ? WHERE id = ?", (int(extra), game_id))
    return True


def settle_game(game_id, payout, mult, nonce):
    """Clôture la partie et verse le gain. Idempotent : un 2e appel ne verse RIEN."""
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM active_games WHERE id = ?", (game_id,)).fetchone()
        if row is None:
            conn.rollback()
            return None
        conn.execute("DELETE FROM active_games WHERE id = ?", (game_id,))
        uid, bet, payout = row["user_id"], row["bet"], int(payout)
        u = conn.execute("SELECT wagered FROM users WHERE user_id = ?", (uid,)).fetchone()
        rate = vip_for(u["wagered"] if u else 0)[3]
        conn.execute(
            "UPDATE users SET balance = balance + ?, wagered = wagered + ?, won = won + ?, profit = profit + ?, "
            "games = games + 1, biggest_win = MAX(biggest_win, ?), rakeback = rakeback + ? WHERE user_id = ?",
            (payout, bet, payout, payout - bet, payout - bet, bet * HOUSE_EDGE * rate, uid))
        conn.execute("INSERT INTO bets (user_id, game, bet, payout, mult, nonce, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (uid, row["game"], bet, payout, float(mult), nonce, now_ts()))
        conn.commit()
        return {"bet": bet, "payout": payout, "user_id": uid, "game": row["game"]}
    finally:
        conn.close()


def refund_game(game_id):
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM active_games WHERE id = ?", (game_id,)).fetchone()
        if row is None:
            conn.rollback()
            return False
        conn.execute("DELETE FROM active_games WHERE id = ?", (game_id,))
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (row["bet"], row["user_id"]))
        conn.commit()
        return True
    finally:
        conn.close()


def refund_all_active():
    n = 0
    for r in db_all("SELECT id FROM active_games"):
        if refund_game(r["id"]):
            n += 1
    return n


# ========================= PROVABLY FAIR =========================

def _new_server_seed():
    return secrets.token_hex(32)


def sha256(s):
    return hashlib.sha256(s.encode()).hexdigest()


def get_seeds(uid):
    row = db_one("SELECT * FROM seeds WHERE user_id = ?", (str(uid),))
    if row is None:
        db_exec("INSERT OR IGNORE INTO seeds (user_id, server_seed, client_seed, nonce) VALUES (?, ?, ?, 0)",
                (str(uid), _new_server_seed(), secrets.token_hex(8)))
        row = db_one("SELECT * FROM seeds WHERE user_id = ?", (str(uid),))
    return row


def next_rng(uid):
    """Consomme un nonce et retourne le RNG de la partie."""
    s = get_seeds(uid)
    db_exec("UPDATE seeds SET nonce = nonce + 1 WHERE user_id = ?", (str(uid),))
    return FairRNG(s["server_seed"], s["client_seed"], s["nonce"])


def rotate_seeds(uid, new_client=None):
    s = get_seeds(uid)
    db_exec("UPDATE seeds SET prev_server = ?, prev_client = ?, prev_nonce = ?, server_seed = ?, client_seed = ?, nonce = 0 "
            "WHERE user_id = ?", (s["server_seed"], s["client_seed"], s["nonce"], _new_server_seed(),
                                  (new_client or secrets.token_hex(8))[:64], str(uid)))
    return s


class FairRNG:
    """Floats déterministes : HMAC_SHA256(server_seed, f"{client_seed}:{nonce}:{cursor}"),
    4 octets par float (même méthode que Stake). Vérifiable avec =verify."""

    def __init__(self, server_seed, client_seed, nonce):
        self.server_seed, self.client_seed, self.nonce = server_seed, client_seed, nonce
        self.cursor = 0
        self._buf = []

    def random(self):
        if not self._buf:
            digest = hmac.new(self.server_seed.encode(), f"{self.client_seed}:{self.nonce}:{self.cursor}".encode(),
                              hashlib.sha256).digest()
            self.cursor += 1
            for i in range(0, 32, 4):
                b = digest[i:i + 4]
                self._buf.append(b[0] / 256 + b[1] / 256 ** 2 + b[2] / 256 ** 3 + b[3] / 256 ** 4)
        return self._buf.pop(0)

    def randrange(self, n):
        return min(n - 1, int(self.random() * n))

    def choice(self, seq):
        return seq[self.randrange(len(seq))]

    def shuffle(self, items):
        items = list(items)
        for i in range(len(items) - 1, 0, -1):
            j = self.randrange(i + 1)
            items[i], items[j] = items[j], items[i]
        return items

    def weighted(self, items, weights):
        total = sum(weights)
        r = self.random() * total
        acc = 0
        for it, w in zip(items, weights):
            acc += w
            if r < acc:
                return it
        return items[-1]


def crash_point_from(f):
    """Multiplicateur type Stake : 1% d'edge, P(≥ x) = 0.99 / x."""
    return max(1.0, math.floor((1 - HOUSE_EDGE) / (1 - f) * 100) / 100)


# ========================= HELPERS =========================

def now_ts():
    return int(time.time())


def fmt(n):
    return f"{int(n):,}".replace(",", " ")


def money(n):
    return f"**{fmt(n)}** {SYMBOL}"


def payout_of(bet, mult):
    return int(math.floor(bet * mult + 1e-9))


def embed_color():
    return 0x2b2d31


def success_embed(title, desc=""):
    return discord.Embed(title=title, description=desc, color=0x43b581)


def error_embed(title, desc=""):
    return discord.Embed(title=title, description=desc, color=0xf04747)


def info_embed(title, desc=""):
    return discord.Embed(title=title, description=desc, color=embed_color())


def denied(min_rank):
    if min_rank >= 4:
        return error_embed("❌ Permission refusée", "Seul le **Buyer** peut utiliser cette commande.")
    return error_embed("❌ Permission refusée", f"**{rank_name(min_rank)}+** requis.")


async def gate(ctx, min_rank):
    r = get_rank_db(ctx.author.id)
    if r >= min_rank:
        return True
    if r == 0:
        try:
            await ctx.message.add_reaction("🔒")
        except discord.HTTPException:
            pass
    else:
        await ctx.send(embed=denied(min_rank))
    return False


def apply_thumbnail(em, guild):
    if guild and getattr(guild, "icon", None):
        try:
            em.set_thumbnail(url=guild.icon.url)
        except (AttributeError, TypeError):
            pass


def parse_amount(arg, balance):
    if arg is None:
        return None
    a = str(arg).strip().lower().replace(",", ".").replace(" ", "")
    if a in ("all", "max", "tout", "allin"):
        return balance if balance > 0 else None
    if a in ("half", "moitie", "moitié", "h"):
        return balance // 2 if balance >= 2 else None
    if a.endswith("%"):
        try:
            pct = float(a[:-1])
        except ValueError:
            return None
        return max(1, int(balance * pct / 100)) if balance > 0 and 0 < pct <= 100 else None
    mult = 1
    if a and a[-1] in "kmb":
        mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[a[-1]]
        a = a[:-1]
    try:
        val = int(float(a) * mult)
    except ValueError:
        return None
    return val if val > 0 else None


async def resolve_user_or_id(ctx, user_input):
    if not user_input:
        return None, None
    raw = user_input.strip()
    try:
        user_id = int(raw.strip("<@!>"))
    except ValueError:
        try:
            m = await commands.MemberConverter().convert(ctx, raw)
            return m, m.id
        except commands.CommandError:
            pass
        try:
            u = await commands.UserConverter().convert(ctx, raw)
            return u, u.id
        except commands.CommandError:
            return None, None
    if ctx.guild:
        m = ctx.guild.get_member(user_id)
        if m:
            return m, user_id
    try:
        return await bot.fetch_user(user_id), user_id
    except discord.HTTPException:
        return None, user_id


def format_user_display(display_obj, user_id):
    if display_obj is not None:
        return f"{display_obj.mention} ({display_obj.id})"
    return f"<@{user_id}> ({user_id})"


# ========================= TABLES DE GAINS (RTP calés automatiquement) =========================

def _scale(table, probs, target):
    ev = sum(m * p for m, p in zip(table, probs))
    k = target / ev if ev else 1
    return [round(m * k, 2) for m in table]


def binom_probs(n):
    return [math.comb(n, k) / 2 ** n for k in range(n + 1)]


# Plinko (valeurs de référence Stake), recalées à 99 %
_PLINKO_BASE = {
    8:  {"low": [5.6, 2.1, 1.1, 1, 0.5, 1, 1.1, 2.1, 5.6],
         "medium": [13, 3, 1.3, 0.7, 0.4, 0.7, 1.3, 3, 13],
         "high": [29, 4, 1.5, 0.3, 0.2, 0.3, 1.5, 4, 29]},
    12: {"low": [10, 3, 1.6, 1.4, 1.1, 1, 0.5, 1, 1.1, 1.4, 1.6, 3, 10],
         "medium": [33, 11, 4, 2, 1.1, 0.6, 0.3, 0.6, 1.1, 2, 4, 11, 33],
         "high": [170, 24, 8.1, 2, 0.7, 0.2, 0.2, 0.2, 0.7, 2, 8.1, 24, 170]},
    16: {"low": [16, 9, 2, 1.4, 1.4, 1.2, 1.1, 1, 0.5, 1, 1.1, 1.2, 1.4, 1.4, 2, 9, 16],
         "medium": [110, 41, 10, 5, 3, 1.5, 1, 0.5, 0.3, 0.5, 1, 1.5, 3, 5, 10, 41, 110],
         "high": [1000, 130, 26, 9, 4, 2, 0.2, 0.2, 0.2, 0.2, 0.2, 2, 4, 9, 26, 130, 1000]},
}
PLINKO = {rows: {risk: _scale(t, binom_probs(rows), 0.99) for risk, t in risks.items()}
          for rows, risks in _PLINKO_BASE.items()}

# Wheel : 20 segments, RTP exact 99 %
WHEEL = {
    "low":    [1.5, 1.2, 1.2, 0, 1.2, 1.2, 1.2, 0, 1.2, 1.2, 1.5, 1.2, 1.2, 0, 1.2, 1.2, 1.2, 0, 1.2, 1.2],
    "medium": [0, 1.5, 0, 2, 0, 1.5, 0, 3, 0, 1.5, 0, 2, 0, 1.5, 0, 3, 0, 2, 0, 1.8],
    "high":   [0] * 19 + [19.8],
}

# Keno : 40 numéros, 10 tirés. Tables de référence recalées à 97 %.
_KENO_BASE = {
    1: [0, 3.96], 2: [0, 1.9, 4.5], 3: [0, 1, 3.1, 10.4], 4: [0, 0.8, 1.8, 5, 22.5],
    5: [0, 0.25, 1.4, 4.1, 16.5, 36], 6: [0, 0, 1, 3.68, 7, 16.5, 40], 7: [0, 0, 0.47, 3, 4.5, 14, 31, 60],
    8: [0, 0, 0, 2.2, 4, 13, 22, 55, 70], 9: [0, 0, 0, 1.55, 3, 8, 15, 44, 60, 85],
    10: [0, 0, 0, 1.4, 2.25, 4.5, 8, 17, 50, 80, 100],
}


def keno_probs(spots):
    return [math.comb(spots, h) * math.comb(40 - spots, 10 - h) / math.comb(40, 10) for h in range(spots + 1)]


KENO = {s: _scale(t, keno_probs(s), 0.97) for s, t in _KENO_BASE.items()}

# Diamonds : 7 couleurs, 5 gemmes. Probabilités exactes (7^5 tirages), recalées à 98 %.
DIAMOND_PATTERNS = [((5,), "5 identiques", 50), ((4, 1), "Carré", 5), ((3, 2), "Full", 4), ((3, 1, 1), "Brelan", 3),
                    ((2, 2, 1), "Deux paires", 2), ((2, 1, 1, 1), "Paire", 0.1), ((1, 1, 1, 1, 1), "Rien", 0)]


def _diamond_probs():
    counts = {p[0]: 0 for p in DIAMOND_PATTERNS}
    for draw in product(range(7), repeat=5):
        shape = tuple(sorted((draw.count(g) for g in set(draw)), reverse=True))
        counts[shape] += 1
    return [counts[p[0]] / 7 ** 5 for p in DIAMOND_PATTERNS]


_DM = _scale([p[2] for p in DIAMOND_PATTERNS], _diamond_probs(), 0.98)
DIAMONDS = {p[0]: (p[1], m) for p, m in zip(DIAMOND_PATTERNS, _DM)}

# Cases : poids fixes, multiplicateurs recalés à 96 %
_CASE_W = [35, 22, 14, 10, 7, 5, 3, 2, 1, 0.4]
CASE_MULTS = _scale([0, 0.4, 0.8, 1.2, 1.6, 2.5, 4, 8, 20, 75], [w / sum(_CASE_W) for w in _CASE_W], 0.96)

# Slots : probabilités exactes sur 7^3 combinaisons, recalées à 96 %
SLOT_SYMBOLS = ["cherry", "lemon", "grape", "bell", "star", "diamond", "seven"]
SLOT_WEIGHTS = [28, 24, 18, 14, 9, 5, 2]
_SLOT_TRIPLE_BASE = [8, 14, 20, 30, 50, 100, 250]
_SLOT_TWO_CHERRY_BASE = 2


def _slots_ev(triple, two_cherry):
    tw = sum(SLOT_WEIGHTS)
    ev = 0
    for a, b, c in product(range(7), repeat=3):
        p = SLOT_WEIGHTS[a] * SLOT_WEIGHTS[b] * SLOT_WEIGHTS[c] / tw ** 3
        ev += p * slot_mult([a, b, c], triple, two_cherry)
    return ev


def slot_mult(reels, triple, two_cherry):
    if reels[0] == reels[1] == reels[2]:
        return triple[reels[0]]
    if reels.count(0) == 2:
        return two_cherry
    return 0


_k = 0.96 / _slots_ev(_SLOT_TRIPLE_BASE, _SLOT_TWO_CHERRY_BASE)
SLOT_TRIPLE = [round(m * _k, 2) for m in _SLOT_TRIPLE_BASE]
SLOT_TWO_CHERRY = round(_SLOT_TWO_CHERRY_BASE * _k, 2)


# ========================= MOTEUR D'IMAGES =========================

FONT_URLS = {w: f"https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-{w}.ttf"
             for w in ("ExtraBold", "Bold", "SemiBold", "Medium", "Regular")}
_SYS_FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
_FONT_CACHE = {}


def ensure_fonts():
    os.makedirs(FONTS_DIR, exist_ok=True)
    for w, url in FONT_URLS.items():
        path = os.path.join(FONTS_DIR, f"Poppins-{w}.ttf")
        if os.path.exists(path) and os.path.getsize(path) > 10_000:
            continue
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                data = r.read()
            with open(path, "wb") as f:
                f.write(data)
        except Exception as e:
            log.warning(f"Police {w} non téléchargée ({e}) : police de secours utilisée.")


_FALLBACK_FONT = {"used": False}


def F(size, weight="Regular"):
    key = (size, weight)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    font = None
    for path in [os.path.join(FONTS_DIR, f"Poppins-{weight}.ttf")] + _SYS_FONTS:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                break
            except OSError:
                continue
    if font is None:
        _FALLBACK_FONT["used"] = True
        try:
            font = ImageFont.load_default(size=size)
        except TypeError:
            font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _ascii(text):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", str(text)) if not unicodedata.combining(c))


class SafeDraw(ImageDraw.ImageDraw):
    """Si la police de secours (sans accents) est utilisée, on retire les accents pour éviter les carrés."""

    def text(self, xy, text, *a, **kw):
        return super().text(xy, _ascii(text) if _FALLBACK_FONT["used"] else text, *a, **kw)

    def textlength(self, text, *a, **kw):
        return super().textlength(_ascii(text) if _FALLBACK_FONT["used"] else text, *a, **kw)


W, H = 880, 500
WHITE = (255, 255, 255)
GREY = (170, 178, 190)
DARK = (40, 44, 52)
RED = (231, 76, 60)
GREEN = (46, 204, 113)
GOLD = (241, 196, 15)
CY = (96 + H - 88) / 2
_BG_CACHE = {}


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _background(accent):
    if accent not in _BG_CACHE:
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)
        c1, c2 = _mix(accent, (20, 20, 26), 0.82), (10, 10, 14)
        for y in range(H):
            d.line([(0, y), (W, y)], fill=_mix(c1, c2, y / (H - 1)))
        d.rectangle([0, 0, W, 6], fill=accent)
        d.rounded_rectangle([34, 92, W - 34, H - 88], radius=22, outline=_mix(accent, (255, 255, 255), 0.1), width=2)
        _BG_CACHE[accent] = img
    return _BG_CACHE[accent].copy()


def base_canvas(accent, title):
    img = _background(accent)
    d = SafeDraw(img)
    d.text((38, 26), title, font=F(34, "ExtraBold"), fill=WHITE)
    return img, d


def draw_footer(d, accent, bet, balance, status, status_color=None):
    y = H - 70
    d.line([(40, y), (W - 40, y)], fill=(60, 64, 72), width=1)
    d.text((40, y + 12), f"Mise  {fmt(bet)}", font=F(22, "SemiBold"), fill=WHITE)
    txt = f"Solde  {fmt(balance)}"
    d.text((W - 40 - d.textlength(txt, font=F(22, "SemiBold")), y + 12), txt, font=F(22, "SemiBold"), fill=GREY)
    if status:
        d.text((W - 40, 46), status, font=F(20, "SemiBold"), fill=status_color or accent, anchor="rm")


def to_file(img, name="game.png"):
    buf = BytesIO()
    img.save(buf, "PNG", optimize=False)
    buf.seek(0)
    return discord.File(buf, filename=name)


def _gem(d, cx, cy, s, col):
    d.polygon([(cx, cy - s), (cx + s, cy), (cx, cy + s), (cx - s, cy)], fill=col, outline=(15, 15, 18))
    d.polygon([(cx, cy - s), (cx + s * 0.45, cy - s * 0.1), (cx, cy + s * 0.3), (cx - s * 0.45, cy - s * 0.1)],
              fill=_mix(col, WHITE, 0.35))


def _bomb(d, cx, cy, s):
    d.ellipse([cx - s, cy - s, cx + s, cy + s], fill=(25, 25, 30), outline=RED, width=2)
    d.line([(cx + s * 0.5, cy - s * 0.8), (cx + s * 0.9, cy - s * 1.3)], fill=(200, 140, 60), width=3)
    d.ellipse([cx + s * 0.8, cy - s * 1.5, cx + s * 1.1, cy - s * 1.2], fill=GOLD)


def _star(d, cx, cy, r, col):
    pts = []
    for k in range(10):
        ang = -math.pi / 2 + k * math.pi / 5
        rr = r if k % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    d.polygon(pts, fill=col)


def draw_suit(d, cx, cy, s, suit, col):
    if suit == "D":
        d.polygon([(cx, cy - s), (cx + s * 0.75, cy), (cx, cy + s), (cx - s * 0.75, cy)], fill=col)
    elif suit == "H":
        r = s * 0.52
        d.ellipse([cx - 2 * r, cy - s * 0.65, cx, cy - s * 0.65 + 2 * r], fill=col)
        d.ellipse([cx, cy - s * 0.65, cx + 2 * r, cy - s * 0.65 + 2 * r], fill=col)
        d.polygon([(cx - 2 * r + 1, cy - s * 0.1), (cx + 2 * r - 1, cy - s * 0.1), (cx, cy + s)], fill=col)
    elif suit == "S":
        r = s * 0.52
        d.ellipse([cx - 2 * r, cy - s * 0.35, cx, cy - s * 0.35 + 2 * r], fill=col)
        d.ellipse([cx, cy - s * 0.35, cx + 2 * r, cy - s * 0.35 + 2 * r], fill=col)
        d.polygon([(cx - 2 * r + 1, cy + s * 0.2), (cx + 2 * r - 1, cy + s * 0.2), (cx, cy - s)], fill=col)
        d.polygon([(cx, cy + s * 0.2), (cx - s * 0.35, cy + s), (cx + s * 0.35, cy + s)], fill=col)
    else:  # C
        r = s * 0.42
        for ox, oy in ((0, -s * 0.48), (-s * 0.5, s * 0.12), (s * 0.5, s * 0.12)):
            d.ellipse([cx + ox - r, cy + oy - r, cx + ox + r, cy + oy + r], fill=col)
        d.polygon([(cx, cy), (cx - s * 0.35, cy + s), (cx + s * 0.35, cy + s)], fill=col)


RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["S", "H", "D", "C"]


def draw_card(d, x, y, w, h, card, face_up=True, glow=None):
    if glow:
        d.rounded_rectangle([x - 4, y - 4, x + w + 4, y + h + 4], radius=14, outline=glow, width=3)
    if not face_up:
        d.rounded_rectangle([x, y, x + w, y + h], radius=12, fill=(40, 52, 88), outline=(20, 20, 24), width=2)
        d.rounded_rectangle([x + 8, y + 8, x + w - 8, y + h - 8], radius=8, fill=(28, 38, 70), outline=(90, 110, 170), width=2)
        _gem(d, x + w / 2, y + h / 2, min(w, h) * 0.18, (90, 110, 170))
        return
    d.rounded_rectangle([x, y, x + w, y + h], radius=12, fill=(245, 246, 248), outline=(20, 20, 24), width=2)
    rank, suit = card
    col = (200, 40, 40) if suit in ("H", "D") else (25, 25, 30)
    d.text((x + 9, y + 4), rank, font=F(int(h * 0.24), "Bold"), fill=col)
    draw_suit(d, x + 9 + h * 0.07, y + h * 0.36, h * 0.07, suit, col)
    draw_suit(d, x + w / 2 + w * 0.08, y + h * 0.62, h * 0.17, suit, col)


def draw_slot_symbol(d, sym, cx, cy, s):
    if sym == "cherry":
        d.line([(cx - s * 0.3, cy), (cx + s * 0.1, cy - s * 0.8)], fill=(60, 140, 60), width=4)
        d.line([(cx + s * 0.35, cy + s * 0.05), (cx + s * 0.1, cy - s * 0.8)], fill=(60, 140, 60), width=4)
        for ox in (-s * 0.35, s * 0.35):
            d.ellipse([cx + ox - s * 0.35, cy - s * 0.05, cx + ox + s * 0.35, cy + s * 0.65], fill=(210, 30, 50))
    elif sym == "lemon":
        d.ellipse([cx - s * 0.7, cy - s * 0.5, cx + s * 0.7, cy + s * 0.5], fill=(245, 210, 40), outline=(190, 150, 20), width=3)
    elif sym == "grape":
        for k, (ox, oy) in enumerate([(-0.4, -0.4), (0, -0.4), (0.4, -0.4), (-0.2, 0), (0.2, 0), (0, 0.4)]):
            d.ellipse([cx + ox * s - s * 0.24, cy + oy * s - s * 0.24, cx + ox * s + s * 0.24, cy + oy * s + s * 0.24],
                      fill=(140, 70, 190), outline=(90, 40, 130))
    elif sym == "bell":
        d.polygon([(cx - s * 0.65, cy + s * 0.45), (cx - s * 0.4, cy - s * 0.4), (cx, cy - s * 0.7),
                   (cx + s * 0.4, cy - s * 0.4), (cx + s * 0.65, cy + s * 0.45)], fill=(243, 170, 30), outline=(180, 110, 10))
        d.ellipse([cx - s * 0.15, cy + s * 0.4, cx + s * 0.15, cy + s * 0.7], fill=(180, 110, 10))
    elif sym == "star":
        _star(d, cx, cy, s * 0.8, GOLD)
    elif sym == "diamond":
        _gem(d, cx, cy, s * 0.75, (52, 152, 219))
    elif sym == "seven":
        d.text((cx, cy), "7", font=F(int(s * 1.7), "ExtraBold"), fill=(220, 30, 40), anchor="mm")
    else:
        d.text((cx, cy), "?", font=F(int(s * 1.4), "ExtraBold"), fill=(120, 120, 130), anchor="mm")


def draw_big(d, text, color, y=CY, size=86):
    d.text((W / 2, y), text, font=F(size, "ExtraBold"), fill=color, anchor="mm")


def result_status(bet, payout):
    delta = payout - bet
    if delta > 0:
        return f"GAGNÉ +{fmt(delta)}", GREEN
    if delta == 0:
        return "REMBOURSÉ", GREY
    return f"PERDU -{fmt(-delta)}", RED


# ========================= BOT SETUP =========================

init_db()
load_ranks()

intents = discord.Intents.default()
intents.members = True
intents.message_content = True


def get_prefix(bot, message):
    return get_prefix_cached()


bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None, case_insensitive=True)

CHANNEL_EXEMPT = {"allow", "unallow", "allowed", "help", "sys", "unsys", "owner", "unowner", "wl", "unwl", "prefix",
                  "setlog", "config", "addmoney", "removemoney", "setmoney", "resetbalance", "wipeeconomy"}


def get_allowed(gid):
    return {int(r["channel_id"]) for r in db_all("SELECT channel_id FROM allowed_channels WHERE guild_id = ?", (str(gid),))}


@bot.check
async def _channel_ok(ctx):
    if ctx.guild is None:
        return False
    if ctx.command and ctx.command.name in CHANNEL_EXEMPT:
        return True
    if get_rank_db(ctx.author.id) >= 2:
        return True
    allowed = get_allowed(ctx.guild.id)
    if not allowed:
        return True  # aucun salon configuré = casino ouvert partout
    return ctx.channel.id in allowed or getattr(ctx.channel, "parent_id", None) in allowed


# ========================= LOGS =========================

def get_log_channel(gid):
    row = db_one("SELECT channel_id FROM log_channels WHERE guild_id = ?", (str(gid),))
    return row["channel_id"] if row else None


async def send_log_embed(guild, em):
    if guild is None:
        return
    cid = get_log_channel(guild.id)
    ch = guild.get_channel(int(cid)) if cid else None
    if ch:
        try:
            await ch.send(embed=em, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass


async def admin_log(guild, title, author, desc, color=0xfaa61a):
    em = discord.Embed(title=f"📋 {title}", description=desc, color=color, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Par", value=f"{author.mention} ({author.id})", inline=False)
    await send_log_embed(guild, em)


# ========================= VUES DE BASE =========================

class OwnerView(discord.ui.View):
    def __init__(self, author, timeout=GAME_TIMEOUT):
        super().__init__(timeout=timeout)
        self.author = author
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                f"Ce n'est pas ta partie 🙂 Lance la tienne avec {get_prefix_cached()}help.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


async def safe_defer(interaction):
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
    except discord.HTTPException:
        pass


def game_embed(game=None):
    em = discord.Embed(color=embed_color())
    em.set_image(url="attachment://game.png")
    if game is not None:
        em.set_footer(text=f"Partie #{game.id} · nonce {game.nonce} · provably fair ({get_prefix_cached()}fair)")
    return em


class GameCtx:
    def __init__(self, gid, rng):
        self.id = gid
        self.rng = rng
        self.nonce = rng.nonce


def action(fn):
    """Exécute un callback de jeu sous verrou, ignoré si la partie est terminée (anti double-clic)."""
    @functools.wraps(fn)
    async def wrapper(self, interaction, *args):
        async with self.lock:
            if self.finished:
                return await safe_defer(interaction)
            await fn(self, interaction, *args)
    return wrapper


class GameView(OwnerView):
    key = ""

    def __init__(self, author, bet, game, guild=None):
        super().__init__(author, timeout=GAME_TIMEOUT)
        self.bet = bet
        self.base_bet = bet
        self.game = game
        self.guild = guild
        self.lock = asyncio.Lock()
        self.finished = False

    @property
    def theme(self):
        return GAMES[self.key][1]

    @property
    def title(self):
        return GAMES[self.key][0]

    def render(self, status=None, status_color=None, final=False):
        raise NotImplementedError

    def canvas(self, title=None):
        return base_canvas(self.theme, title or self.title)

    def footer(self, d, status, status_color=None, accent=None):
        draw_footer(d, accent or self.theme, self.bet, get_balance(self.author.id), status, status_color)

    async def frame(self, **kw):
        return await asyncio.to_thread(lambda: to_file(self.render(**kw)))

    async def show(self, interaction, **kw):
        file = await self.frame(**kw)
        await interaction.response.edit_message(attachments=[file], embed=game_embed(self.game), view=self)
        self.message = interaction.message

    async def update(self, interaction, **kw):
        file = await self.frame(**kw)
        await interaction.response.edit_message(attachments=[file], embed=game_embed(self.game), view=self)

    async def finish(self, interaction, mult, status_prefix="", **kw):
        """Clôture : verse le gain (une seule fois), affiche le résultat + bouton rejouer."""
        self.finished = True
        payout = payout_of(self.bet_total(), mult)
        res = settle_game(self.game.id, payout, mult, self.game.nonce)
        self.stop()
        if res is None:
            return await safe_defer(interaction) if interaction else None
        txt, col = result_status(res["bet"], payout)
        status = f"{status_prefix}  ·  {txt}" if status_prefix else txt
        file = await self.frame(status=status, status_color=col, final=True, **kw)
        again = PlayAgainView(self.author, self.key, self.base_bet)
        try:
            if interaction is not None:
                await interaction.response.edit_message(attachments=[file], embed=game_embed(self.game), view=again)
                again.message = interaction.message
            elif self.message is not None:
                await self.message.edit(attachments=[file], embed=game_embed(self.game), view=again)
                again.message = self.message
        except discord.HTTPException as e:
            log.warning(f"finish: affichage du résultat échoué ({e}) — gain déjà versé.")
        await self._bigwin(res["bet"], payout, mult)

    def bet_total(self):
        return self.bet

    async def _bigwin(self, bet, payout, mult):
        if payout - bet <= 0 or mult < setting("bigwin_mult"):
            return
        em = discord.Embed(title=f"🏆 Gros gain — {self.title}", color=0xf1c40f, timestamp=datetime.now(timezone.utc),
                           description=f"{self.author.mention} a gagné {money(payout)} avec une mise de {money(bet)} "
                                       f"(**x{mult:.2f}**).")
        await send_log_embed(self.guild, em)

    async def refund(self, note="⏱️ Partie expirée — mise remboursée"):
        self.finished = True
        self.stop()
        if refund_game(self.game.id) and self.message:
            for c in self.children:
                c.disabled = True
            try:
                await self.message.edit(content=note, view=self)
            except discord.HTTPException:
                pass

    async def auto_finish(self):
        """Timeout : par défaut on rembourse (aucun risque pris). Les jeux à cash-out l'override."""
        await self.refund()

    async def on_timeout(self):
        async with self.lock:
            if not self.finished:
                await self.auto_finish()


class PlayAgainView(OwnerView):
    def __init__(self, author, key, bet):
        super().__init__(author, timeout=120)
        self.key = key
        self.bet = bet

    @discord.ui.button(label="Rejouer", emoji="🔁", style=discord.ButtonStyle.success)
    async def again(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        view = BetSetupView(self.author, self.key, self.bet, interaction.guild)
        file = await view.frame()
        await interaction.response.edit_message(content=None, attachments=[file], embed=view.embed(), view=view)
        view.message = interaction.message

    @discord.ui.button(label="Quitter", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def quit(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()


# ========================= ÉCRAN DE MISE =========================

GAME_LAUNCHERS = {}


class CustomBetModal(discord.ui.Modal, title="Mise personnalisée"):
    value = discord.ui.TextInput(label="Montant", placeholder="ex : 250, 1k, 50%, all", max_length=20)

    def __init__(self, view):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        v = parse_amount(str(self.value), get_balance(self.view_ref.author.id))
        if v is None:
            return await interaction.response.send_message("❌ Montant invalide.", ephemeral=True)
        self.view_ref.bet = v
        await self.view_ref.refresh(interaction)


class BetSetupView(OwnerView):
    def __init__(self, author, key, bet, guild=None):
        super().__init__(author, timeout=120)
        self.key = key
        self.guild = guild
        self.bet = bet
        self.busy = False
        self._clamp()

    def _clamp(self):
        bal = get_balance(self.author.id)
        mn, mx = setting("min_bet"), setting("max_bet")
        hi = bal if not mx else min(bal, mx)
        self.bet = max(mn, min(int(self.bet), max(mn, hi)))

    def render(self):
        name, theme = GAMES[self.key][0], GAMES[self.key][1]
        img, d = base_canvas(theme, name)
        d.text((W / 2, CY - 70), "TA MISE", font=F(30, "SemiBold"), fill=GREY, anchor="mm")
        d.text((W / 2, CY + 6), fmt(self.bet), font=F(76, "ExtraBold"), fill=theme, anchor="mm")
        d.text((W / 2, CY + 70), "Ajuste ci-dessous puis appuie sur Jouer", font=F(22, "Medium"), fill=GREY, anchor="mm")
        draw_footer(d, theme, self.bet, get_balance(self.author.id), None)
        return img

    async def frame(self):
        return await asyncio.to_thread(lambda: to_file(self.render()))

    def embed(self):
        em = game_embed()
        em.set_footer(text=f"{GAMES[self.key][2]} {GAMES[self.key][3]}")
        return em

    async def refresh(self, interaction):
        self._clamp()
        file = await self.frame()
        await interaction.response.edit_message(attachments=[file], embed=self.embed(), view=self)

    async def _adj(self, interaction, fn):
        self.bet = fn(self.bet)
        await self.refresh(interaction)

    @discord.ui.button(label="-100", style=discord.ButtonStyle.secondary, row=0)
    async def m100(self, i, b): await self._adj(i, lambda v: v - 100)

    @discord.ui.button(label="-10", style=discord.ButtonStyle.secondary, row=0)
    async def m10(self, i, b): await self._adj(i, lambda v: v - 10)

    @discord.ui.button(label="+10", style=discord.ButtonStyle.secondary, row=0)
    async def p10(self, i, b): await self._adj(i, lambda v: v + 10)

    @discord.ui.button(label="+100", style=discord.ButtonStyle.secondary, row=0)
    async def p100(self, i, b): await self._adj(i, lambda v: v + 100)

    @discord.ui.button(label="Min", style=discord.ButtonStyle.secondary, row=1)
    async def mn(self, i, b): await self._adj(i, lambda v: 0)

    @discord.ui.button(label="½", style=discord.ButtonStyle.secondary, row=1)
    async def half(self, i, b): await self._adj(i, lambda v: v // 2)

    @discord.ui.button(label="2×", style=discord.ButtonStyle.secondary, row=1)
    async def dbl(self, i, b): await self._adj(i, lambda v: v * 2)

    @discord.ui.button(label="Max", style=discord.ButtonStyle.secondary, row=1)
    async def mx(self, i, b): await self._adj(i, lambda v: 10 ** 15)

    @discord.ui.button(label="Perso", emoji="✏️", style=discord.ButtonStyle.secondary, row=1)
    async def custom(self, i, b): await i.response.send_modal(CustomBetModal(self))

    @discord.ui.button(label="Jouer", emoji="▶️", style=discord.ButtonStyle.success, row=2)
    async def play(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.busy:
            return await safe_defer(interaction)
        self.busy = True
        gid, err = start_game(self.author.id, self.key, self.bet)
        if err:
            self.busy = False
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        self.stop()
        game = GameCtx(gid, next_rng(self.author.id))
        try:
            await GAME_LAUNCHERS[self.key](interaction, self.author, self.bet, game)
        except Exception as e:
            refund_game(gid)
            log.error(f"Lancement {self.key} échoué : {e}\n{traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Erreur au lancement, mise remboursée.", ephemeral=True)

    @discord.ui.button(label="Annuler", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content="Partie annulée.", view=self)
        self.stop()


async def open_bet_setup(ctx, key, bet):
    view = BetSetupView(ctx.author, key, bet, ctx.guild)
    file = await view.frame()
    view.message = await ctx.send(file=file, embed=view.embed(), view=view)


def register(key):
    def deco(cls):
        cls.key = key

        async def launcher(interaction, author, bet, game):
            view = cls(author, bet, game, interaction.guild)
            await view.start(interaction)
        GAME_LAUNCHERS[key] = launcher
        return cls
    return deco


# ---- Écran de choix avant la partie (mines, dragon, chicken, pump, crash) ----

class ChoiceSetupView(GameView):
    """Mise déjà débitée. Choix d'une option puis transfert vers la vraie partie.
    Abandon = remboursement au timeout."""

    def __init__(self, author, bet, game, guild, key, subtitle, hint, options, factory, modal_cls=None):
        super().__init__(author, bet, game, guild)
        self.key_override = key
        self.subtitle, self.hint, self.factory = subtitle, hint, factory
        for label, value, style in options:
            btn = discord.ui.Button(label=label, style=style)
            btn.callback = self._make_cb(value)
            self.add_item(btn)
        if modal_cls:
            btn = discord.ui.Button(label="Perso", emoji="✏️", style=discord.ButtonStyle.secondary)

            async def open_modal(interaction):
                await interaction.response.send_modal(modal_cls(self))
            btn.callback = open_modal
            self.add_item(btn)

    @property
    def theme(self):
        return GAMES[self.key_override][1]

    @property
    def title(self):
        return GAMES[self.key_override][0]

    def render(self, status=None, status_color=None, final=False):
        img, d = self.canvas()
        d.text((W / 2, CY - 14), self.subtitle, font=F(32, "SemiBold"), fill=GREY, anchor="mm")
        d.text((W / 2, CY + 36), self.hint, font=F(21, "Medium"), fill=self.theme, anchor="mm")
        self.footer(d, status, status_color)
        return img

    def _make_cb(self, value):
        async def cb(interaction):
            await self.pick(interaction, value)
        return cb

    async def pick(self, interaction, value):
        async with self.lock:
            if self.finished:
                return await safe_defer(interaction)
            self.finished = True  # la partie continue dans la nouvelle vue (pas de remboursement)
            self.stop()
            view = self.factory(value)
            await view.start(interaction)


# ========================= JEUX INSTANTANÉS =========================

@register("coinflip")
class CoinflipView(GameView):
    face = None

    async def start(self, interaction):
        await self.show(interaction, status="Pile ou Face ?")

    def render(self, status=None, status_color=None, final=False):
        img, d = self.canvas()
        r = 95
        coin = GOLD if self.face != "face" else (200, 200, 210)
        d.ellipse([W / 2 - r, CY - r, W / 2 + r, CY + r], fill=_mix(coin, WHITE, 0.15), outline=_mix(coin, (0, 0, 0), 0.4), width=8)
        d.ellipse([W / 2 - r + 22, CY - r + 22, W / 2 + r - 22, CY + r - 22], outline=_mix(coin, (0, 0, 0), 0.25), width=3)
        label = {"pile": "PILE", "face": "FACE"}.get(self.face, "?")
        d.text((W / 2, CY), label, font=F(44 if self.face else 80, "ExtraBold"), fill=(60, 45, 5), anchor="mm")
        d.text((W / 2, CY + r + 26), "x1.98", font=F(22, "SemiBold"), fill=GREY, anchor="mm")
        self.footer(d, status, status_color)
        return img

    async def _flip(self, interaction, side):
        self.face = "pile" if self.game.rng.random() < 0.5 else "face"
        mult = 1.98 if self.face == side else 0
        await self.finish(interaction, mult, f"{self.face.upper()}")

    @discord.ui.button(label="Pile", emoji="🟡", style=discord.ButtonStyle.primary)
    @action
    async def pile(self, i, b): await self._flip(i, "pile")

    @discord.ui.button(label="Face", emoji="⚪", style=discord.ButtonStyle.primary)
    @action
    async def facebtn(self, i, b): await self._flip(i, "face")


class NumberModal(discord.ui.Modal):
    def __init__(self, view, title, label, placeholder, apply):
        super().__init__(title=title)
        self.view_ref, self.apply = view, apply
        self.value = discord.ui.TextInput(label=label, placeholder=placeholder, max_length=60)
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        v = self.view_ref
        async with v.lock:
            if v.finished:
                return await safe_defer(interaction)
            err = self.apply(str(self.value).strip())
            if err:
                return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
            await v.update(interaction, status=v.idle_status())


@register("dice")
class DiceView(GameView):
    direction = "over"
    target = 50.5
    roll = None

    def chance(self):
        return (100 - self.target) if self.direction == "over" else self.target

    def mult(self):
        return round(99 / self.chance(), 4)

    def idle_status(self):
        return f"{'Au-dessus' if self.direction == 'over' else 'En dessous'} de {self.target:.2f}"

    def _clamp(self):
        lo, hi = (2.0, 99.0) if self.direction == "over" else (1.0, 98.0)
        self.target = round(min(hi, max(lo, self.target)), 2)

    async def start(self, interaction):
        await self.show(interaction, status=self.idle_status())

    def render(self, status=None, status_color=None, final=False):
        img, d = self.canvas()
        x, y, w = 70, 170, W - 140
        tx = x + w * self.target / 100
        d.rounded_rectangle([x, y, x + w, y + 26], radius=13, fill=RED)
        if self.direction == "over":
            d.rounded_rectangle([tx, y, x + w, y + 26], radius=13, fill=GREEN)
        else:
            d.rounded_rectangle([x, y, tx, y + 26], radius=13, fill=GREEN)
        d.line([(tx, y - 12), (tx, y + 38)], fill=WHITE, width=3)
        for v in (0, 25, 50, 75, 100):
            d.text((x + w * v / 100, y + 52), str(v), font=F(18, "Medium"), fill=GREY, anchor="mm")
        if self.roll is not None:
            rx = x + w * self.roll / 100
            win = (self.roll > self.target) if self.direction == "over" else (self.roll < self.target)
            col = GREEN if win else RED
            d.rounded_rectangle([rx - 46, y - 74, rx + 46, y - 28], radius=10, fill=col)
            d.polygon([(rx - 8, y - 29), (rx + 8, y - 29), (rx, y - 16)], fill=col)
            d.text((rx, y - 51), f"{self.roll:.2f}", font=F(24, "ExtraBold"), fill=WHITE, anchor="mm")
        stats = [("Multiplicateur", f"x{self.mult():.4f}"), ("Cible", f"{'>' if self.direction == 'over' else '<'} {self.target:.2f}"),
                 ("Chance", f"{self.chance():.2f}%")]
        for k, (lab, val) in enumerate(stats):
            cx = 70 + (W - 140) * (k + 0.5) / 3
            d.text((cx, 290), lab, font=F(18, "Medium"), fill=GREY, anchor="mm")
            d.text((cx, 325), val, font=F(30, "ExtraBold"), fill=WHITE, anchor="mm")
        self.footer(d, status, status_color)
        return img

    async def _adj(self, interaction, delta=None, flip=False):
        if flip:
            self.direction = "under" if self.direction == "over" else "over"
            self.target = round(100 - self.target, 2)
        else:
            self.target += delta
        self._clamp()
        await self.update(interaction, status=self.idle_status())

    @discord.ui.button(label="Over / Under", emoji="⇅", style=discord.ButtonStyle.primary, row=0)
    @action
    async def flip(self, i, b): await self._adj(i, flip=True)

    @discord.ui.button(label="-10", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def m10(self, i, b): await self._adj(i, -10)

    @discord.ui.button(label="-1", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def m1(self, i, b): await self._adj(i, -1)

    @discord.ui.button(label="+1", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def p1(self, i, b): await self._adj(i, 1)

    @discord.ui.button(label="+10", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def p10(self, i, b): await self._adj(i, 10)

    @discord.ui.button(label="Cible", emoji="🎯", style=discord.ButtonStyle.secondary, row=1)
    async def custom(self, interaction: discord.Interaction, b):
        def apply(raw):
            try:
                self.target = float(raw.replace(",", "."))
            except ValueError:
                return "Nombre invalide."
            self._clamp()
        await interaction.response.send_modal(NumberModal(self, "Cible du dé", "Cible (1 à 99)", "ex : 50.5", apply))

    @discord.ui.button(label="Lancer", emoji="🎲", style=discord.ButtonStyle.success, row=1)
    @action
    async def roll_btn(self, i, b):
        self.roll = self.game.rng.randrange(10001) / 100
        win = (self.roll > self.target) if self.direction == "over" else (self.roll < self.target)
        await self.finish(i, self.mult() if win else 0, f"{self.roll:.2f}")


@register("limbo")
class LimboView(GameView):
    target = 2.0
    result = None

    def idle_status(self):
        return f"Cible x{self.target:.2f} · {99 / self.target:.4f}% de chance"

    async def start(self, interaction):
        await self.show(interaction, status=self.idle_status())

    def render(self, status=None, status_color=None, final=False):
        img, d = self.canvas()
        if self.result is None:
            d.text((W / 2, CY - 40), "CIBLE", font=F(26, "SemiBold"), fill=GREY, anchor="mm")
            draw_big(d, f"{self.target:.2f}x", self.theme, CY + 20)
        else:
            col = GREEN if self.result >= self.target else RED
            draw_big(d, f"{self.result:,.2f}x".replace(",", " "), col, CY - 10)
            d.text((W / 2, CY + 62), f"cible {self.target:.2f}x", font=F(24, "Medium"), fill=GREY, anchor="mm")
        self.footer(d, status, status_color)
        return img

    async def _adj(self, interaction, fn):
        self.target = round(min(1_000_000, max(1.01, fn(self.target))), 2)
        await self.update(interaction, status=self.idle_status())

    @discord.ui.button(label="÷2", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def d2(self, i, b): await self._adj(i, lambda t: t / 2)

    @discord.ui.button(label="-0.1", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def m01(self, i, b): await self._adj(i, lambda t: t - 0.1)

    @discord.ui.button(label="+0.1", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def p01(self, i, b): await self._adj(i, lambda t: t + 0.1)

    @discord.ui.button(label="×2", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def x2(self, i, b): await self._adj(i, lambda t: t * 2)

    @discord.ui.button(label="Cible", emoji="🎯", style=discord.ButtonStyle.secondary, row=1)
    async def custom(self, interaction: discord.Interaction, b):
        def apply(raw):
            try:
                self.target = round(min(1_000_000, max(1.01, float(raw.replace(",", ".").rstrip("x")))), 2)
            except ValueError:
                return "Nombre invalide."
        await interaction.response.send_modal(NumberModal(self, "Cible Limbo", "Multiplicateur (1.01 à 1 000 000)", "ex : 3.5", apply))

    @discord.ui.button(label="Jouer", emoji="🚀", style=discord.ButtonStyle.success, row=1)
    @action
    async def play(self, i, b):
        self.result = min(1_000_000.0, crash_point_from(self.game.rng.random()))
        await self.finish(i, self.target if self.result >= self.target else 0, f"{self.result:.2f}x")


@register("wheel")
class WheelView(GameView):
    risk = "medium"
    landed = None
    angle = 0.0

    async def start(self, interaction):
        await self.show(interaction, status=f"Risque {self.risk}")

    def render(self, status=None, status_color=None, final=False):
        img, d = self.canvas()
        seg = WHEEL[self.risk]
        n = len(seg)
        cx, cy, r = W / 2, CY + 4, 132
        palette = {0: (55, 60, 70), 1.2: (90, 160, 200), 1.5: (46, 204, 113), 1.8: (241, 196, 15), 2: (230, 126, 34),
                   3: (155, 89, 182), 19.8: (231, 76, 60)}
        for k in range(n):
            a0 = self.angle + k * 360 / n - 90
            col = palette.get(seg[k], self.theme)
            if self.landed is not None and k == self.landed:
                col = WHITE
            d.pieslice([cx - r, cy - r, cx + r, cy + r], a0, a0 + 360 / n, fill=col, outline=(15, 15, 18), width=2)
        d.ellipse([cx - r + 26, cy - r + 26, cx + r - 26, cy + r - 26], fill=(20, 22, 26))
        if self.landed is not None:
            d.text((cx, cy), f"{seg[self.landed]:g}x", font=F(38, "ExtraBold"), fill=self.theme, anchor="mm")
        else:
            d.text((cx, cy), self.risk.upper(), font=F(24, "Bold"), fill=GREY, anchor="mm")
        d.polygon([(cx, cy - r + 14), (cx - 14, cy - r - 12), (cx + 14, cy - r - 12)], fill=WHITE)
        legend = sorted(set(seg))
        for k, m in enumerate(legend):
            yy = 130 + k * 34
            d.rounded_rectangle([W - 160, yy, W - 130, yy + 24], radius=6, fill=palette.get(m, self.theme))
            d.text((W - 118, yy + 12), f"{m:g}x", font=F(20, "SemiBold"), fill=WHITE, anchor="lm")
        self.footer(d, status, status_color)
        return img

    async def _risk(self, interaction, risk):
        self.risk = risk
        await self.update(interaction, status=f"Risque {risk}")

    @discord.ui.button(label="Low", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def low(self, i, b): await self._risk(i, "low")

    @discord.ui.button(label="Medium", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def med(self, i, b): await self._risk(i, "medium")

    @discord.ui.button(label="High", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def high(self, i, b): await self._risk(i, "high")

    @discord.ui.button(label="Tourner", emoji="🎡", style=discord.ButtonStyle.success, row=1)
    @action
    async def spin(self, i, b):
        seg = WHEEL[self.risk]
        self.landed = self.game.rng.randrange(len(seg))
        self.angle = -(self.landed + 0.5) * 360 / len(seg)
        await self.finish(i, seg[self.landed], f"x{seg[self.landed]:g}")


@register("slots")
class SlotsView(GameView):
    reels = None

    async def start(self, interaction):
        await self.show(interaction, status="Appuie sur Lancer !")

    def render(self, status=None, status_color=None, final=False):
        img, d = self.canvas()
        bw, gap = 140, 24
        x0 = W / 2 - (bw * 3 + gap * 2) / 2
        for k in range(3):
            x = x0 + k * (bw + gap)
            d.rounded_rectangle([x, CY - 85, x + bw, CY + 85], radius=18, fill=(245, 246, 248), outline=self.theme, width=5)
            draw_slot_symbol(d, SLOT_SYMBOLS[self.reels[k]] if self.reels else None, x + bw / 2, CY, 46)
        pay = "  ".join(f"{n[:3]} {m:g}x" for n, m in zip(["Cer", "Cit", "Rai", "Clo", "Eto", "Dia", "777"], SLOT_TRIPLE))
        d.text((W / 2, CY + 112), f"3 identiques : {pay}", font=F(14, "Medium"), fill=GREY, anchor="mm")
        self.footer(d, status, status_color)
        return img

    @discord.ui.button(label="Lancer", emoji="🎰", style=discord.ButtonStyle.success)
    @action
    async def spin(self, i, b):
        rng = self.game.rng
        self.reels = [rng.weighted(list(range(7)), SLOT_WEIGHTS) for _ in range(3)]
        m = slot_mult(self.reels, SLOT_TRIPLE, SLOT_TWO_CHERRY)
        await self.finish(i, m, f"x{m:g}")


@register("plinko")
class PlinkoView(GameView):
    risk = "medium"
    rows = 12
    path = None

    def idle_status(self):
        return f"Risque {self.risk} · {self.rows} lignes"

    async def start(self, interaction):
        await self.show(interaction, status=self.idle_status())

    def render(self, status=None, status_color=None, final=False):
        img, d = self.canvas()
        table = PLINKO[self.rows][self.risk]
        n = len(table)
        top, bot = 112, H - 150
        bw = (W - 180) / n
        x_left = 90

        def peg_xy(row, k):
            count = row + 3
            span = bw * (count - 1)
            return W / 2 - span / 2 + k * bw, top + (bot - top) * row / self.rows

        for row in range(self.rows):
            for k in range(row + 3):
                px, py = peg_xy(row, k)
                d.ellipse([px - 3, py - 3, px + 3, py + 3], fill=(150, 156, 168))
        if self.path is not None:
            pos, pts = 0.0, [(W / 2, top - 14)]
            for row, right in enumerate(self.path):
                pos += 0.5 if right else -0.5
                pts.append((W / 2 + pos * bw, top + (bot - top) * (row + 0.5) / self.rows))
            landed = sum(self.path)
            pts.append((x_left + (landed + 0.5) * bw, bot + 22))
            d.line(pts, fill=WHITE, width=3)
            ex, ey = pts[-1]
            d.ellipse([ex - 9, ey - 9, ex + 9, ey + 9], fill=GOLD, outline=WHITE, width=2)
        for k in range(n):
            bx = x_left + k * bw
            m = table[k]
            t = min(1.0, math.log10(max(m, 0.1) * 10) / 4)
            col = _mix((241, 196, 15), (231, 50, 60), t)
            if self.path is not None and sum(self.path) == k:
                col = WHITE
            d.rounded_rectangle([bx + 2, bot + 30, bx + bw - 2, bot + 58], radius=6, fill=col)
            d.text((bx + bw / 2, bot + 44), f"{m:g}", font=F(12 if n > 13 else 14, "Bold"), fill=(20, 20, 24), anchor="mm")
        self.footer(d, status, status_color)
        return img

    @discord.ui.button(label="Low", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def low(self, i, b):
        self.risk = "low"
        await self.update(i, status=self.idle_status())

    @discord.ui.button(label="Medium", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def med(self, i, b):
        self.risk = "medium"
        await self.update(i, status=self.idle_status())

    @discord.ui.button(label="High", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def high(self, i, b):
        self.risk = "high"
        await self.update(i, status=self.idle_status())

    @discord.ui.button(label="Lignes 8/12/16", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def rows_btn(self, i, b):
        self.rows = {8: 12, 12: 16, 16: 8}[self.rows]
        await self.update(i, status=self.idle_status())

    @discord.ui.button(label="Lâcher", emoji="🟡", style=discord.ButtonStyle.success, row=1)
    @action
    async def drop(self, i, b):
        self.path = [self.game.rng.random() < 0.5 for _ in range(self.rows)]
        m = PLINKO[self.rows][self.risk][sum(self.path)]
        await self.finish(i, m, f"x{m:g}")


DIAMOND_COLORS = [(231, 76, 60), (230, 126, 34), (241, 196, 15), (46, 204, 113), (52, 152, 219), (155, 89, 182), (236, 240, 241)]


@register("diamonds")
class DiamondsView(GameView):
    gems = None
    label = None

    async def start(self, interaction):
        await self.show(interaction, status="Appuie sur Révéler !")

    def render(self, status=None, status_color=None, final=False):
        img, d = self.canvas()
        gw, gap = 100, 26
        x0 = W / 2 - (gw * 5 + gap * 4) / 2
        for k in range(5):
            x = x0 + k * (gw + gap)
            d.rounded_rectangle([x, CY - 70, x + gw, CY + 50], radius=14, fill=DARK)
            col = DIAMOND_COLORS[self.gems[k]] if self.gems else (70, 74, 82)
            _gem(d, x + gw / 2, CY - 10, 38, col)
        if self.label:
            d.text((W / 2, CY + 90), self.label, font=F(30, "ExtraBold"), fill=self.theme, anchor="mm")
        else:
            d.text((W / 2, CY + 90), " · ".join(f"{lab} {m:g}x" for lab, m in list(DIAMONDS.values())[:5]),
                   font=F(16, "Medium"), fill=GREY, anchor="mm")
        self.footer(d, status, status_color)
        return img

    @discord.ui.button(label="Révéler", emoji="💎", style=discord.ButtonStyle.success)
    @action
    async def reveal(self, i, b):
        self.gems = [self.game.rng.randrange(7) for _ in range(5)]
        shape = tuple(sorted((self.gems.count(g) for g in set(self.gems)), reverse=True))
        self.label, m = DIAMONDS[shape]
        await self.finish(i, m, f"{self.label} x{m:g}")


@register("case")
class CaseView(GameView):
    reward = None

    async def start(self, interaction):
        await self.show(interaction, status="Appuie sur Ouvrir !")

    def render(self, status=None, status_color=None, final=False):
        img, d = self.canvas()
        cx = W / 2
        d.rounded_rectangle([cx - 110, CY - 80, cx + 110, CY + 60], radius=16, fill=_mix(self.theme, (40, 30, 10), 0.5),
                            outline=self.theme, width=5)
        if self.reward is None:
            d.line([(cx - 110, CY - 30), (cx + 110, CY - 30)], fill=self.theme, width=5)
            d.rounded_rectangle([cx - 26, CY - 44, cx + 26, CY - 14], radius=6, fill=self.theme)
            d.text((cx, CY + 18), "CAISSE", font=F(30, "ExtraBold"), fill=WHITE, anchor="mm")
        else:
            col = GREEN if self.reward >= 1 else RED
            d.text((cx, CY - 10), f"{self.reward:g}x", font=F(60, "ExtraBold"), fill=col, anchor="mm")
        strip = "  ".join(f"{m:g}x" for m in CASE_MULTS)
        d.text((W / 2, CY + 100), strip, font=F(17, "Medium"), fill=GREY, anchor="mm")
        self.footer(d, status, status_color)
        return img

    @discord.ui.button(label="Ouvrir", emoji="📦", style=discord.ButtonStyle.success)
    @action
    async def open_case(self, i, b):
        self.reward = self.game.rng.weighted(CASE_MULTS, _CASE_W)
        await self.finish(i, self.reward, f"x{self.reward:g}")


@register("keno")
class KenoView(GameView):
    drawn = None

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.picks = sorted(self.game.rng.shuffle(range(1, 41))[:8])

    def idle_status(self):
        return f"{len(self.picks)} numéros · max x{KENO[len(self.picks)][-1]:g}"

    async def start(self, interaction):
        await self.show(interaction, status=self.idle_status())

    def render(self, status=None, status_color=None, final=False):
        img, d = self.canvas()
        cols, gx, gy = 10, 70, 112
        cw, ch = (W - 300) / cols, 54
        for n in range(1, 41):
            r, c = (n - 1) // cols, (n - 1) % cols
            x, y = gx + c * cw, gy + r * ch
            picked, hit = n in self.picks, self.drawn is not None and n in self.drawn
            if hit and picked:
                fill, tcol = GREEN, (10, 10, 14)
            elif hit:
                fill, tcol = (90, 40, 40), WHITE
            elif picked:
                fill, tcol = _mix(self.theme, WHITE, 0.15), WHITE
            else:
                fill, tcol = DARK, GREY
            d.rounded_rectangle([x + 3, y + 3, x + cw - 3, y + ch - 3], radius=8, fill=fill)
            d.text((x + cw / 2, y + ch / 2), str(n), font=F(19, "SemiBold"), fill=tcol, anchor="mm")
        table = KENO[len(self.picks)]
        d.text((W - 200, 112), "Gains", font=F(20, "Bold"), fill=WHITE)
        for h, m in enumerate(table):
            if m > 0:
                yy = 112 + 28 + sum(1 for x in table[:h] if x > 0) * 24
                d.text((W - 200, yy), f"{h} trouvés : {m:g}x", font=F(17, "Medium"), fill=GREY)
        self.footer(d, status, status_color)
        return img

    async def _spots(self, interaction, n):
        self.picks = sorted(self.game.rng.shuffle(range(1, 41))[:n])
        await self.update(interaction, status=self.idle_status())

    @discord.ui.button(label="3", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def s3(self, i, b): await self._spots(i, 3)

    @discord.ui.button(label="5", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def s5(self, i, b): await self._spots(i, 5)

    @discord.ui.button(label="8", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def s8(self, i, b): await self._spots(i, 8)

    @discord.ui.button(label="10", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def s10(self, i, b): await self._spots(i, 10)

    @discord.ui.button(label="Aléatoire", emoji="🔀", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def repick(self, i, b): await self._spots(i, len(self.picks))

    @discord.ui.button(label="Mes numéros", emoji="✏️", style=discord.ButtonStyle.secondary, row=1)
    async def mine(self, interaction: discord.Interaction, b):
        def apply(raw):
            nums = [int(x) for x in re.findall(r"\d+", raw)]
            nums = sorted(set(n for n in nums if 1 <= n <= 40))
            if not 1 <= len(nums) <= 10:
                return "Choisis entre 1 et 10 numéros entre 1 et 40."
            self.picks = nums
        await interaction.response.send_modal(NumberModal(self, "Tes numéros Keno", "1 à 10 numéros (1-40)", "ex : 3 7 12 25 33", apply))

    @discord.ui.button(label="Tirer", emoji="🎱", style=discord.ButtonStyle.success, row=1)
    @action
    async def draw_btn(self, i, b):
        self.drawn = set(self.game.rng.shuffle(range(1, 41))[:10])
        hits = len(set(self.picks) & self.drawn)
        m = KENO[len(self.picks)][hits]
        await self.finish(i, m, f"{hits}/{len(self.picks)} · x{m:g}")


RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
ROULETTE_LABELS = {"red": "Rouge", "black": "Noir", "even": "Pair", "odd": "Impair", "low": "1-18", "high": "19-36",
                   "d1": "1-12", "d2": "13-24", "d3": "25-36"}


def roulette_win(choice, r):
    if choice.isdigit():
        return int(choice) == r, 36
    table = {
        "red": (r in RED_NUMBERS, 2), "black": (r != 0 and r not in RED_NUMBERS, 2),
        "even": (r != 0 and r % 2 == 0, 2), "odd": (r % 2 == 1, 2), "low": (1 <= r <= 18, 2), "high": (19 <= r <= 36, 2),
        "d1": (1 <= r <= 12, 3), "d2": (13 <= r <= 24, 3), "d3": (25 <= r <= 36, 3),
    }
    return table[choice]


@register("roulette")
class RouletteView(GameView):
    choice = "red"
    result = None

    def label(self):
        return f"Numéro {self.choice}" if self.choice.isdigit() else ROULETTE_LABELS[self.choice]

    def idle_status(self):
        return f"Pari : {self.label()} · x{roulette_win(self.choice, -1)[1]}"

    async def start(self, interaction):
        await self.show(interaction, status=self.idle_status())

    def render(self, status=None, status_color=None, final=False):
        img, d = self.canvas()
        cx = W / 2
        if self.result is None:
            d.text((cx, CY - 30), "PARI", font=F(26, "SemiBold"), fill=GREY, anchor="mm")
            draw_big(d, self.label(), self.theme, CY + 26, size=64)
        else:
            ring = GREEN if self.result == 0 else (RED if self.result in RED_NUMBERS else (35, 38, 44))
            d.ellipse([cx - 86, CY - 96, cx + 86, CY + 76], fill=ring, outline=WHITE, width=5)
            d.text((cx, CY - 10), str(self.result), font=F(70, "ExtraBold"), fill=WHITE, anchor="mm")
            d.text((cx, CY + 104), f"pari : {self.label()}", font=F(22, "Medium"), fill=GREY, anchor="mm")
        self.footer(d, status, status_color)
        return img

    async def _set(self, interaction, choice):
        self.choice = choice
        await self.update(interaction, status=self.idle_status())

    @discord.ui.button(label="Rouge", style=discord.ButtonStyle.danger, row=0)
    @action
    async def red(self, i, b): await self._set(i, "red")

    @discord.ui.button(label="Noir", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def black(self, i, b): await self._set(i, "black")

    @discord.ui.button(label="Pair", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def even(self, i, b): await self._set(i, "even")

    @discord.ui.button(label="Impair", style=discord.ButtonStyle.secondary, row=0)
    @action
    async def odd(self, i, b): await self._set(i, "odd")

    @discord.ui.button(label="1-18", style=discord.ButtonStyle.secondary, row=1)
    @action
    async def low(self, i, b): await self._set(i, "low")

    @discord.ui.button(label="19-36", style=discord.ButtonStyle.secondary, row=1)
    @action
    async def high(self, i, b): await self._set(i, "high")

    @discord.ui.button(label="1-12", style=discord.ButtonStyle.secondary, row=1)
    @action
    async def d1(self, i, b): await self._set(i, "d1")

    @discord.ui.button(label="13-24", style=discord.ButtonStyle.secondary, row=1)
    @action
    async def d2(self, i, b): await self._set(i, "d2")

    @discord.ui.button(label="25-36", style=discord.ButtonStyle.secondary, row=1)
    @action
    async def d3(self, i, b): await self._set(i, "d3")

    @discord.ui.button(label="Numéro", emoji="#️⃣", style=discord.ButtonStyle.primary, row=2)
    async def number(self, interaction: discord.Interaction, b):
        def apply(raw):
            if not raw.isdigit() or not 0 <= int(raw) <= 36:
                return "Numéro entre 0 et 36."
            self.choice = str(int(raw))
        await interaction.response.send_modal(NumberModal(self, "Numéro plein (x36)", "Numéro (0-36)", "ex : 17", apply))

    @discord.ui.button(label="Tourner", emoji="🎡", style=discord.ButtonStyle.success, row=2)
    @action
    async def spin(self, i, b):
        self.result = self.game.rng.randrange(37)
        win, m = roulette_win(self.choice, self.result)
        await self.finish(i, m if win else 0, f"Sorti : {self.result}")


def rand_card(rng):
    return RANKS[rng.randrange(13)], SUITS[rng.randrange(4)]


def shuffled_deck(rng):
    return rng.shuffle([(r, s) for s in SUITS for r in RANKS])


def bacc_pip(card):
    r = card[0]
    return 0 if r in ("10", "J", "Q", "K") else (1 if r == "A" else int(r))


def bacc_value(cards):
    return sum(bacc_pip(c) for c in cards) % 10


def play_baccarat(rng):
    deck = shuffled_deck(rng)
    player, banker = [deck.pop(), deck.pop()], [deck.pop(), deck.pop()]
    pv, bv = bacc_value(player), bacc_value(banker)
    if pv < 8 and bv < 8:
        third = None
        if pv <= 5:
            third = deck.pop()
            player.append(third)
        if third is None:
            draw_b = bv <= 5
        else:
            p = bacc_pip(third)
            draw_b = (bv <= 2 or (bv == 3 and p != 8) or (bv == 4 and 2 <= p <= 7)
                      or (bv == 5 and 4 <= p <= 7) or (bv == 6 and p in (6, 7)))
        if draw_b:
            banker.append(deck.pop())
    pv, bv = bacc_value(player), bacc_value(banker)
    return player, banker, pv, bv, ("player" if pv > bv else "banker" if bv > pv else "tie")


@register("baccarat")
class BaccaratView(GameView):
    state = None

    async def start(self, interaction):
        await self.show(interaction, status="Joueur x2 · Banquier x1.95 · Égalité x9")

    def render(self, status=None, status_color=None, final=False):
        img, d = self.canvas()
        if self.state is None:
            draw_big(d, "Choisis ton camp", GREY, CY, size=40)
        else:
            player, banker, pv, bv, winner = self.state
            for label, cards, val, yy, key in (("Joueur", player, pv, 140, "player"), ("Banquier", banker, bv, 290, "banker")):
                win = winner == key
                d.text((90, yy - 30), f"{label}  {val}", font=F(24, "Bold"), fill=GREEN if win else GREY)
                for k, c in enumerate(cards):
                    draw_card(d, 90 + k * 84, yy, 72, 102, c, glow=GREEN if win else None)
            name = {"player": "JOUEUR", "banker": "BANQUIER", "tie": "ÉGALITÉ"}[winner]
            d.text((W - 80, CY), name, font=F(40, "ExtraBold"), fill=self.theme, anchor="rm")
        self.footer(d, status, status_color)
        return img

    async def _bet(self, interaction, side):
        self.state = play_baccarat(self.game.rng)
        winner = self.state[4]
        if winner == side:
            m = {"player": 2, "banker": 1.95, "tie": 9}[side]
        elif winner == "tie":
            m = 1  # égalité : les paris Joueur / Banquier sont remboursés
        else:
            m = 0
        await self.finish(interaction, m, {"player": "Joueur", "banker": "Banquier", "tie": "Égalité"}[winner])

    @discord.ui.button(label="Joueur", style=discord.ButtonStyle.primary)
    @action
    async def player(self, i, b): await self._bet(i, "player")

    @discord.ui.button(label="Banquier", style=discord.ButtonStyle.danger)
    @action
    async def banker(self, i, b): await self._bet(i, "banker")

    @discord.ui.button(label="Égalité", style=discord.ButtonStyle.secondary)
    @action
    async def tie(self, i, b): await self._bet(i, "tie")


# ========================= JEUX À CASH-OUT =========================

class CashoutGame(GameView):
    """Jeux où l'on peut encaisser : au timeout, encaissement auto si gain en cours, sinon remboursement."""
    mult = 1.0

    def has_progress(self):
        return self.mult > 1.0

    async def auto_finish(self):
        if self.has_progress():
            await self.finish(None, self.mult, f"Encaissé auto x{self.mult:.2f}", reveal=True)
        else:
            await self.refund()

    async def cashout(self, interaction):
        if not self.has_progress():
            return await interaction.response.send_message("Fais au moins un coup gagnant avant d'encaisser !", ephemeral=True)
        await self.finish(interaction, self.mult, f"Encaissé x{self.mult:.2f}", reveal=True)


# ---- MINES ----
MINES_COLS, MINES_ROWS = 5, 4
MINES_TILES = MINES_COLS * MINES_ROWS


def mines_multiplier(picks, mines):
    m = 1.0
    for i in range(picks):
        m *= (MINES_TILES - i) / (MINES_TILES - mines - i)
    return round(m * (1 - HOUSE_EDGE), 4)


class MineButton(discord.ui.Button):
    def __init__(self, index):
        super().__init__(label="​", style=discord.ButtonStyle.secondary, row=index // MINES_COLS)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        await self.view.tile(interaction, self.index)


class MinesView(CashoutGame):
    key = "mines"

    def __init__(self, author, bet, game, guild, n_mines):
        super().__init__(author, bet, game, guild)
        self.n_mines = n_mines
        self.mines = set(game.rng.shuffle(range(MINES_TILES))[:n_mines])
        self.revealed = []
        self.hit = None
        for i in range(MINES_TILES):
            self.add_item(MineButton(i))
        self.cash_btn = discord.ui.Button(label="Encaisser", emoji="💰", style=discord.ButtonStyle.success, row=4)
        self.cash_btn.callback = self._cash
        self.add_item(self.cash_btn)
        rnd = discord.ui.Button(label="Case aléatoire", emoji="🎲", style=discord.ButtonStyle.secondary, row=4)
        rnd.callback = self._random
        self.add_item(rnd)

    async def start(self, interaction):
        await self.show(interaction, status=f"{self.n_mines} mines cachées — trouve les gemmes !")

    def render(self, status=None, status_color=None, final=False, reveal=False):
        img, d = self.canvas()
        tile, gap = 66, 12
        ax, ay = W - 60 - (tile * MINES_COLS + gap * (MINES_COLS - 1)), 108
        for i in range(MINES_TILES):
            x = ax + (i % MINES_COLS) * (tile + gap)
            y = ay + (i // MINES_COLS) * (tile + gap)
            box = [x, y, x + tile, y + tile]
            if i in self.revealed:
                d.rounded_rectangle(box, radius=10, fill=_mix(self.theme, (10, 10, 14), 0.55), outline=self.theme, width=2)
                _gem(d, x + tile / 2, y + tile / 2, tile * 0.27, GREEN)
            elif (reveal or final) and i in self.mines:
                d.rounded_rectangle(box, radius=10, fill=(120, 30, 26) if i == self.hit else (60, 30, 30),
                                    outline=RED, width=3 if i == self.hit else 1)
                _bomb(d, x + tile / 2, y + tile / 2 + 4, tile * 0.18)
            elif reveal or final:
                d.rounded_rectangle(box, radius=10, fill=(34, 40, 36), outline=(60, 90, 60), width=1)
                _gem(d, x + tile / 2, y + tile / 2, tile * 0.18, (70, 110, 80))
            else:
                d.rounded_rectangle(box, radius=10, fill=DARK, outline=(60, 64, 72), width=2)
        nxt = mines_multiplier(len(self.revealed) + 1, self.n_mines) if len(self.revealed) < MINES_TILES - self.n_mines else self.mult
        info = [("Mines", str(self.n_mines), RED), ("Gemmes", str(len(self.revealed)), GREEN),
                ("Multiplicateur", f"x{self.mult:.2f}", WHITE), ("Prochain", f"x{nxt:.2f}", GREY),
                ("Gain", fmt(payout_of(self.bet, self.mult)), GOLD)]
        for k, (lab, val, col) in enumerate(info):
            d.text((70, 112 + k * 50), lab, font=F(17, "Medium"), fill=GREY)
            d.text((70, 130 + k * 50), val, font=F(26, "ExtraBold"), fill=col)
        self.footer(d, status, status_color)
        return img

    async def tile(self, interaction, index):
        async with self.lock:
            if self.finished or index in self.revealed:
                return await safe_defer(interaction)
            await self._reveal(interaction, index)

    async def _random(self, interaction):
        async with self.lock:
            if self.finished:
                return await safe_defer(interaction)
            hidden = [i for i in range(MINES_TILES) if i not in self.revealed]
            await self._reveal(interaction, hidden[secrets.randbelow(len(hidden))])

    async def _reveal(self, interaction, index):
        if index in self.mines:
            self.hit = index
            return await self.finish(interaction, 0, "BOOM", reveal=True)
        self.revealed.append(index)
        self.mult = mines_multiplier(len(self.revealed), self.n_mines)
        btn = next(c for c in self.children if isinstance(c, MineButton) and c.index == index)
        btn.label, btn.style, btn.disabled, btn.emoji = None, discord.ButtonStyle.success, True, "💎"
        if len(self.revealed) >= MINES_TILES - self.n_mines:
            return await self.finish(interaction, self.mult, "Grille nettoyée !", reveal=True)
        self.cash_btn.label = f"Encaisser {fmt(payout_of(self.bet, self.mult))}"
        await self.update(interaction, status=f"x{self.mult:.2f} — continue ou encaisse")

    async def _cash(self, interaction):
        async with self.lock:
            if self.finished:
                return await safe_defer(interaction)
            await self.cashout(interaction)


class MinesCountModal(discord.ui.Modal, title="Nombre de mines"):
    value = discord.ui.TextInput(label=f"Mines (1-{MINES_TILES - 1})", placeholder="3", max_length=2)

    def __init__(self, setup):
        super().__init__()
        self.setup = setup

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.value).strip()
        if not raw.isdigit() or not 1 <= int(raw) <= MINES_TILES - 1:
            return await interaction.response.send_message(f"❌ Entre un nombre entre 1 et {MINES_TILES - 1}.", ephemeral=True)
        await self.setup.pick(interaction, int(raw))


async def launch_mines(interaction, author, bet, game):
    setup = ChoiceSetupView(
        author, bet, game, interaction.guild, "mines", "COMBIEN DE MINES ?", "plus de mines = plus gros gains",
        [("1", 1, discord.ButtonStyle.secondary), ("3", 3, discord.ButtonStyle.primary), ("5", 5, discord.ButtonStyle.secondary),
         ("10", 10, discord.ButtonStyle.secondary), ("15", 15, discord.ButtonStyle.danger)],
        lambda n: MinesView(author, bet, game, interaction.guild, n), MinesCountModal)
    await setup.show(interaction)
GAME_LAUNCHERS["mines"] = launch_mines


# ---- CRASH ----
CRASH_TICK = 1.2
CRASH_SPEED = 0.07  # multiplicateur = e^(0.07 · secondes)
CRASH_CAP = 1000.0


class CrashView(CashoutGame):
    key = "crash"

    def __init__(self, author, bet, game, guild, auto):
        super().__init__(author, bet, game, guild)
        self.timeout = None  # la boucle gère la fin de partie
        self.crash = min(CRASH_CAP, crash_point_from(game.rng.random()))
        self.auto = auto
        self.t0 = None
        self.history = [1.0]
        self.crashed = False

    def growth(self, t):
        return math.floor(math.exp(CRASH_SPEED * t) * 100) / 100

    def has_progress(self):
        return True

    async def start(self, interaction):
        await self.show(interaction, status="Décollage…" + (f" · auto x{self.auto:g}" if self.auto else ""))
        self.t0 = time.monotonic()
        self._task = asyncio.create_task(self._run_safe())

    async def _run_safe(self):
        try:
            await self.run()
        except Exception as e:
            log.error(f"Crash loop : {e}\n{traceback.format_exc()}")
            async with self.lock:
                if not self.finished:
                    await self.refund("⚠️ Erreur pendant la partie — mise remboursée")

    def render(self, status=None, status_color=None, final=False, reveal=False):
        col = RED if self.crashed else self.theme if not final else GREEN
        img, d = base_canvas(col, self.title)
        px0, py0, px1, py1 = 80, 120, W - 80, H - 120
        d.line([(px0, py1), (px1, py1)], fill=(60, 64, 72), width=2)
        d.line([(px0, py0), (px0, py1)], fill=(60, 64, 72), width=2)
        pts = self.history
        if len(pts) >= 2:
            top = max(2.0, max(pts))
            coords = [(px0 + (px1 - px0) * k / (len(pts) - 1), py1 - (py1 - py0) * (m - 1) / (top - 1)) for k, m in enumerate(pts)]
            d.polygon(coords + [(coords[-1][0], py1), (px0, py1)], fill=_mix(col, (10, 10, 14), 0.75))
            d.line(coords, fill=col, width=5, joint="curve")
            d.ellipse([coords[-1][0] - 7, coords[-1][1] - 7, coords[-1][0] + 7, coords[-1][1] + 7], fill=WHITE)
        shown = self.crash if self.crashed else self.mult
        draw_big(d, f"{shown:.2f}x", col, (py0 + py1) / 2 - 10, size=92)
        if self.crashed:
            d.text((W / 2, (py0 + py1) / 2 + 56), "CRASH", font=F(28, "ExtraBold"), fill=RED, anchor="mm")
        if self.auto:
            d.text((px1, py0 - 8), f"Auto-cashout x{self.auto:g}", font=F(18, "SemiBold"), fill=GREY, anchor="rb")
        self.footer(d, status, status_color, accent=col)
        return img

    async def run(self):
        while True:
            await asyncio.sleep(CRASH_TICK)
            async with self.lock:
                if self.finished:
                    return
                m = self.growth(time.monotonic() - self.t0)
                if self.auto and self.auto < self.crash and m >= self.auto:
                    self.mult = self.auto
                    self.history.append(self.auto)
                    return await self.finish(None, self.auto, f"Auto-cashout x{self.auto:g}")
                if m >= self.crash:
                    self.crashed = True
                    self.history.append(self.crash)
                    return await self.finish(None, 0, f"Crash à x{self.crash:.2f}")
                self.mult = m
                self.history.append(m)
                try:
                    file = await self.frame(status=f"x{m:.2f} → {fmt(payout_of(self.bet, m))}")
                    await self.message.edit(attachments=[file], embed=game_embed(self.game), view=self)
                except discord.HTTPException:
                    pass

    @discord.ui.button(label="Encaisser", emoji="💰", style=discord.ButtonStyle.success)
    async def cash(self, interaction: discord.Interaction, b):
        t_click = time.monotonic()
        async with self.lock:
            if self.finished:
                return await safe_defer(interaction)
            m = self.growth(t_click - self.t0)
            if m >= self.crash:
                self.crashed = True
                self.history.append(self.crash)
                return await self.finish(interaction, 0, f"Crash à x{self.crash:.2f}")
            if m <= 1.0:
                return await interaction.response.send_message("La fusée n'a pas encore décollé !", ephemeral=True)
            self.mult = m
            self.history.append(m)
            await self.finish(interaction, m, f"Encaissé x{m:.2f}")


async def launch_crash(interaction, author, bet, game):
    setup = ChoiceSetupView(
        author, bet, game, interaction.guild, "crash", "AUTO-CASHOUT ?", "le bot encaisse pour toi à ce multiplicateur",
        [("Manuel", 0, discord.ButtonStyle.primary), ("x1.5", 1.5, discord.ButtonStyle.secondary),
         ("x2", 2, discord.ButtonStyle.secondary), ("x5", 5, discord.ButtonStyle.secondary), ("x10", 10, discord.ButtonStyle.danger)],
        lambda a: CrashView(author, bet, game, interaction.guild, a))
    await setup.show(interaction)
GAME_LAUNCHERS["crash"] = launch_crash


# ---- HI-LO (règles Stake : "plus haut ou égal" / "plus bas ou égal") ----

@register("hilo")
class HiloView(CashoutGame):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.card = rand_card(self.game.rng)
        self.last = None
        self.skips = 0
        self.streak = 0
        self.sync()

    def has_progress(self):
        return self.streak > 0  # au moins un bon pronostic (même si x < 1 après un "As plus haut")

    def idx(self, card=None):
        return RANKS.index((card or self.card)[0])

    def p_high(self):
        return (13 - self.idx()) / 13

    def p_low(self):
        return (self.idx() + 1) / 13

    def m_high(self):
        return (1 - HOUSE_EDGE) / self.p_high()

    def m_low(self):
        return (1 - HOUSE_EDGE) / self.p_low()

    def sync(self):
        self.higher.label = f"Plus haut/égal x{self.m_high():.2f}"
        self.lower.label = f"Plus bas/égal x{self.m_low():.2f}"
        self.cash_btn.label = f"Encaisser {fmt(payout_of(self.bet, self.mult))}" if self.mult > 1 else "Encaisser"

    async def start(self, interaction):
        await self.show(interaction, status="Plus haut ou plus bas ?")

    def render(self, status=None, status_color=None, final=False, reveal=False):
        img, d = self.canvas()
        draw_card(d, 120, CY - 92, 130, 182, self.card)
        d.text((185, CY - 112), "Carte actuelle", font=F(18, "Medium"), fill=GREY, anchor="mm")
        if self.last is not None:
            draw_card(d, 300, CY - 72, 100, 142, self.last, glow=RED if final and self.mult == 0 else None)
            d.text((350, CY - 92), "Précédente", font=F(16, "Medium"), fill=GREY, anchor="mm")
        lines = [("Plus haut/égal", f"x{self.m_high():.2f}  ({self.p_high() * 100:.1f}%)", GREEN),
                 ("Plus bas/égal", f"x{self.m_low():.2f}  ({self.p_low() * 100:.1f}%)", (52, 152, 219)),
                 ("Total", f"x{self.mult:.2f}", WHITE), ("Gain", fmt(payout_of(self.bet, self.mult)), GOLD)]
        for k, (lab, val, col) in enumerate(lines):
            d.text((W - 80, 118 + k * 58), lab, font=F(17, "Medium"), fill=GREY, anchor="ra")
            d.text((W - 80, 138 + k * 58), val, font=F(26, "ExtraBold"), fill=col, anchor="ra")
        self.footer(d, status, status_color)
        return img

    async def _guess(self, interaction, high):
        p_mult = self.m_high() if high else self.m_low()
        new = rand_card(self.game.rng)
        self.last = self.card
        ok = self.idx(new) >= self.idx() if high else self.idx(new) <= self.idx()
        self.card = new
        if not ok:
            self.mult = 0
            return await self.finish(interaction, 0, "Raté")
        self.mult = round(self.mult * p_mult, 4)
        self.streak += 1
        self.sync()
        await self.update(interaction, status=f"Bien joué ! x{self.mult:.2f}")

    @discord.ui.button(label="Plus haut", emoji="⬆️", style=discord.ButtonStyle.success, row=0)
    @action
    async def higher(self, i, b): await self._guess(i, True)

    @discord.ui.button(label="Plus bas", emoji="⬇️", style=discord.ButtonStyle.primary, row=0)
    @action
    async def lower(self, i, b): await self._guess(i, False)

    @discord.ui.button(label="Passer", emoji="⏭️", style=discord.ButtonStyle.secondary, row=1)
    @action
    async def skip(self, i, b):
        if self.skips >= 52:
            return await i.response.send_message("Trop de cartes passées.", ephemeral=True)
        self.skips += 1
        self.last, self.card = self.card, rand_card(self.game.rng)
        self.sync()
        await self.update(i, status="Carte passée")

    @discord.ui.button(label="Encaisser", emoji="💰", style=discord.ButtonStyle.danger, row=1)
    @action
    async def cash_btn(self, i, b): await self.cashout(i)


# ---- DRAGON TOWER ----
DRAGON_DIFF = {"easy": (4, 3), "medium": (3, 2), "hard": (2, 1), "expert": (3, 1), "master": (4, 1)}
DRAGON_ROWS = 9


class DragonTile(discord.ui.Button):
    def __init__(self, col):
        super().__init__(label=f"Case {col + 1}", style=discord.ButtonStyle.secondary, row=0)
        self.col = col

    async def callback(self, interaction: discord.Interaction):
        await self.view.climb(interaction, self.col)


class DragonView(CashoutGame):
    key = "dragon"

    def __init__(self, author, bet, game, guild, diff):
        super().__init__(author, bet, game, guild)
        self.diff = diff
        self.tiles, self.safe = DRAGON_DIFF[diff]
        self.step = (self.tiles / self.safe) * (1 - HOUSE_EDGE)
        self.safe_cols = [set(game.rng.shuffle(range(self.tiles))[:self.safe]) for _ in range(DRAGON_ROWS)]
        self.level = 0
        self.path = []
        self.dead = None
        for c in range(self.tiles):
            self.add_item(DragonTile(c))
        self.cash_btn = discord.ui.Button(label="Encaisser", emoji="💰", style=discord.ButtonStyle.danger, row=1)
        self.cash_btn.callback = self._cash
        self.add_item(self.cash_btn)

    async def start(self, interaction):
        await self.show(interaction, status=f"{self.diff.capitalize()} — choisis une case")

    def render(self, status=None, status_color=None, final=False, reveal=False):
        img, d = self.canvas()
        top, bot = 104, H - 94
        rh = (bot - top) / DRAGON_ROWS
        cw = 96
        x0 = W / 2 + 60 - self.tiles * cw / 2
        for r in range(DRAGON_ROWS):
            lvl = DRAGON_ROWS - 1 - r
            y = top + r * rh
            for c in range(self.tiles):
                x = x0 + c * cw
                box = [x + 4, y + 3, x + cw - 4, y + rh - 3]
                if (lvl, c) in self.path:
                    d.rounded_rectangle(box, radius=8, fill=_mix(self.theme, (10, 10, 14), 0.5), outline=self.theme, width=2)
                    _gem(d, x + cw / 2, y + rh / 2, rh * 0.25, GREEN)
                elif self.dead == (lvl, c):
                    d.rounded_rectangle(box, radius=8, fill=(130, 30, 26), outline=RED, width=2)
                    d.text((x + cw / 2, y + rh / 2), "X", font=F(int(rh * 0.6), "ExtraBold"), fill=WHITE, anchor="mm")
                elif reveal or final:
                    safe = c in self.safe_cols[lvl]
                    d.rounded_rectangle(box, radius=8, fill=(34, 44, 36) if safe else (60, 30, 28),
                                        outline=(70, 110, 80) if safe else (120, 50, 45), width=1)
                else:
                    here = lvl == self.level
                    d.rounded_rectangle(box, radius=8, fill=(66, 70, 80) if here else DARK, outline=(80, 84, 94), width=1)
            mult = round(self.step ** (lvl + 1), 2)
            d.text((x0 - 14, y + rh / 2), f"x{mult:g}", font=F(14, "SemiBold"), fill=GREY, anchor="rm")
        d.text((60, 120), self.diff.upper(), font=F(22, "Bold"), fill=self.theme)
        d.text((60, 150), f"x{self.mult:.2f}", font=F(36, "ExtraBold"), fill=WHITE)
        d.text((60, 196), fmt(payout_of(self.bet, self.mult)), font=F(22, "SemiBold"), fill=GOLD)
        self.footer(d, status, status_color)
        return img

    async def climb(self, interaction, col):
        async with self.lock:
            if self.finished:
                return await safe_defer(interaction)
            if col not in self.safe_cols[self.level]:
                self.dead = (self.level, col)
                return await self.finish(interaction, 0, "Dragon !", reveal=True)
            self.path.append((self.level, col))
            self.level += 1
            self.mult = round(self.step ** self.level, 4)
            if self.level >= DRAGON_ROWS:
                return await self.finish(interaction, self.mult, "Sommet atteint !", reveal=True)
            self.cash_btn.label = f"Encaisser {fmt(payout_of(self.bet, self.mult))}"
            await self.update(interaction, status=f"Niveau {self.level} · x{self.mult:.2f}")

    async def _cash(self, interaction):
        async with self.lock:
            if self.finished:
                return await safe_defer(interaction)
            await self.cashout(interaction)


async def launch_dragon(interaction, author, bet, game):
    setup = ChoiceSetupView(
        author, bet, game, interaction.guild, "dragon", "DIFFICULTÉ ?", "plus dur = moins de cases sûres, plus de gains",
        [("Easy", "easy", discord.ButtonStyle.success), ("Medium", "medium", discord.ButtonStyle.primary),
         ("Hard", "hard", discord.ButtonStyle.secondary), ("Expert", "expert", discord.ButtonStyle.secondary),
         ("Master", "master", discord.ButtonStyle.danger)],
        lambda diff: DragonView(author, bet, game, interaction.guild, diff))
    await setup.show(interaction)
GAME_LAUNCHERS["dragon"] = launch_dragon


# ---- CHICKEN & PUMP ----
LADDER_DIFF = {"easy": 0.95, "medium": 0.84, "hard": 0.68, "hardcore": 0.50}
LADDER_MAX_STEPS = 25


class LadderView(CashoutGame):
    def __init__(self, author, bet, game, guild, key, diff):
        self.key = key
        super().__init__(author, bet, game, guild)
        self.diff, self.p = diff, LADDER_DIFF[diff]
        self.steps = 0
        self.dead = False
        self.go.label = "Avancer" if key == "chicken" else "Gonfler"
        self.go.emoji = "🐔" if key == "chicken" else "🎈"

    def next_mult(self):
        return round(self.mult * (1 - HOUSE_EDGE) / self.p, 4)

    async def start(self, interaction):
        await self.show(interaction, status=f"{self.diff.capitalize()} · {int(self.p * 100)}% de réussite par étape")

    def render(self, status=None, status_color=None, final=False, reveal=False):
        img, d = self.canvas()
        if self.key == "pump":
            r = 64 + min(96, self.steps * 8)
            col = RED if self.dead else self.theme
            if self.dead:
                for k in range(12):
                    a = k * math.pi / 6
                    d.line([(W / 2 + 30 * math.cos(a), CY - 10 + 30 * math.sin(a)),
                            (W / 2 + 110 * math.cos(a), CY - 10 + 110 * math.sin(a))], fill=RED, width=6)
                d.text((W / 2, CY - 10), "POP !", font=F(54, "ExtraBold"), fill=WHITE, anchor="mm")
            else:
                d.ellipse([W / 2 - r * 0.85, CY - 10 - r, W / 2 + r * 0.85, CY - 10 + r], fill=_mix(col, WHITE, 0.12),
                          outline=_mix(col, (0, 0, 0), 0.3), width=4)
                d.line([(W / 2, CY - 10 + r), (W / 2, CY + 120)], fill=GREY, width=3)
                d.text((W / 2, CY - 10), f"x{self.mult:.2f}", font=F(30 if r < 90 else 40, "ExtraBold"), fill=WHITE, anchor="mm")
        else:
            lanes = 10
            lw = (W - 160) / lanes
            off = max(0, self.steps - lanes + 2)
            for i in range(lanes):
                x = 80 + i * lw
                lane_n = i + off
                fill = (60, 64, 72) if lane_n < self.steps else DARK
                d.rounded_rectangle([x + 4, CY - 40, x + lw - 4, CY + 40], radius=8, fill=fill)
                for yy in range(int(CY - 36), int(CY + 36), 18):
                    d.line([(x + lw - 4, yy), (x + lw - 4, yy + 9)], fill=(200, 200, 200), width=2)
                m = round(((1 - HOUSE_EDGE) / self.p) ** (lane_n + 1), 2)
                d.text((x + lw / 2, CY + 56), f"x{m:g}", font=F(14, "SemiBold"), fill=GREY, anchor="mm")
            px = 80 + (self.steps - off) * lw - lw / 2 if self.steps else 60
            d.ellipse([px - 20, CY - 20, px + 20, CY + 20], fill=RED if self.dead else (250, 250, 250), outline=GOLD, width=3)
            d.polygon([(px + 18, CY - 4), (px + 30, CY), (px + 18, CY + 4)], fill=GOLD)
            d.text((W / 2, CY - 70), f"x{self.mult:.2f}", font=F(40, "ExtraBold"), fill=RED if self.dead else self.theme, anchor="mm")
        d.text((W / 2, CY + 96), f"prochain x{self.next_mult():.2f} · gain {fmt(payout_of(self.bet, self.mult))}",
               font=F(19, "Medium"), fill=GREY, anchor="mm")
        self.footer(d, status, status_color)
        return img

    @discord.ui.button(label="Avancer", style=discord.ButtonStyle.success)
    @action
    async def go(self, i, b):
        if self.game.rng.random() < self.p:
            self.steps += 1
            self.mult = self.next_mult()
            if self.steps >= LADDER_MAX_STEPS:
                return await self.finish(i, self.mult, "Maximum atteint !")
            self.cash_btn.label = f"Encaisser {fmt(payout_of(self.bet, self.mult))}"
            await self.update(i, status=f"Étape {self.steps} · x{self.mult:.2f}")
        else:
            self.dead = True
            await self.finish(i, 0, "Éclaté !" if self.key == "pump" else "Écrasé !")

    @discord.ui.button(label="Encaisser", emoji="💰", style=discord.ButtonStyle.danger)
    @action
    async def cash_btn(self, i, b): await self.cashout(i)


def _ladder_launcher(key):
    async def launch(interaction, author, bet, game):
        setup = ChoiceSetupView(
            author, bet, game, interaction.guild, key, "DIFFICULTÉ ?", "plus risqué = plus gros multiplicateurs",
            [("Easy 95%", "easy", discord.ButtonStyle.success), ("Medium 84%", "medium", discord.ButtonStyle.primary),
             ("Hard 68%", "hard", discord.ButtonStyle.secondary), ("Hardcore 50%", "hardcore", discord.ButtonStyle.danger)],
            lambda diff: LadderView(author, bet, game, interaction.guild, key, diff))
        await setup.show(interaction)
    return launch


GAME_LAUNCHERS["chicken"] = _ladder_launcher("chicken")
GAME_LAUNCHERS["pump"] = _ladder_launcher("pump")


# ---- BLACKJACK (infinite deck, croupier tire jusqu'à 17, peek BJ, 3:2) ----

def bj_value(cards):
    total, aces = 0, 0
    for r, _ in cards:
        if r == "A":
            total, aces = total + 11, aces + 1
        elif r in ("K", "Q", "J", "10"):
            total += 10
        else:
            total += int(r)
    while total > 21 and aces:
        total, aces = total - 10, aces - 1
    return total


@register("blackjack")
class BlackjackView(GameView):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        rng = self.game.rng
        self.player = [rand_card(rng), rand_card(rng)]
        self.dealer = [rand_card(rng), rand_card(rng)]
        self.doubled = False
        self.revealed = False

    def bet_total(self):
        return self.bet * (2 if self.doubled else 1)

    async def start(self, interaction):
        pbj, dbj = bj_value(self.player) == 21, bj_value(self.dealer) == 21
        if pbj or dbj:
            self.revealed = True
            m = 1 if (pbj and dbj) else (2.5 if pbj else 0)
            label = "Égalité de Blackjacks" if pbj and dbj else ("BLACKJACK !" if pbj else "Blackjack du croupier")
            return await self.finish(interaction, m, label)
        self.double_btn.disabled = get_balance(self.author.id) < self.bet
        await self.show(interaction, status="Hit, Stand ou Double ?")

    def render(self, status=None, status_color=None, final=False, reveal=False):
        img, d = self.canvas()
        show_all = self.revealed or final

        def hand(cards, label, yy, hide):
            val = bj_value(cards) if not hide else bj_value(cards[1:])
            d.text((90, yy - 32), f"{label}  {val if not hide else str(val) + ' + ?'}", font=F(22, "SemiBold"), fill=GREY)
            for k, c in enumerate(cards):
                draw_card(d, 90 + k * 92, yy, 80, 114, c, face_up=not (hide and k == 0))
        hand(self.dealer, "Croupier", 128, not show_all)
        hand(self.player, "Toi", 290, False)
        if self.doubled:
            d.text((W - 80, 300), "DOUBLÉ", font=F(26, "ExtraBold"), fill=self.theme, anchor="ra")
        self.footer(d, status, status_color)
        return img

    async def _resolve(self, interaction):
        self.revealed = True
        while bj_value(self.dealer) < 17:
            self.dealer.append(rand_card(self.game.rng))
        pv, dv = bj_value(self.player), bj_value(self.dealer)
        if pv > 21:
            m, lab = 0, "Bust"
        elif dv > 21 or pv > dv:
            m, lab = 2, "Gagné"
        elif pv < dv:
            m, lab = 0, "Le croupier gagne"
        else:
            m, lab = 1, "Égalité"
        await self.finish(interaction, m, f"{lab} ({pv} vs {dv})")

    async def auto_finish(self):
        await self._resolve(None)  # timeout = Stand automatique

    @discord.ui.button(label="Hit", emoji="🃏", style=discord.ButtonStyle.primary)
    @action
    async def hit(self, i, b):
        self.player.append(rand_card(self.game.rng))
        self.double_btn.disabled = True
        pv = bj_value(self.player)
        if pv > 21:
            self.revealed = True
            return await self.finish(i, 0, f"Bust ({pv})")
        if pv == 21:
            return await self._resolve(i)
        await self.update(i, status="Hit ou Stand ?")

    @discord.ui.button(label="Stand", emoji="✋", style=discord.ButtonStyle.success)
    @action
    async def stand(self, i, b): await self._resolve(i)

    @discord.ui.button(label="Double", emoji="✖️", style=discord.ButtonStyle.secondary)
    @action
    async def double_btn(self, i, b):
        if len(self.player) != 2:
            return await i.response.send_message("Double uniquement sur les 2 premières cartes.", ephemeral=True)
        if not raise_bet(self.game.id, self.author.id, self.bet):
            return await i.response.send_message("Solde insuffisant pour doubler.", ephemeral=True)
        self.doubled = True
        self.player.append(rand_card(self.game.rng))
        if bj_value(self.player) > 21:
            self.revealed = True
            return await self.finish(i, 0, f"Bust ({bj_value(self.player)})")
        await self._resolve(i)


# ---- VIDEO POKER (Jacks or Better 9/6) ----
_RVAL = {r: v for v, r in enumerate(["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"], start=2)}
POKER_PAYS = [("Quinte flush royale", 250), ("Quinte flush", 50), ("Carré", 25), ("Full", 9), ("Couleur", 6),
              ("Suite", 4), ("Brelan", 3), ("Deux paires", 2), ("Paire de valets+", 1)]


def poker_eval(cards):
    vals = sorted(_RVAL[r] for r, _ in cards)
    counts = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1
    cc = sorted(counts.values(), reverse=True)
    flush = len({s for _, s in cards}) == 1
    straight = (len(counts) == 5 and vals[-1] - vals[0] == 4) or vals == [2, 3, 4, 5, 14]
    if straight and flush and vals[0] == 10:
        return POKER_PAYS[0]
    if straight and flush:
        return POKER_PAYS[1]
    if cc[0] == 4:
        return POKER_PAYS[2]
    if cc[:2] == [3, 2]:
        return POKER_PAYS[3]
    if flush:
        return POKER_PAYS[4]
    if straight:
        return POKER_PAYS[5]
    if cc[0] == 3:
        return POKER_PAYS[6]
    if cc[:2] == [2, 2]:
        return POKER_PAYS[7]
    if cc[0] == 2 and max(v for v, n in counts.items() if n == 2) >= 11:
        return POKER_PAYS[8]
    return ("Rien", 0)


class HoldButton(discord.ui.Button):
    def __init__(self, index):
        super().__init__(label=f"Garder {index + 1}", style=discord.ButtonStyle.secondary, row=0)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        v = self.view
        async with v.lock:
            if v.finished:
                return await safe_defer(interaction)
            if self.index in v.held:
                v.held.discard(self.index)
                self.style = discord.ButtonStyle.secondary
            else:
                v.held.add(self.index)
                self.style = discord.ButtonStyle.success
            await v.update(interaction, status="Garde tes cartes puis Tire")


@register("videopoker")
class VideoPokerView(GameView):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.deck = shuffled_deck(self.game.rng)
        self.hand = [self.deck.pop() for _ in range(5)]
        self.held = set()
        for k in range(5):
            self.add_item(HoldButton(k))
        btn = discord.ui.Button(label="Tirer", emoji="🎴", style=discord.ButtonStyle.primary, row=1)
        btn.callback = self._draw
        self.add_item(btn)

    async def start(self, interaction):
        await self.show(interaction, status=f"Main actuelle : {poker_eval(self.hand)[0]}")

    def render(self, status=None, status_color=None, final=False, reveal=False):
        img, d = self.canvas()
        cw, ch, gap = 112, 158, 18
        x0 = 60
        for k in range(5):
            x = x0 + k * (cw + gap)
            draw_card(d, x, CY - ch / 2 - 14, cw, ch, self.hand[k], glow=self.theme if k in self.held else None)
            if k in self.held:
                d.rounded_rectangle([x, CY + ch / 2 - 4, x + cw, CY + ch / 2 + 22], radius=6, fill=self.theme)
                d.text((x + cw / 2, CY + ch / 2 + 9), "GARDÉE", font=F(16, "Bold"), fill=(10, 10, 14), anchor="mm")
        current = poker_eval(self.hand)[0]
        for k, (lab, m) in enumerate(POKER_PAYS):
            col = GOLD if lab == current else GREY
            d.text((W - 60, 112 + k * 28), f"{lab}  {m}x", font=F(16, "SemiBold"), fill=col, anchor="ra")
        self.footer(d, status, status_color)
        return img

    async def _do_draw(self, interaction):
        for k in range(5):
            if k not in self.held:
                self.hand[k] = self.deck.pop()
        label, m = poker_eval(self.hand)
        await self.finish(interaction, m, label)

    async def _draw(self, interaction):
        async with self.lock:
            if self.finished:
                return await safe_defer(interaction)
            await self._do_draw(interaction)

    async def auto_finish(self):
        await self._do_draw(None)


# ========================= COMMANDES DE JEU =========================

def _make_game_command(key):
    async def _cmd(ctx, bet: str = None):
        prefill = max(setting("min_bet"), 100)
        if bet is not None:
            parsed = parse_amount(bet, get_balance(ctx.author.id))
            if parsed is None:
                return await ctx.send(embed=error_embed("❌ Mise invalide", "Exemples : 100, 1k, 50%, all."))
            prefill = parsed
        await open_bet_setup(ctx, key, prefill)
    _cmd.__name__ = f"game_{key}"
    return _cmd


for _key in GAMES:
    bot.command(name=_key, aliases=GAME_ALIASES.get(_key, []))(_make_game_command(_key))


@bot.command(name="games", aliases=["jeux"])
async def _games(ctx):
    p = get_prefix_cached()
    em = info_embed("🎰 Jeux disponibles", f"Lance un jeu avec `{p}<jeu> [mise]` — ex : `{p}mines 500`")
    for cat, label in (("originals", "⭐ Originals"), ("casino", "🃏 Casino")):
        em.add_field(name=label, value="\n".join(f"{v[2]} `{p}{k}` — {v[3]}" for k, v in GAMES.items() if v[4] == cat)[:1024],
                     inline=False)
    apply_thumbnail(em, ctx.guild)
    await ctx.send(embed=em)


# ========================= ÉCONOMIE =========================

@bot.command(name="balance", aliases=["bal", "solde", "wallet"])
async def _balance(ctx, *, user_input: str = None):
    display, uid = (ctx.author, ctx.author.id) if not user_input else await resolve_user_or_id(ctx, user_input)
    if uid is None:
        return await ctx.send(embed=error_embed("❌ Utilisateur introuvable", "Mention, ID ou nom requis."))
    u = get_user(uid)
    vip = vip_for(u["wagered"])
    name = getattr(display, "display_name", None) or f"ID {uid}"
    em = discord.Embed(title=f"{SYMBOL} Portefeuille — {name}", color=embed_color())
    em.add_field(name="Solde", value=money(u["balance"]), inline=True)
    em.add_field(name="VIP", value=f"{vip[2]} {vip[1]}", inline=True)
    em.add_field(name="Rakeback dispo", value=money(int(u["rakeback"])), inline=True)
    if display is not None:
        em.set_thumbnail(url=display.display_avatar.url)
    await ctx.send(embed=em)


@bot.command(name="profil", aliases=["profile", "stats"])
async def _profil(ctx, *, user_input: str = None):
    display, uid = (ctx.author, ctx.author.id) if not user_input else await resolve_user_or_id(ctx, user_input)
    if uid is None:
        return await ctx.send(embed=error_embed("❌ Utilisateur introuvable", "Mention, ID ou nom requis."))
    u = get_user(uid)
    vip, nxt = vip_for(u["wagered"]), next_vip(u["wagered"])
    fav = db_one("SELECT game, COUNT(*) AS n FROM bets WHERE user_id = ? GROUP BY game ORDER BY n DESC LIMIT 1", (str(uid),))
    name = getattr(display, "display_name", None) or f"ID {uid}"
    em = discord.Embed(title=f"📊 Profil — {name}", color=embed_color())
    em.add_field(name="Solde", value=money(u["balance"]), inline=True)
    em.add_field(name="VIP", value=f"{vip[2]} **{vip[1]}** ({int(vip[3] * 100)}% rakeback)", inline=True)
    em.add_field(name="Parties", value=f"**{fmt(u['games'])}**", inline=True)
    em.add_field(name="Total misé", value=money(u["wagered"]), inline=True)
    em.add_field(name="Profit", value=("🟢 +" if u["profit"] >= 0 else "🔴 -") + money(abs(u["profit"])), inline=True)
    em.add_field(name="Plus gros gain", value=money(u["biggest_win"]), inline=True)
    if fav:
        em.add_field(name="Jeu préféré", value=f"{GAMES[fav['game']][2]} {GAMES[fav['game']][0]} ({fav['n']} parties)", inline=True)
    if nxt:
        pct = min(100, int(100 * (u["wagered"] - vip[0]) / max(1, nxt[0] - vip[0])))
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        em.add_field(name=f"Prochain VIP : {nxt[2]} {nxt[1]}", value=f"`{bar}` {pct}% — encore {money(nxt[0] - u['wagered'])} à miser",
                     inline=False)
    if display is not None:
        em.set_thumbnail(url=display.display_avatar.url)
    await ctx.send(embed=em)


@bot.command(name="historique", aliases=["history", "bets"])
async def _historique(ctx, *, user_input: str = None):
    display, uid = (ctx.author, ctx.author.id) if not user_input else await resolve_user_or_id(ctx, user_input)
    if uid is None:
        return await ctx.send(embed=error_embed("❌ Utilisateur introuvable", "Mention, ID ou nom requis."))
    rows = db_all("SELECT * FROM bets WHERE user_id = ? ORDER BY id DESC LIMIT 15", (str(uid),))
    if not rows:
        return await ctx.send(embed=info_embed("📜 Historique", "Aucune partie jouée."))
    lines = []
    for r in rows:
        delta = r["payout"] - r["bet"]
        sign = "🟢 +" if delta > 0 else ("⚪ " if delta == 0 else "🔴 -")
        lines.append(f"<t:{r['ts']}:R> {GAMES[r['game']][2]} **{GAMES[r['game']][0]}** · {fmt(r['bet'])} → x{r['mult']:.2f} · {sign}{fmt(abs(delta))}")
    name = getattr(display, "display_name", None) or f"ID {uid}"
    await ctx.send(embed=info_embed(f"📜 Historique — {name}", "\n".join(lines)[:4000]))


@bot.command(name="daily", aliases=["quotidien"])
async def _daily(ctx):
    u = get_user(ctx.author.id)
    now = now_ts()
    elapsed = now - u["last_daily"]
    if elapsed < 86400:
        return await ctx.send(embed=error_embed("⏳ Déjà récupéré", f"Reviens <t:{u['last_daily'] + 86400}:R>."))
    streak = u["streak"] + 1 if elapsed < 2 * 86400 else 1
    vip = vip_for(u["wagered"])
    vip_bonus = VIP_LEVELS.index(vip) * 0.10
    base = setting("daily_amount")
    bonus = min(streak, 7) * setting("daily_streak")
    total = int((base + bonus) * (1 + vip_bonus))
    rc, _ = db_exec("UPDATE users SET balance = balance + ?, last_daily = ?, streak = ? WHERE user_id = ? AND last_daily = ?",
                    (total, now, streak, str(ctx.author.id), u["last_daily"]))
    if rc != 1:
        return
    em = success_embed("🎁 Récompense quotidienne", f"Tu reçois {money(total)} !")
    em.add_field(name="Base", value=money(base), inline=True)
    em.add_field(name=f"Série x{streak}", value=money(bonus), inline=True)
    if vip_bonus:
        em.add_field(name=f"Bonus VIP {vip[2]}", value=f"+{int(vip_bonus * 100)}%", inline=True)
    em.add_field(name="Nouveau solde", value=money(get_balance(ctx.author.id)), inline=False)
    await ctx.send(embed=em)


WORK_JOBS = ["as distribué les cartes", "as nettoyé les machines à sous", "as servi les high rollers",
             "as compté le coffre", "as fait tourner la roulette", "as garé les voitures de luxe"]


@bot.command(name="work", aliases=["travail", "grind"])
async def _work(ctx):
    u = get_user(ctx.author.id)
    now, cd = now_ts(), setting("work_cooldown")
    if now - u["last_work"] < cd:
        return await ctx.send(embed=error_embed("⏳ Tu es fatigué", f"Retravaille <t:{u['last_work'] + cd}:R>."))
    lo, hi = sorted((setting("work_min"), setting("work_max")))
    amount = lo + secrets.randbelow(hi - lo + 1)
    rc, _ = db_exec("UPDATE users SET balance = balance + ?, last_work = ? WHERE user_id = ? AND last_work = ?",
                    (amount, now, str(ctx.author.id), u["last_work"]))
    if rc != 1:
        return
    await ctx.send(embed=success_embed("💼 Travail", f"Tu {WORK_JOBS[secrets.randbelow(len(WORK_JOBS))]} et gagnes {money(amount)}.\n"
                                                     f"Solde : {money(get_balance(ctx.author.id))}"))


@bot.command(name="rakeback", aliases=["rb"])
async def _rakeback(ctx):
    u = get_user(ctx.author.id)
    amount = int(u["rakeback"])
    vip = vip_for(u["wagered"])
    if amount < 1:
        return await ctx.send(embed=info_embed("💸 Rakeback", f"Rien à récupérer pour l'instant.\nTon niveau VIP {vip[2]} **{vip[1]}** "
                                                             f"te reverse **{int(vip[3] * 100)}%** de l'avantage maison sur chaque mise."))
    db_exec("UPDATE users SET balance = balance + ?, rakeback = rakeback - ? WHERE user_id = ?", (amount, amount, str(ctx.author.id)))
    await ctx.send(embed=success_embed("💸 Rakeback récupéré", f"+{money(amount)} · Solde : {money(get_balance(ctx.author.id))}"))


@bot.command(name="vip")
async def _vip(ctx):
    u = get_user(ctx.author.id)
    cur = vip_for(u["wagered"])
    lines = [f"{'➡️' if lvl == cur else '▫️'} {lvl[2]} **{lvl[1]}** — dès {money(lvl[0])} misés · {int(lvl[3] * 100)}% rakeback · "
             f"+{VIP_LEVELS.index(lvl) * 10}% daily" for lvl in VIP_LEVELS[1:]]
    await ctx.send(embed=info_embed("💎 Niveaux VIP", "\n".join(lines) + f"\n\nTon total misé : {money(u['wagered'])}"))


class GiveConfirm(OwnerView):
    def __init__(self, author, target, amount):
        super().__init__(author, timeout=60)
        self.target, self.amount, self.done = target, amount, False

    @discord.ui.button(label="Confirmer", emoji="✅", style=discord.ButtonStyle.success)
    async def ok(self, interaction: discord.Interaction, b):
        if self.done:
            return await safe_defer(interaction)
        self.done = True
        self.stop()
        if not debit(self.author.id, self.amount):
            return await interaction.response.edit_message(embed=error_embed("❌ Solde insuffisant", "Transfert annulé."), view=None)
        credit(self.target.id, self.amount)
        await interaction.response.edit_message(
            embed=success_embed("✅ Transfert effectué", f"{self.author.mention} → {self.target.mention} : {money(self.amount)}"), view=None)
        await admin_log(interaction.guild, "Transfert", self.author, f"→ {self.target.mention} : {money(self.amount)}", color=0x3498db)

    @discord.ui.button(label="Annuler", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, b):
        self.done = True
        self.stop()
        await interaction.response.edit_message(embed=error_embed("✖️ Transfert annulé"), view=None)


@bot.command(name="give", aliases=["pay", "donner"])
async def _give(ctx, user_input: str = None, amount: str = None):
    p = get_prefix_cached()
    if not user_input or not amount:
        return await ctx.send(embed=error_embed("❌ Usage", f"{p}give @user <montant>"))
    display, uid = await resolve_user_or_id(ctx, user_input)
    if uid is None or display is None or getattr(display, "bot", False) or uid == ctx.author.id:
        return await ctx.send(embed=error_embed("❌ Destinataire invalide", "Mentionne un autre joueur."))
    amt = parse_amount(amount, get_balance(ctx.author.id))
    if amt is None:
        return await ctx.send(embed=error_embed("❌ Montant invalide", "Exemples : 500, 2k, 50%, all."))
    if amt > get_balance(ctx.author.id):
        return await ctx.send(embed=error_embed("❌ Solde insuffisant", f"Tu as {money(get_balance(ctx.author.id))}."))
    view = GiveConfirm(ctx.author, display, amt)
    view.message = await ctx.send(embed=info_embed("💸 Confirmer le transfert", f"Envoyer {money(amt)} à {display.mention} ?"), view=view)


LB_KINDS = {"balance": ("Solde", "balance"), "wagered": ("Total misé", "wagered"), "profit": ("Profit", "profit")}


def build_lb_embed(guild, kind):
    label, col = LB_KINDS[kind]
    rows = db_all(f"SELECT user_id, {col} AS v FROM users ORDER BY {col} DESC LIMIT 10")
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = []
    for i, r in enumerate(rows, 1):
        lines.append(f"{medals.get(i, f'**{i}.**')} <@{r['user_id']}> — {money(r['v'])}")
    em = info_embed(f"🏆 Classement — {label}", "\n".join(lines) or "Aucun joueur.")
    apply_thumbnail(em, guild)
    return em


class LeaderboardView(OwnerView):
    def __init__(self, author, guild):
        super().__init__(author, timeout=120)
        self.guild = guild
        for kind, (label, _c) in LB_KINDS.items():
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
            btn.callback = self._cb(kind)
            self.add_item(btn)

    def _cb(self, kind):
        async def cb(interaction):
            await interaction.response.edit_message(embed=build_lb_embed(self.guild, kind), view=self)
        return cb


@bot.command(name="leaderboard", aliases=["lb", "top", "classement"])
async def _leaderboard(ctx):
    view = LeaderboardView(ctx.author, ctx.guild)
    view.message = await ctx.send(embed=build_lb_embed(ctx.guild, "balance"), view=view, allowed_mentions=discord.AllowedMentions.none())


# ---- Boutique ----

@bot.command(name="shop", aliases=["boutique"])
async def _shop(ctx):
    p = get_prefix_cached()
    items = db_all("SELECT * FROM shop ORDER BY price ASC")
    em = info_embed("🛒 Boutique", f"Achète avec `{p}buy <id>`." if items else "La boutique est vide.")
    for it in items[:25]:
        role = f" — donne <@&{it['role_id']}>" if it["role_id"] else ""
        em.add_field(name=f"#{it['item_id']} · {it['name']} — {fmt(it['price'])} {SYMBOL}", value=(it["description"] or "—") + role, inline=False)
    apply_thumbnail(em, ctx.guild)
    await ctx.send(embed=em)


@bot.command(name="buy", aliases=["acheter"])
async def _buy(ctx, item_id: int = None):
    if item_id is None:
        return await ctx.send(embed=error_embed("❌ Usage", f"{get_prefix_cached()}buy <id>"))
    it = db_one("SELECT * FROM shop WHERE item_id = ?", (item_id,))
    if not it:
        return await ctx.send(embed=error_embed("❌ Article introuvable"))
    role = None
    if it["role_id"]:
        role = ctx.guild.get_role(int(it["role_id"]))
        if role is None:
            return await ctx.send(embed=error_embed("❌ Rôle introuvable", "Le rôle lié n'existe plus."))
        if role in ctx.author.roles:
            return await ctx.send(embed=error_embed("Déjà possédé", "Tu as déjà ce rôle."))
    if not debit(ctx.author.id, it["price"]):
        return await ctx.send(embed=error_embed("❌ Trop cher", f"Il coûte {money(it['price'])}, tu as {money(get_balance(ctx.author.id))}."))
    if role:
        try:
            await ctx.author.add_roles(role, reason=f"Achat boutique #{item_id}")
        except discord.HTTPException:
            credit(ctx.author.id, it["price"])
            return await ctx.send(embed=error_embed("❌ Impossible de donner le rôle", "Achat remboursé."))
    await ctx.send(embed=success_embed("✅ Achat effectué", f"**{it['name']}** pour {money(it['price'])}. Solde : {money(get_balance(ctx.author.id))}"))


# ========================= PROVABLY FAIR =========================

@bot.command(name="fair", aliases=["seeds", "provablyfair"])
async def _fair(ctx):
    s = get_seeds(ctx.author.id)
    p = get_prefix_cached()
    em = info_embed("🔐 Provably fair",
                    "Chaque partie utilise `HMAC_SHA256(server_seed, client_seed:nonce:curseur)`.\n"
                    "Le server seed est **caché** (seul son hash est montré) et révélé quand tu le changes : "
                    "tu peux alors vérifier toutes tes parties passées.")
    em.add_field(name="Server seed (hash)", value=f"`{sha256(s['server_seed'])}`", inline=False)
    em.add_field(name="Client seed", value=f"`{s['client_seed']}`", inline=True)
    em.add_field(name="Nonce", value=f"`{s['nonce']}`", inline=True)
    if s["prev_server"]:
        em.add_field(name="Ancien server seed (révélé)", value=f"`{s['prev_server']}`\nclient `{s['prev_client']}` · nonces 0 à {s['prev_nonce'] - 1}",
                     inline=False)
    em.set_footer(text=f"{p}seed [nouveau client seed] pour changer · {p}verify <server> <client> <nonce>")
    await ctx.send(embed=em)


@bot.command(name="seed", aliases=["rotate"])
async def _seed(ctx, *, client: str = None):
    if active_game_of(ctx.author.id):
        return await ctx.send(embed=error_embed("❌ Partie en cours", "Termine ta partie avant de changer de seed."))
    if client and not re.fullmatch(r"[\w\-]{1,64}", client):
        return await ctx.send(embed=error_embed("❌ Client seed invalide", "Lettres, chiffres, - et _ uniquement (64 max)."))
    old = rotate_seeds(ctx.author.id, client)
    new = get_seeds(ctx.author.id)
    em = success_embed("🔄 Seeds changés")
    em.add_field(name="Ancien server seed (révélé)", value=f"`{old['server_seed']}`", inline=False)
    em.add_field(name="Ancien client seed", value=f"`{old['client_seed']}` · {old['nonce']} parties", inline=False)
    em.add_field(name="Nouveau server seed (hash)", value=f"`{sha256(new['server_seed'])}`", inline=False)
    em.add_field(name="Nouveau client seed", value=f"`{new['client_seed']}`", inline=False)
    await ctx.send(embed=em)


@bot.command(name="verify", aliases=["verifier"])
async def _verify(ctx, server: str = None, client: str = None, nonce: int = None):
    if not server or client is None or nonce is None:
        return await ctx.send(embed=error_embed("❌ Usage", f"{get_prefix_cached()}verify <server_seed> <client_seed> <nonce>"))
    rng = FairRNG(server, client, nonce)
    f = rng.random()
    em = info_embed("🔍 Vérification", f"Hash du server seed : `{sha256(server)}`")
    em.add_field(name="1er float", value=f"`{f:.10f}`", inline=False)
    em.add_field(name="Dice", value=f"{min(10000, int(f * 10001)) / 100:.2f}", inline=True)
    em.add_field(name="Limbo / Crash", value=f"x{crash_point_from(f):.2f}", inline=True)
    em.add_field(name="Coinflip", value="Pile" if f < 0.5 else "Face", inline=True)
    em.add_field(name="Roulette", value=str(min(36, int(f * 37))), inline=True)
    await ctx.send(embed=em)


# ========================= HELP (filtré par rang) =========================

DEFAULT_EMOJIS = {"help_home_title": "🎰", "help_cat_originals": "⭐", "help_cat_casino": "🃏", "help_cat_economie": "💰",
                  "help_cat_profil": "📊", "help_cat_staff": "🛡️", "help_cat_system": "🛠️"}
EMOJI_LABELS = {"help_home_title": "Help · Titre accueil", "help_cat_originals": "Help · Originals", "help_cat_casino": "Help · Casino",
                "help_cat_economie": "Help · Économie", "help_cat_profil": "Help · Profil & Fair",
                "help_cat_staff": "Help · Staff", "help_cat_system": "Help · Système"}


def get_emojis():
    try:
        data = json.loads(get_config("emojis") or "{}")
    except (json.JSONDecodeError, TypeError):
        data = {}
    merged = dict(DEFAULT_EMOJIS)
    merged.update({k: v for k, v in data.items() if k in DEFAULT_EMOJIS})
    return merged


def get_emoji(key):
    return get_emojis().get(key, "")


def _emoji_for_select(raw):
    try:
        return discord.PartialEmoji.from_str(raw) if raw else None
    except Exception:
        return None


def help_categories():
    games = lambda cat: [(f"{k} [mise]", v[3], 0) for k, v in GAMES.items() if v[4] == cat]
    return {
        "originals": {"label": "Originals", "subtitle": "Les jeux maison, style Stake.", "sections": [("⭐", "Jeux", games("originals"))]},
        "casino":    {"label": "Casino", "subtitle": "Les classiques du casino.", "sections": [("🃏", "Jeux", games("casino"))]},
        "economie":  {"label": "Économie", "subtitle": f"Monnaie virtuelle {SYMBOL} uniquement — aucune valeur réelle.", "sections": [
            ("💰", "Gagner", [("daily", "Récompense quotidienne (série + bonus VIP)", 0), ("work", "Travailler (cooldown)", 0),
                             ("rakeback", "Récupérer ton rakeback VIP", 0)]),
            ("💸", "Échanger", [("give @user <montant>", "Envoyer des jetons", 0), ("shop", "Boutique", 0), ("buy <id>", "Acheter", 0)]),
        ]},
        "profil":    {"label": "Profil & Fair", "subtitle": "Stats, classements et vérification des tirages.", "sections": [
            ("📊", "Stats", [("balance [@user]", "Solde", 0), ("profil [@user]", "Profil complet", 0),
                            ("historique [@user]", "Dernières parties", 0), ("top", "Classements", 0), ("vip", "Niveaux VIP", 0)]),
            ("🔐", "Provably fair", [("fair", "Tes seeds actuels", 0), ("seed [client]", "Changer de seeds (révèle l'ancien)", 0),
                                    ("verify <server> <client> <nonce>", "Vérifier un tirage", 0)]),
        ]},
        "staff":     {"label": "Staff", "subtitle": "Gestion de l'économie et des salons.", "sections": [
            ("📺", "Salons (Owner+)", [("allow [#salon]", "Autoriser le casino dans un salon", 2), ("unallow [#salon]", "Retirer un salon", 2),
                                      ("allowed", "Salons autorisés (aucun = partout)", 2)]),
            ("💰", "Argent (Owner+)", [("addmoney @user <montant>", "Ajouter", 2), ("removemoney @user <montant>", "Retirer", 2),
                                      ("setmoney @user <montant>", "Définir", 2), ("resetbalance @user", "Remettre au départ", 2)]),
            ("🛒", "Boutique (Owner+)", [("additem <prix> [@rôle] <nom>", "Ajouter un article", 2), ("delitem <id>", "Supprimer", 2)]),
            ("👥", "Rangs", [("wl [@user] / unwl", "Whitelist (Owner+)", 2), ("owner [@user] / unowner", "Owners (Sys+)", 3),
                            ("sys [@user] / unsys", "Sys (Buyer)", 4)]),
        ]},
        "system":    {"label": "Système", "subtitle": "Configuration du bot.", "sections": [
            ("⚙️", "Config", [("config", "Mises min/max, daily, work… (panneau)", 3)]),
            ("🛠️", "Buyer only", [("prefix [nouveau]", "Changer le prefix", 4), ("setlog #salon", "Logs (gros gains, admin)", 4),
                                 ("setemoji", "Emojis du help", 4), ("wipeeconomy", "Remettre TOUTE l'économie à zéro", 4)]),
        ]},
    }


def _sections(cat, rank):
    out = []
    for emoji, title, items in cat["sections"]:
        vis = [(s, d) for s, d, mr in items if rank >= mr]
        if vis:
            out.append((emoji, title, vis))
    return out


def build_help_home(rank, guild):
    p = get_prefix_cached()
    em = discord.Embed(title=f"{get_emoji('help_home_title')}  Casino",
                       description=f"**Prefix :** {p} ・ **Ton rang :** {rank_name(rank)}\n"
                                   f"*Monnaie virtuelle uniquement — aucune valeur réelle.*\n\n"
                                   f"*Choisis une catégorie ci-dessous.*", color=embed_color())
    apply_thumbnail(em, guild)
    cats = help_categories()
    descs = {"originals": "Mines, Crash, Dice, Plinko…", "casino": "Blackjack, Roulette, Slots…", "economie": "Daily, work, give, boutique",
             "profil": "Stats, classements, provably fair", "staff": "Économie, salons, rangs", "system": "Config du bot"}
    for gname, keys in (("🎮 Jouer", ["originals", "casino", "economie", "profil"]), ("🛠️ Staff & Admin", ["staff", "system"])):
        lines = [f"{get_emoji(f'help_cat_{k}')} **{cats[k]['label']}** — {descs[k]}" for k in keys if _sections(cats[k], rank)]
        if lines:
            em.add_field(name=gname, value="\n".join(lines), inline=False)
    return em


def build_help_cat(key, rank, guild):
    p = get_prefix_cached()
    cat = help_categories()[key]
    em = discord.Embed(title=f"{get_emoji(f'help_cat_{key}')}  {cat['label']}", description=cat["subtitle"], color=embed_color())
    apply_thumbnail(em, guild)
    for emoji, title, items in _sections(cat, rank):
        em.add_field(name=f"{emoji} {title}", value="\n".join(f"{p}{s} — {d}" for s, d in items)[:1024], inline=False)
    if key in ("originals", "casino"):
        em.add_field(name="💡 Mises", value=f"`{p}mines 500` · `{p}dice 1k` · `{p}crash 50%` · `{p}bj all`", inline=False)
    return em


class HelpSelect(discord.ui.Select):
    def __init__(self, rank, guild):
        self.rank, self.guild = rank, guild
        cats = help_categories()
        opts = [discord.SelectOption(label="Accueil", value="home", emoji="🏠")]
        opts += [discord.SelectOption(label=c["label"], value=k, emoji=_emoji_for_select(get_emoji(f"help_cat_{k}")))
                 for k, c in cats.items() if _sections(c, rank)]
        super().__init__(placeholder="📂 Choisis une catégorie...", options=opts)

    async def callback(self, interaction: discord.Interaction):
        v = self.values[0]
        em = build_help_home(self.rank, self.guild) if v == "home" else build_help_cat(v, self.rank, self.guild)
        await interaction.response.edit_message(embed=em, view=self.view)


class HelpView(OwnerView):
    def __init__(self, author, rank, guild):
        super().__init__(author, timeout=180)
        self.add_item(HelpSelect(rank, guild))


@bot.command(name="help", aliases=["aide", "casino", "menu"])
async def _help(ctx):
    rank = get_rank_db(ctx.author.id)
    view = HelpView(ctx.author, rank, ctx.guild)
    view.message = await ctx.send(embed=build_help_home(rank, ctx.guild), view=view)


# ========================= STAFF =========================

@bot.command(name="allow")
async def _allow(ctx, channel: discord.TextChannel = None):
    if not await gate(ctx, 2):
        return
    channel = channel or ctx.channel
    db_exec("INSERT OR IGNORE INTO allowed_channels VALUES (?, ?)", (str(ctx.guild.id), str(channel.id)))
    await ctx.send(embed=success_embed("✅ Salon autorisé", f"Le casino est ouvert dans {channel.mention}."))


@bot.command(name="unallow", aliases=["disallow"])
async def _unallow(ctx, channel: discord.TextChannel = None):
    if not await gate(ctx, 2):
        return
    channel = channel or ctx.channel
    db_exec("DELETE FROM allowed_channels WHERE guild_id = ? AND channel_id = ?", (str(ctx.guild.id), str(channel.id)))
    left = get_allowed(ctx.guild.id)
    await ctx.send(embed=success_embed("🚫 Salon retiré", f"{channel.mention} n'est plus autorisé."
                                       + ("" if left else "\n*Plus aucun salon configuré : le casino est ouvert partout.*")))


@bot.command(name="allowed", aliases=["salons"])
async def _allowed(ctx):
    if not await gate(ctx, 2):
        return
    ids = get_allowed(ctx.guild.id)
    desc = ", ".join(f"<#{c}>" for c in ids) if ids else "Aucun salon configuré : **le casino est ouvert partout**."
    await ctx.send(embed=info_embed("📺 Salons du casino", desc))


async def _money_target(ctx, user_input, amount_raw):
    p = get_prefix_cached()
    if not user_input or amount_raw is None:
        await ctx.send(embed=error_embed("❌ Usage", f"{p}{ctx.command.name} @user <montant>"))
        return None, None, None
    display, uid = await resolve_user_or_id(ctx, user_input)
    if uid is None:
        await ctx.send(embed=error_embed("❌ Utilisateur introuvable", "Mention, ID ou nom requis."))
        return None, None, None
    amt = parse_amount(amount_raw, 10 ** 15) if amount_raw not in ("0",) else 0
    if amt is None:
        await ctx.send(embed=error_embed("❌ Montant invalide", "Nombre positif (ex : 500, 2k, 1m)."))
        return None, None, None
    return display, uid, amt


@bot.command(name="addmoney", aliases=["addcoins"])
async def _addmoney(ctx, user_input: str = None, amount: str = None):
    if not await gate(ctx, 2):
        return
    display, uid, amt = await _money_target(ctx, user_input, amount)
    if uid is None:
        return
    credit(uid, amt)
    await ctx.send(embed=success_embed("✅ Jetons ajoutés", f"+{money(amt)} à {format_user_display(display, uid)}. Solde : {money(get_balance(uid))}"))
    await admin_log(ctx.guild, "Jetons ajoutés", ctx.author, f"{format_user_display(display, uid)} : +{money(amt)}", 0x43b581)


@bot.command(name="removemoney", aliases=["removecoins"])
async def _removemoney(ctx, user_input: str = None, amount: str = None):
    if not await gate(ctx, 2):
        return
    display, uid, amt = await _money_target(ctx, user_input, amount)
    if uid is None:
        return
    bal = get_balance(uid)
    set_balance(uid, bal - amt)
    await ctx.send(embed=success_embed("✅ Jetons retirés", f"-{money(min(amt, bal))} à {format_user_display(display, uid)}. Solde : {money(get_balance(uid))}"))
    await admin_log(ctx.guild, "Jetons retirés", ctx.author, f"{format_user_display(display, uid)} : -{money(min(amt, bal))}")


@bot.command(name="setmoney", aliases=["setbalance"])
async def _setmoney(ctx, user_input: str = None, amount: str = None):
    if not await gate(ctx, 2):
        return
    display, uid, amt = await _money_target(ctx, user_input, amount)
    if uid is None:
        return
    set_balance(uid, amt)
    await ctx.send(embed=success_embed("✅ Solde défini", f"{format_user_display(display, uid)} : {money(amt)}"))
    await admin_log(ctx.guild, "Solde défini", ctx.author, f"{format_user_display(display, uid)} : {money(amt)}")


@bot.command(name="resetbalance", aliases=["resetbal"])
async def _resetbalance(ctx, *, user_input: str = None):
    if not await gate(ctx, 2):
        return
    display, uid = await resolve_user_or_id(ctx, user_input)
    if uid is None:
        return await ctx.send(embed=error_embed("❌ Utilisateur introuvable", "Mention, ID ou nom requis."))
    set_balance(uid, setting("start_balance"))
    await ctx.send(embed=success_embed("✅ Solde réinitialisé", f"{format_user_display(display, uid)} : {money(setting('start_balance'))}"))
    await admin_log(ctx.guild, "Solde réinitialisé", ctx.author, format_user_display(display, uid))


@bot.command(name="additem")
async def _additem(ctx, price: str = None, role: discord.Role = None, *, name: str = None):
    if not await gate(ctx, 2):
        return
    pr = parse_amount(price, 10 ** 15) if price else None
    if pr is None or not name:
        return await ctx.send(embed=error_embed("❌ Usage", f"{get_prefix_cached()}additem <prix> [@rôle] <nom>"))
    db_exec("INSERT INTO shop (name, price, role_id, description) VALUES (?, ?, ?, NULL)",
            (name.strip()[:80], pr, str(role.id) if role else None))
    await ctx.send(embed=success_embed("✅ Article ajouté", f"**{name.strip()}** — {money(pr)}" + (f" (donne {role.mention})" if role else "")))


@bot.command(name="delitem", aliases=["removeitem"])
async def _delitem(ctx, item_id: int = None):
    if not await gate(ctx, 2):
        return
    rc, _ = db_exec("DELETE FROM shop WHERE item_id = ?", (item_id,))
    await ctx.send(embed=success_embed("✅ Article supprimé") if rc else error_embed("❌ Article introuvable"))


class WipeConfirm(OwnerView):
    @discord.ui.button(label="TOUT EFFACER", emoji="⚠️", style=discord.ButtonStyle.danger)
    async def ok(self, interaction: discord.Interaction, b):
        self.stop()
        n = db_one("SELECT COUNT(*) AS n FROM users")["n"]
        db_exec("UPDATE users SET balance = ?, wagered = 0, won = 0, profit = 0, games = 0, biggest_win = 0, rakeback = 0, streak = 0",
                (setting("start_balance"),))
        db_exec("DELETE FROM bets")
        await interaction.response.edit_message(embed=success_embed("✅ Économie remise à zéro", f"{n} compte(s) réinitialisé(s)."), view=None)
        await admin_log(interaction.guild, "WIPE ÉCONOMIE", self.author, f"{n} comptes", 0xf04747)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, b):
        self.stop()
        await interaction.response.edit_message(embed=error_embed("✖️ Annulé"), view=None)


@bot.command(name="wipeeconomy", aliases=["resetall"])
async def _wipe(ctx):
    if not await gate(ctx, 4):
        return
    view = WipeConfirm(ctx.author, timeout=60)
    view.message = await ctx.send(embed=error_embed("⚠️ Confirmation", f"Remettre **tous** les soldes à {money(setting('start_balance'))} "
                                                                     f"et effacer toutes les stats ?"), view=view)


# ---- Config (panneau, même système que le Bot BL) ----

def build_config_embed(guild):
    em = discord.Embed(title="⚙️ Configuration du casino", description="Choisis un réglage puis envoie la nouvelle valeur dans le salon.",
                       color=embed_color())
    for k, (label, _mn, _mx) in SETTINGS_META.items():
        v = setting(k)
        em.add_field(name=label, value=("**illimitée**" if k == "max_bet" and v == 0 else f"**{fmt(v)}**"), inline=True)
    apply_thumbnail(em, guild)
    return em


class ConfigSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="Choisis un réglage...", options=[
            discord.SelectOption(label=label[:100], value=k, description=f"Actuel : {setting(k)}"[:100]) for k, (label, _a, _b) in SETTINGS_META.items()])

    async def callback(self, interaction: discord.Interaction):
        k = self.values[0]
        label, mn, mx = SETTINGS_META[k]
        panel = interaction.message
        await interaction.response.send_message(f"📨 Envoie la nouvelle valeur pour **{label}** ({fmt(mn)} à {fmt(mx)}). *(60 secondes)*")

        def check(m):
            return m.author.id == self.view.author.id and m.channel.id == interaction.channel.id

        try:
            reply = await bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            try:
                await interaction.edit_original_response(content="⏱️ Temps écoulé, aucune valeur reçue.")
            except discord.HTTPException:
                pass
            return
        val = parse_amount(reply.content, 10 ** 15) if reply.content.strip() != "0" else 0
        if val is not None and mn <= val <= mx:
            set_config(f"set_{k}", val)
        else:
            try:
                await interaction.followup.send("❌ Valeur invalide, aucune modification.", ephemeral=True)
            except discord.HTTPException:
                pass
        for coro in (interaction.delete_original_response(), reply.delete()):
            try:
                await coro
            except discord.HTTPException:
                pass
        try:
            view = ConfigView(self.view.author)
            await panel.edit(embed=build_config_embed(interaction.guild), view=view)
            view.message = panel
        except discord.HTTPException:
            pass


class ConfigView(OwnerView):
    def __init__(self, author):
        super().__init__(author, timeout=180)
        self.add_item(ConfigSelect())


@bot.command(name="config", aliases=["settings"])
async def _config(ctx):
    if not await gate(ctx, 3):
        return
    view = ConfigView(ctx.author)
    view.message = await ctx.send(embed=build_config_embed(ctx.guild), view=view)


# ---- Système ----

@bot.command(name="prefix")
async def _prefix(ctx, new_prefix: str = None):
    if not await gate(ctx, 4):
        return
    if not new_prefix:
        return await ctx.send(embed=info_embed("Prefix actuel", get_prefix_cached()))
    set_config("prefix", new_prefix)
    await ctx.send(embed=success_embed("✅ Prefix modifié", f"Nouveau prefix : {new_prefix}"))


@bot.command(name="setlog")
async def _setlog(ctx, channel: discord.TextChannel = None):
    if not await gate(ctx, 4):
        return
    if not channel:
        return await ctx.send(embed=error_embed("Argument manquant", "Mentionne un salon."))
    db_exec("INSERT OR REPLACE INTO log_channels VALUES (?, ?)", (str(ctx.guild.id), str(channel.id)))
    await ctx.send(embed=success_embed("✅ Salon de logs défini", f"Gros gains et actions staff dans {channel.mention}."))


class EmojiSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="Choisis un emoji à modifier...", options=[
            discord.SelectOption(label=EMOJI_LABELS[k], value=k, emoji=_emoji_for_select(get_emoji(k))) for k in DEFAULT_EMOJIS])

    async def callback(self, interaction: discord.Interaction):
        key, panel = self.values[0], interaction.message
        await interaction.response.send_message(f"📨 Envoie l'emoji pour **{EMOJI_LABELS[key]}**. *(60 secondes)*")

        def check(m):
            return m.author.id == self.view.author.id and m.channel.id == interaction.channel.id
        try:
            reply = await bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            return
        e = get_emojis()
        e[key] = reply.content.strip()
        set_config("emojis", json.dumps(e))
        for coro in (interaction.delete_original_response(), reply.delete()):
            try:
                await coro
            except discord.HTTPException:
                pass
        try:
            view = EmojiView(self.view.author)
            await panel.edit(embed=build_emoji_embed(), view=view)
            view.message = panel
        except discord.HTTPException:
            pass


def build_emoji_embed():
    e = get_emojis()
    return info_embed("🎨 Emojis personnalisables", "\n".join(f"{e[k]} **{EMOJI_LABELS[k]}**" for k in DEFAULT_EMOJIS))


class EmojiView(OwnerView):
    def __init__(self, author):
        super().__init__(author, timeout=180)
        self.add_item(EmojiSelect())

    @discord.ui.button(label="Tout réinitialiser", emoji="♻️", style=discord.ButtonStyle.danger, row=1)
    async def reset(self, interaction: discord.Interaction, b):
        set_config("emojis", json.dumps(DEFAULT_EMOJIS))
        view = EmojiView(self.author)
        await interaction.response.edit_message(embed=build_emoji_embed(), view=view)
        view.message = interaction.message


@bot.command(name="setemoji")
async def _setemoji(ctx):
    if not await gate(ctx, 4):
        return
    view = EmojiView(ctx.author)
    view.message = await ctx.send(embed=build_emoji_embed(), view=view)


# ---- Rangs ----

async def _rank_list(ctx, level, min_rank, title):
    if not await gate(ctx, min_rank):
        return
    ids = get_ranks_by_level(level)
    await ctx.send(embed=info_embed(f"📋 {title} ({len(ids)})", "\n".join(f"<@{u}>" for u in ids)[:4000] or "Aucun utilisateur."))


async def _rank_add(ctx, user_input, level, min_rank, label):
    if not await gate(ctx, min_rank):
        return
    display, uid = await resolve_user_or_id(ctx, user_input)
    if uid is None:
        return await ctx.send(embed=error_embed("❌ Utilisateur introuvable", "Mention, ID ou nom requis."))
    cur = get_rank_db(uid)
    if cur >= level:
        return await ctx.send(embed=error_embed("❌ Erreur", f"{format_user_display(display, uid)} a déjà un rang égal ou supérieur."))
    set_rank_db(uid, level)
    await ctx.send(embed=success_embed(f"✅ {label} ajouté", f"{format_user_display(display, uid)} est maintenant **{label}**."))
    await admin_log(ctx.guild, f"{label} ajouté", ctx.author, format_user_display(display, uid), 0x43b581)


async def _rank_remove(ctx, user_input, level, min_rank, label):
    if not await gate(ctx, min_rank):
        return
    display, uid = await resolve_user_or_id(ctx, user_input)
    if uid is None:
        return await ctx.send(embed=error_embed("❌ Utilisateur introuvable", "Mention, ID ou nom requis."))
    if get_rank_db(uid) != level:
        return await ctx.send(embed=error_embed(f"Pas {label}", f"{format_user_display(display, uid)} n'est pas **{label}**."))
    set_rank_db(uid, 0)
    await ctx.send(embed=success_embed(f"✅ {label} retiré", f"{format_user_display(display, uid)} n'est plus **{label}**."))
    await admin_log(ctx.guild, f"{label} retiré", ctx.author, format_user_display(display, uid))


@bot.command(name="sys")
async def _sys(ctx, *, user_input: str = None):
    if user_input is None:
        return await _rank_list(ctx, 3, 4, "Liste Sys")
    await _rank_add(ctx, user_input, 3, 4, "Sys")


@bot.command(name="unsys")
async def _unsys(ctx, *, user_input: str = None):
    await _rank_remove(ctx, user_input, 3, 4, "Sys")


@bot.command(name="owner")
async def _owner(ctx, *, user_input: str = None):
    if user_input is None:
        return await _rank_list(ctx, 2, 3, "Liste Owner")
    await _rank_add(ctx, user_input, 2, 3, "Owner")


@bot.command(name="unowner")
async def _unowner(ctx, *, user_input: str = None):
    await _rank_remove(ctx, user_input, 2, 3, "Owner")


@bot.command(name="wl")
async def _wl(ctx, *, user_input: str = None):
    if user_input is None:
        return await _rank_list(ctx, 1, 2, "Whitelist")
    await _rank_add(ctx, user_input, 1, 2, "Whitelist")


@bot.command(name="unwl")
async def _unwl(ctx, *, user_input: str = None):
    await _rank_remove(ctx, user_input, 1, 2, "Whitelist")


# ========================= EVENTS =========================

_ready_once = {"done": False}


@bot.event
async def on_ready():
    log.info(f"Bot connecté : {bot.user} ({bot.user.id}) · prefix {get_prefix_cached()} · {len(bot.guilds)} serveur(s)")
    if not _ready_once["done"]:
        _ready_once["done"] = True
        n = refund_all_active()
        if n:
            log.info(f"{n} partie(s) interrompue(s) par le redémarrage : mises remboursées.")
    try:
        await bot.change_presence(activity=discord.Game(name=f"{get_prefix_cached()}help · 🎰"))
    except discord.HTTPException:
        pass


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandInvokeError):
        error = error.original
    if isinstance(error, (commands.CommandNotFound, commands.CheckFailure)):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send(embed=error_embed("❌ Argument manquant", f"Il te manque : {error.param.name}. Voir {get_prefix_cached()}help."))
    if isinstance(error, (commands.BadArgument, commands.BadUnionArgument)):
        return await ctx.send(embed=error_embed("❌ Argument invalide", str(error)[:300]))
    log.error(f"Erreur '{ctx.command}' par {ctx.author} : {error}\n" + "".join(traceback.format_exception(type(error), error, error.__traceback__)))
    try:
        await ctx.send(embed=error_embed("❌ Erreur interne", "Une erreur inattendue est survenue. Les logs ont été générés."))
    except discord.HTTPException:
        pass


# ========================= RUN =========================
if __name__ == "__main__":
    ensure_fonts()
    try:
        log.info("Démarrage du bot Casino...")
        bot.run(BOT_TOKEN, log_handler=None)
    except KeyboardInterrupt:
        log.info("Arrêt demandé.")
    except Exception as e:
        log.error(f"Erreur fatale : {e}", exc_info=True)
        sys.exit(1)
