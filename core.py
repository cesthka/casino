"""
core.py — base de données, économie (en centimes d'euro virtuels), provably fair, tables de gains.
Aucune dépendance à Discord : testable seul.
"""
import os
import re
import json
import math
import time
import hmac
import hashlib
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from itertools import product

HOUSE_EDGE = 0.01
STALE_GAME_SECONDS = 1800

DEFAULT_SETTINGS = {
    "min_bet": 10,            # 0,10 €
    "max_bet": 0,             # 0 = illimitée
    "start_cash": 2500,       # 25,00 € dans le Wallet
    "start_bank": 0,
    "daily_amount": 500,      # 5,00 €
    "daily_streak": 100,      # +1,00 € par jour de série (max 7)
    "savings_rate_bp": 100,   # 1,00 % par jour (en points de base)
    "savings_cap": 100000,    # intérêts calculés sur 1 000 € max
    "bigwin_mult": 10,
}
SETTINGS_META = {
    "min_bet": "Mise minimum (centimes)", "max_bet": "Mise maximum (centimes, 0 = illimitée)",
    "start_cash": "Wallet de départ (centimes)", "start_bank": "Banque de départ (centimes)",
    "daily_amount": "Daily · base (centimes)", "daily_streak": "Daily · bonus par jour de série (centimes)",
    "savings_rate_bp": "Épargne · taux par jour (points de base, 100 = 1 %)", "savings_cap": "Épargne · plafond rémunéré (centimes)",
    "bigwin_mult": "Log gros gain à partir de x",
}

VIP_LEVELS = [  # misé total (centimes), nom, couleur, % de l'edge reversé
    (0, "Aucun", "#8B95A7", 0.00),
    (10_000, "Bronze", "#D39257", 0.05),
    (50_000, "Argent", "#C9D1DC", 0.08),
    (250_000, "Or", "#F5C451", 0.10),
    (1_000_000, "Platine", "#7FE0E0", 0.12),
    (5_000_000, "Diamant", "#9DB8FF", 0.15),
]

JOBS = [  # clé, nom, niveau requis, salaire (centimes), cooldown (s), formation (centimes), couleur, icône
    ("serveur", "Serveur", 1, 500, 600, 0, "#3E4A5E", "bag"),
    ("croupier", "Croupier", 3, 1200, 600, 0, "#D9573B", "dice"),
    ("securite", "Agent de sécurité", 6, 2000, 900, 0, "#2B5FA8", "shield"),
    ("trader", "Trader crypto", 10, 3500, 900, 50000, "#17A660", "chart"),
    ("manager", "Manager du casino", 15, 6000, 1200, 0, "#7C4DFF", "job"),
    ("directeur", "Directeur", 25, 10000, 1800, 500000, "#B8860B", "crown"),
]
JOB_BY_KEY = {j[0]: j for j in JOBS}


def now_ts():
    return int(time.time())


# ========================= DATABASE =========================
class DB:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.lock = threading.RLock()

    def x(self, sql, p=()):
        with self.lock:
            return self.conn.execute(sql, p)

    def one(self, sql, p=()):
        with self.lock:
            r = self.conn.execute(sql, p).fetchone()
            return dict(r) if r else None

    def all(self, sql, p=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, p).fetchall()]

    @contextmanager
    def tx(self):
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise


SCHEMA = """
CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS ranks (user_id TEXT PRIMARY KEY, rank INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS log_channels (guild_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS allowed_channels (guild_id TEXT NOT NULL, channel_id TEXT NOT NULL, PRIMARY KEY (guild_id, channel_id));
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY, cash INTEGER NOT NULL DEFAULT 0, bank INTEGER NOT NULL DEFAULT 0,
    savings INTEGER NOT NULL DEFAULT 0, savings_ts INTEGER NOT NULL DEFAULT 0,
    last_daily INTEGER NOT NULL DEFAULT 0, streak INTEGER NOT NULL DEFAULT 0, last_work INTEGER NOT NULL DEFAULT 0,
    job TEXT NOT NULL DEFAULT 'serveur', xp INTEGER NOT NULL DEFAULT 0, trained TEXT NOT NULL DEFAULT '',
    wagered INTEGER NOT NULL DEFAULT 0, won INTEGER NOT NULL DEFAULT 0, profit INTEGER NOT NULL DEFAULT 0,
    games INTEGER NOT NULL DEFAULT 0, biggest_win INTEGER NOT NULL DEFAULT 0, best_mult REAL NOT NULL DEFAULT 0,
    rakeback REAL NOT NULL DEFAULT 0, frame TEXT, theme TEXT, created INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS active_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, game TEXT NOT NULL,
    bet INTEGER NOT NULL, ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, game TEXT NOT NULL,
    bet INTEGER NOT NULL, payout INTEGER NOT NULL, mult REAL NOT NULL, nonce INTEGER, ts INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_bets_user ON bets (user_id, id DESC);
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, account TEXT NOT NULL,
    label TEXT NOT NULL, amount INTEGER NOT NULL, ts INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_ledger_user ON ledger (user_id, account, id DESC);
CREATE TABLE IF NOT EXISTS holdings (
    user_id TEXT NOT NULL, sym TEXT NOT NULL, qty REAL NOT NULL DEFAULT 0, cost INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, sym));
CREATE TABLE IF NOT EXISTS seeds (
    user_id TEXT PRIMARY KEY, server_seed TEXT NOT NULL, client_seed TEXT NOT NULL, nonce INTEGER NOT NULL DEFAULT 0,
    prev_server TEXT, prev_client TEXT, prev_nonce INTEGER);
CREATE TABLE IF NOT EXISTS shop (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, price INTEGER NOT NULL, role_id TEXT, description TEXT);
"""


class Store:
    """Accès aux données + règles de l'économie."""

    def __init__(self, path, buyer_ids=()):
        self.db = DB(path)
        with self.db.lock:
            self.db.conn.executescript(SCHEMA)
        self.db.x("INSERT OR IGNORE INTO config VALUES ('prefix', '$')")
        if buyer_ids:
            self.db.x("INSERT OR REPLACE INTO config VALUES ('buyer_ids', ?)", (json.dumps([str(i) for i in buyer_ids]),))
        self._cfg = {}
        self.ranks = {}
        self.buyers = set()
        self.load_ranks()

    # ---------- config ----------
    def cfg(self, key, default=None):
        if key not in self._cfg:
            r = self.db.one("SELECT value FROM config WHERE key = ?", (key,))
            self._cfg[key] = r["value"] if r else None
        v = self._cfg[key]
        return default if v is None else v

    def set_cfg(self, key, value):
        self.db.x("INSERT OR REPLACE INTO config VALUES (?, ?)", (key, str(value)))
        self._cfg[key] = str(value)

    def setting(self, key):
        try:
            return int(self.cfg(f"set_{key}", DEFAULT_SETTINGS[key]))
        except (TypeError, ValueError):
            return DEFAULT_SETTINGS[key]

    # ---------- rangs ----------
    def load_ranks(self):
        self.ranks = {r["user_id"]: r["rank"] for r in self.db.all("SELECT * FROM ranks")}
        try:
            self.buyers = {str(i) for i in json.loads(self.cfg("buyer_ids", "[]"))}
        except (TypeError, ValueError):
            self.buyers = set()

    def rank(self, uid):
        uid = str(uid)
        return 4 if uid in self.buyers else self.ranks.get(uid, 0)

    def set_rank(self, uid, level):
        uid = str(uid)
        if level == 0:
            self.db.x("DELETE FROM ranks WHERE user_id = ?", (uid,))
            self.ranks.pop(uid, None)
        else:
            self.db.x("INSERT OR REPLACE INTO ranks VALUES (?, ?)", (uid, level))
            self.ranks[uid] = level

    # ---------- utilisateurs ----------
    def ensure(self, uid):
        self.db.x("INSERT OR IGNORE INTO users (user_id, cash, bank, created, savings_ts) VALUES (?, ?, ?, ?, ?)",
                  (str(uid), self.setting("start_cash"), self.setting("start_bank"), now_ts(), now_ts()))

    def user(self, uid):
        self.ensure(uid)
        return self.db.one("SELECT * FROM users WHERE user_id = ?", (str(uid),))

    def log(self, uid, account, label, amount):
        self.db.x("INSERT INTO ledger (user_id, account, label, amount, ts) VALUES (?, ?, ?, ?, ?)",
                  (str(uid), account, label[:60], int(amount), now_ts()))

    def ledger(self, uid, account, n=8):
        return self.db.all("SELECT * FROM ledger WHERE user_id = ? AND account = ? ORDER BY id DESC LIMIT ?", (str(uid), account, n))

    def add_cash(self, uid, amount, label=None):
        self.ensure(uid)
        self.db.x("UPDATE users SET cash = cash + ? WHERE user_id = ?", (int(amount), str(uid)))
        if label:
            self.log(uid, "wallet", label, amount)

    def take_cash(self, uid, amount, label=None):
        """Retire du Wallet seulement si le solde suffit (atomique)."""
        self.ensure(uid)
        ok = self.db.x("UPDATE users SET cash = cash - ? WHERE user_id = ? AND cash >= ?",
                       (int(amount), str(uid), int(amount))).rowcount == 1
        if ok and label:
            self.log(uid, "wallet", label, -amount)
        return ok

    def set_cash(self, uid, value):
        self.ensure(uid)
        self.db.x("UPDATE users SET cash = ? WHERE user_id = ?", (max(0, int(value)), str(uid)))

    def move(self, uid, src, dst, amount, label_src, label_dst):
        """Transfert interne atomique entre cash / bank / savings."""
        self.ensure(uid)
        amount = int(amount)
        if amount <= 0:
            return False
        with self.db.tx() as c:
            if src == "savings" or dst == "savings":
                self._accrue(c, uid)
            r = c.execute(f"UPDATE users SET {src} = {src} - ?, {dst} = {dst} + ? WHERE user_id = ? AND {src} >= ?",
                          (amount, amount, str(uid), amount))
            if r.rowcount != 1:
                return False
            t = now_ts()
            acc = {"cash": "wallet", "bank": "bank", "savings": "bank"}
            c.execute("INSERT INTO ledger (user_id, account, label, amount, ts) VALUES (?, ?, ?, ?, ?)", (str(uid), acc[src], label_src, -amount, t))
            c.execute("INSERT INTO ledger (user_id, account, label, amount, ts) VALUES (?, ?, ?, ?, ?)", (str(uid), acc[dst], label_dst, amount, t))
        return True

    def transfer(self, uid, to, amount, src="bank"):
        """Virement entre joueurs (depuis la banque ou le wallet)."""
        self.ensure(uid)
        self.ensure(to)
        amount = int(amount)
        with self.db.tx() as c:
            r = c.execute(f"UPDATE users SET {src} = {src} - ? WHERE user_id = ? AND {src} >= ?", (amount, str(uid), amount))
            if r.rowcount != 1:
                return False
            c.execute(f"UPDATE users SET {src} = {src} + ? WHERE user_id = ?", (amount, str(to)))
            acc = "bank" if src == "bank" else "wallet"
            t = now_ts()
            c.execute("INSERT INTO ledger (user_id, account, label, amount, ts) VALUES (?, ?, ?, ?, ?)", (str(uid), acc, f"@to:{to}", -amount, t))
            c.execute("INSERT INTO ledger (user_id, account, label, amount, ts) VALUES (?, ?, ?, ?, ?)", (str(to), acc, f"@from:{uid}", amount, t))
        return True

    # ---------- épargne ----------
    def _accrue(self, c, uid):
        r = c.execute("SELECT savings, savings_ts FROM users WHERE user_id = ?", (str(uid),)).fetchone()
        if not r:
            return 0
        t = now_ts()
        days = max(0, t - r["savings_ts"]) / 86400
        base = min(r["savings"], self.setting("savings_cap"))
        gain = int(base * self.setting("savings_rate_bp") / 10000 * days)
        if gain >= 1:
            c.execute("UPDATE users SET savings = savings + ?, savings_ts = ? WHERE user_id = ?", (gain, t, str(uid)))
            c.execute("INSERT INTO ledger (user_id, account, label, amount, ts) VALUES (?, 'bank', 'Intérêts livret', ?, ?)", (str(uid), gain, t))
        elif r["savings"] == 0:
            c.execute("UPDATE users SET savings_ts = ? WHERE user_id = ?", (t, str(uid)))
        return gain

    def accrue(self, uid):
        self.ensure(uid)
        with self.db.tx() as c:
            return self._accrue(c, uid)

    # ---------- daily / travail ----------
    def claim_daily(self, uid):
        u = self.user(uid)
        t = now_ts()
        elapsed = t - u["last_daily"]
        if elapsed < 86400:
            return None, u["last_daily"] + 86400
        streak = u["streak"] + 1 if elapsed < 2 * 86400 else 1
        vip_i = VIP_LEVELS.index(vip_for(u["wagered"]))
        amount = int((self.setting("daily_amount") + min(streak, 7) * self.setting("daily_streak")) * (1 + vip_i * 0.10))
        r = self.db.x("UPDATE users SET cash = cash + ?, last_daily = ?, streak = ? WHERE user_id = ? AND last_daily = ?",
                      (amount, t, streak, str(uid), u["last_daily"]))
        if r.rowcount != 1:
            return None, t
        self.log(uid, "wallet", f"Daily (série {streak})", amount)
        return amount, streak

    def work(self, uid):
        u = self.user(uid)
        job = JOB_BY_KEY.get(u["job"], JOBS[0])
        t = now_ts()
        if t - u["last_work"] < job[4]:
            return None, u["last_work"] + job[4]
        lvl = level_of(u["xp"])[0]
        pay = int(job[3] * (1 + 0.04 * max(0, lvl - job[2])))
        xp = 20 + secrets.randbelow(11)
        r = self.db.x("UPDATE users SET bank = bank + ?, xp = xp + ?, last_work = ? WHERE user_id = ? AND last_work = ?",
                      (pay, xp, t, str(uid), u["last_work"]))
        if r.rowcount != 1:
            return None, t
        self.log(uid, "bank", f"Salaire · {job[1]}", pay)
        return pay, xp

    def set_job(self, uid, key):
        u = self.user(uid)
        job = JOB_BY_KEY.get(key)
        if not job:
            return "Métier inconnu."
        if level_of(u["xp"])[0] < job[2]:
            return f"Niveau {job[2]} requis."
        trained = set(filter(None, u["trained"].split(",")))
        if job[5] and key not in trained:
            r = self.db.x("UPDATE users SET bank = bank - ? WHERE user_id = ? AND bank >= ?", (job[5], str(uid), job[5]))
            if r.rowcount != 1:
                return f"Formation à {job[5] // 100} € : paiement depuis la banque impossible."
            self.log(uid, "bank", f"Formation · {job[1]}", -job[5])
            trained.add(key)
        self.db.x("UPDATE users SET job = ?, trained = ? WHERE user_id = ?", (key, ",".join(sorted(trained)), str(uid)))
        return None

    # ---------- crypto ----------
    def holdings(self, uid):
        return {r["sym"]: r for r in self.db.all("SELECT * FROM holdings WHERE user_id = ? AND qty > 0", (str(uid),))}

    def buy_crypto(self, uid, sym, eur_cents, price_eur, fee=0.001):
        if price_eur <= 0 or eur_cents <= 0:
            return None
        qty = (eur_cents / 100) * (1 - fee) / price_eur
        with self.db.tx() as c:
            r = c.execute("UPDATE users SET cash = cash - ? WHERE user_id = ? AND cash >= ?", (eur_cents, str(uid), eur_cents))
            if r.rowcount != 1:
                return None
            c.execute("INSERT INTO holdings (user_id, sym, qty, cost) VALUES (?, ?, ?, ?) "
                      "ON CONFLICT(user_id, sym) DO UPDATE SET qty = qty + excluded.qty, cost = cost + excluded.cost",
                      (str(uid), sym, qty, eur_cents))
            c.execute("INSERT INTO ledger (user_id, account, label, amount, ts) VALUES (?, 'wallet', ?, ?, ?)",
                      (str(uid), f"Achat {sym}", -eur_cents, now_ts()))
        return qty

    def sell_crypto(self, uid, sym, eur_cents, price_eur, fee=0.001, all_=False):
        """Vend pour `eur_cents` (brut) ou tout. Retourne le montant crédité."""
        if price_eur <= 0:
            return None
        with self.db.tx() as c:
            h = c.execute("SELECT qty, cost FROM holdings WHERE user_id = ? AND sym = ?", (str(uid), sym)).fetchone()
            if not h or h["qty"] <= 0:
                return None
            qty = h["qty"] if all_ else min(h["qty"], (eur_cents / 100) / price_eur)
            if qty <= 0:
                return None
            gross = qty * price_eur
            credit_ = int(gross * (1 - fee) * 100)
            frac = qty / h["qty"]
            left = h["qty"] - qty
            if left < 1e-12 or all_:
                c.execute("DELETE FROM holdings WHERE user_id = ? AND sym = ?", (str(uid), sym))
            else:
                c.execute("UPDATE holdings SET qty = ?, cost = cost - ? WHERE user_id = ? AND sym = ?",
                          (left, int(h["cost"] * frac), str(uid), sym))
            c.execute("UPDATE users SET cash = cash + ? WHERE user_id = ?", (credit_, str(uid)))
            c.execute("INSERT INTO ledger (user_id, account, label, amount, ts) VALUES (?, 'wallet', ?, ?, ?)",
                      (str(uid), f"Vente {sym}", credit_, now_ts()))
        return credit_

    # ---------- parties ----------
    def active_game(self, uid):
        return self.db.one("SELECT * FROM active_games WHERE user_id = ?", (str(uid),))

    def start_game(self, uid, key, bet):
        bet = int(bet)
        cur = self.active_game(uid)
        if cur:
            if now_ts() - cur["ts"] > STALE_GAME_SECONDS:
                self.refund_game(cur["id"])
            else:
                return None, "Tu as déjà une partie en cours."
        mn, mx = self.setting("min_bet"), self.setting("max_bet")
        if bet < mn:
            return None, f"Mise minimum : {mn / 100:.2f} €".replace(".", ",")
        if mx and bet > mx:
            return None, f"Mise maximum : {mx / 100:.2f} €".replace(".", ",")
        if not self.take_cash(uid, bet):
            return None, "Solde du Wallet insuffisant."
        gid = self.db.x("INSERT INTO active_games (user_id, game, bet, ts) VALUES (?, ?, ?, ?)",
                        (str(uid), key, bet, now_ts())).lastrowid
        return gid, None

    def raise_bet(self, gid, uid, extra):
        if not self.db.one("SELECT 1 FROM active_games WHERE id = ?", (gid,)):
            return False
        if not self.take_cash(uid, extra):
            return False
        self.db.x("UPDATE active_games SET bet = bet + ? WHERE id = ?", (int(extra), gid))
        return True

    def settle_game(self, gid, payout, mult, nonce):
        """Clôture et paie. Idempotent : un second appel ne verse rien."""
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM active_games WHERE id = ?", (gid,)).fetchone()
            if row is None:
                return None
            c.execute("DELETE FROM active_games WHERE id = ?", (gid,))
            uid, bet, payout = row["user_id"], row["bet"], int(payout)
            u = c.execute("SELECT wagered FROM users WHERE user_id = ?", (uid,)).fetchone()
            rate = vip_for(u["wagered"] if u else 0)[3]
            c.execute("UPDATE users SET cash = cash + ?, wagered = wagered + ?, won = won + ?, profit = profit + ?, games = games + 1, "
                      "biggest_win = MAX(biggest_win, ?), best_mult = MAX(best_mult, ?), rakeback = rakeback + ? WHERE user_id = ?",
                      (payout, bet, payout, payout - bet, payout - bet, float(mult) if payout > bet else 0, bet * HOUSE_EDGE * rate, uid))
            c.execute("INSERT INTO bets (user_id, game, bet, payout, mult, nonce, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (uid, row["game"], bet, payout, float(mult), nonce, now_ts()))
        return {"bet": bet, "payout": payout, "user_id": uid, "game": row["game"]}

    def refund_game(self, gid):
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM active_games WHERE id = ?", (gid,)).fetchone()
            if row is None:
                return False
            c.execute("DELETE FROM active_games WHERE id = ?", (gid,))
            c.execute("UPDATE users SET cash = cash + ? WHERE user_id = ?", (row["bet"], row["user_id"]))
        return True

    def refund_all_active(self):
        return sum(1 for r in self.db.all("SELECT id FROM active_games") if self.refund_game(r["id"]))

    def recent_bets(self, uid, n=8):
        return self.db.all("SELECT * FROM bets WHERE user_id = ? ORDER BY id DESC LIMIT ?", (str(uid), n))

    def claim_rakeback(self, uid):
        u = self.user(uid)
        amount = int(u["rakeback"])
        if amount < 1:
            return 0
        self.db.x("UPDATE users SET cash = cash + ?, rakeback = rakeback - ? WHERE user_id = ?", (amount, amount, str(uid)))
        self.log(uid, "wallet", "Rakeback VIP", amount)
        return amount

    # ---------- seeds ----------
    def seeds(self, uid):
        r = self.db.one("SELECT * FROM seeds WHERE user_id = ?", (str(uid),))
        if r is None:
            self.db.x("INSERT OR IGNORE INTO seeds (user_id, server_seed, client_seed, nonce) VALUES (?, ?, ?, 0)",
                      (str(uid), secrets.token_hex(32), secrets.token_hex(8)))
            r = self.db.one("SELECT * FROM seeds WHERE user_id = ?", (str(uid),))
        return r

    def next_rng(self, uid):
        with self.db.tx() as c:
            s = c.execute("SELECT * FROM seeds WHERE user_id = ?", (str(uid),)).fetchone()
            if s is None:
                c.execute("INSERT INTO seeds (user_id, server_seed, client_seed, nonce) VALUES (?, ?, ?, 0)",
                          (str(uid), secrets.token_hex(32), secrets.token_hex(8)))
                s = c.execute("SELECT * FROM seeds WHERE user_id = ?", (str(uid),)).fetchone()
            c.execute("UPDATE seeds SET nonce = nonce + 1 WHERE user_id = ?", (str(uid),))
        return FairRNG(s["server_seed"], s["client_seed"], s["nonce"])

    def rotate_seeds(self, uid, client=None):
        s = self.seeds(uid)
        self.db.x("UPDATE seeds SET prev_server = ?, prev_client = ?, prev_nonce = ?, server_seed = ?, client_seed = ?, nonce = 0 WHERE user_id = ?",
                  (s["server_seed"], s["client_seed"], s["nonce"], secrets.token_hex(32), (client or secrets.token_hex(8))[:64], str(uid)))
        return s


# ========================= HELPERS =========================
def vip_for(wagered):
    lvl = VIP_LEVELS[0]
    for e in VIP_LEVELS:
        if wagered >= e[0]:
            lvl = e
    return lvl


def next_vip(wagered):
    for e in VIP_LEVELS:
        if wagered < e[0]:
            return e
    return None


def level_of(xp):
    """Retourne (niveau, xp dans le niveau, xp nécessaire pour le suivant)."""
    lvl, need = 1, 100
    while xp >= need:
        xp -= need
        lvl += 1
        need = 100 + 50 * (lvl - 1)
    return lvl, xp, need


def parse_eur(arg, balance=None):
    """'12' · '12,5' · '1k' · 'all' · 'moitié' · '25%' → centimes."""
    if arg is None:
        return None
    a = str(arg).strip().lower().replace(" ", "").replace("€", "").replace("eur", "")
    if balance is not None:
        if a in ("all", "max", "tout", "allin"):
            return balance if balance > 0 else None
        if a in ("half", "moitie", "moitié", "h"):
            return balance // 2 if balance >= 2 else None
        if a.endswith("%"):
            try:
                pct = float(a[:-1].replace(",", "."))
            except ValueError:
                return None
            return max(1, int(balance * pct / 100)) if balance > 0 and 0 < pct <= 100 else None
    mult = 1
    if a and a[-1] in "km":
        mult = {"k": 1_000, "m": 1_000_000}[a[-1]]
        a = a[:-1]
    a = a.replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", a or "x") and not re.fullmatch(r"\d*\.\d+", a or "x"):
        return None
    try:
        v = round(float(a) * mult * 100)
    except ValueError:
        return None
    return v if v > 0 else None


def payout_of(bet, mult):
    return int(math.floor(bet * mult + 1e-9))


def sha256(s):
    return hashlib.sha256(s.encode()).hexdigest()


# ========================= PROVABLY FAIR =========================
class FairRNG:
    """HMAC_SHA256(server_seed, f"{client}:{nonce}:{cursor}"), 4 octets par float (méthode Stake)."""

    def __init__(self, server_seed, client_seed, nonce):
        self.server_seed, self.client_seed, self.nonce = server_seed, client_seed, nonce
        self.cursor = 0
        self._buf = []

    def random(self):
        if not self._buf:
            d = hmac.new(self.server_seed.encode(), f"{self.client_seed}:{self.nonce}:{self.cursor}".encode(), hashlib.sha256).digest()
            self.cursor += 1
            for i in range(0, 32, 4):
                b = d[i:i + 4]
                self._buf.append(b[0] / 256 + b[1] / 256 ** 2 + b[2] / 256 ** 3 + b[3] / 256 ** 4)
        return self._buf.pop(0)

    def randrange(self, n):
        return min(n - 1, int(self.random() * n))

    def shuffle(self, items):
        items = list(items)
        for i in range(len(items) - 1, 0, -1):
            j = self.randrange(i + 1)
            items[i], items[j] = items[j], items[i]
        return items

    def weighted(self, items, weights):
        r = self.random() * sum(weights)
        acc = 0
        for it, w in zip(items, weights):
            acc += w
            if r < acc:
                return it
        return items[-1]


def crash_point_from(f):
    return max(1.0, math.floor((1 - HOUSE_EDGE) / (1 - f) * 100) / 100)


# ========================= TABLES DE GAINS (RTP calés) =========================
def _scale(table, probs, target):
    ev = sum(m * p for m, p in zip(table, probs))
    k = target / ev if ev else 1
    return [round(m * k, 2) for m in table]


def binom_probs(n):
    return [math.comb(n, k) / 2 ** n for k in range(n + 1)]


_PLINKO_BASE = {
    8: {"low": [5.6, 2.1, 1.1, 1, 0.5, 1, 1.1, 2.1, 5.6], "medium": [13, 3, 1.3, 0.7, 0.4, 0.7, 1.3, 3, 13],
        "high": [29, 4, 1.5, 0.3, 0.2, 0.3, 1.5, 4, 29]},
    12: {"low": [10, 3, 1.6, 1.4, 1.1, 1, 0.5, 1, 1.1, 1.4, 1.6, 3, 10],
         "medium": [33, 11, 4, 2, 1.1, 0.6, 0.3, 0.6, 1.1, 2, 4, 11, 33],
         "high": [170, 24, 8.1, 2, 0.7, 0.2, 0.2, 0.2, 0.7, 2, 8.1, 24, 170]},
    16: {"low": [16, 9, 2, 1.4, 1.4, 1.2, 1.1, 1, 0.5, 1, 1.1, 1.2, 1.4, 1.4, 2, 9, 16],
         "medium": [110, 41, 10, 5, 3, 1.5, 1, 0.5, 0.3, 0.5, 1, 1.5, 3, 5, 10, 41, 110],
         "high": [1000, 130, 26, 9, 4, 2, 0.2, 0.2, 0.2, 0.2, 0.2, 2, 4, 9, 26, 130, 1000]},
}
PLINKO = {rows: {risk: _scale(t, binom_probs(rows), 0.99) for risk, t in risks.items()} for rows, risks in _PLINKO_BASE.items()}

WHEEL = {
    "low": [1.5, 1.2, 1.2, 0, 1.2, 1.2, 1.2, 0, 1.2, 1.2, 1.5, 1.2, 1.2, 0, 1.2, 1.2, 1.2, 0, 1.2, 1.2],
    "medium": [0, 1.5, 0, 2, 0, 1.5, 0, 3, 0, 1.5, 0, 2, 0, 1.5, 0, 3, 0, 2, 0, 1.8],
    "high": [0] * 19 + [19.8],
}

_KENO_BASE = {
    1: [0, 3.96], 2: [0, 1.9, 4.5], 3: [0, 1, 3.1, 10.4], 4: [0, 0.8, 1.8, 5, 22.5],
    5: [0, 0.25, 1.4, 4.1, 16.5, 36], 6: [0, 0, 1, 3.68, 7, 16.5, 40], 7: [0, 0, 0.47, 3, 4.5, 14, 31, 60],
    8: [0, 0, 0, 2.2, 4, 13, 22, 55, 70], 9: [0, 0, 0, 1.55, 3, 8, 15, 44, 60, 85],
    10: [0, 0, 0, 1.4, 2.25, 4.5, 8, 17, 50, 80, 100],
}


def keno_probs(spots):
    return [math.comb(spots, h) * math.comb(40 - spots, 10 - h) / math.comb(40, 10) for h in range(spots + 1)]


KENO = {s: _scale(t, keno_probs(s), 0.97) for s, t in _KENO_BASE.items()}

DIAMOND_PATTERNS = [((5,), "5 identiques", 50), ((4, 1), "Carré", 5), ((3, 2), "Full", 4), ((3, 1, 1), "Brelan", 3),
                    ((2, 2, 1), "Deux paires", 2), ((2, 1, 1, 1), "Paire", 0.1), ((1, 1, 1, 1, 1), "Rien", 0)]


def _diamond_probs():
    counts = {p[0]: 0 for p in DIAMOND_PATTERNS}
    for draw in product(range(7), repeat=5):
        counts[tuple(sorted((draw.count(g) for g in set(draw)), reverse=True))] += 1
    return [counts[p[0]] / 7 ** 5 for p in DIAMOND_PATTERNS]


_DM = _scale([p[2] for p in DIAMOND_PATTERNS], _diamond_probs(), 0.98)
DIAMONDS = {p[0]: (p[1], m) for p, m in zip(DIAMOND_PATTERNS, _DM)}
DIAMOND_TABLE = [(p[1], m) for p, m in zip(DIAMOND_PATTERNS, _DM)]

CASE_W = [35, 22, 14, 10, 7, 5, 3, 2, 1, 0.4]
CASE_MULTS = _scale([0, 0.4, 0.8, 1.2, 1.6, 2.5, 4, 8, 20, 75], [w / sum(CASE_W) for w in CASE_W], 0.96)

SLOT_SYMBOLS = ["cherry", "lemon", "grape", "bell", "star", "diamond", "seven"]
SLOT_WEIGHTS = [28, 24, 18, 14, 9, 5, 2]
_SLOT_TRIPLE_BASE = [8, 14, 20, 30, 50, 100, 250]


def slot_mult(reels, triple, two_cherry):
    if reels[0] == reels[1] == reels[2]:
        return triple[reels[0]]
    if reels.count(0) == 2:
        return two_cherry
    return 0


def _slots_ev(triple, two_cherry):
    tw = sum(SLOT_WEIGHTS)
    return sum(SLOT_WEIGHTS[a] * SLOT_WEIGHTS[b] * SLOT_WEIGHTS[c] / tw ** 3 * slot_mult([a, b, c], triple, two_cherry)
               for a, b, c in product(range(7), repeat=3))


_k = 0.96 / _slots_ev(_SLOT_TRIPLE_BASE, 2)
SLOT_TRIPLE = [round(m * _k, 2) for m in _SLOT_TRIPLE_BASE]
SLOT_TWO_CHERRY = round(2 * _k, 2)
SLOT_PAYS = [(s, m) for s, m in zip(SLOT_SYMBOLS, SLOT_TRIPLE)] + [("2cherry", SLOT_TWO_CHERRY)]
