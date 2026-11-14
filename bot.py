"""
================================================================================
  CASINO PHONE — bot Discord "téléphone" (monnaie VIRTUELLE, aucune valeur réelle)
================================================================================
Tout passe par des images de téléphone + boutons / menus déroulants.
Seule exception : la commande `guide` (embeds d'explication des jeux) et les commandes staff.

Fichiers :
  bot.py            ce fichier (Discord : téléphone, commandes)
  core.py           base de données, économie, provably fair, tables de gains
  games.py          logique des 19 jeux
  gfx.py            moteur de rendu skia
  screens_apps.py   écrans du téléphone (accueil, wallet, banque, crypto…)
  screens_games.py  écrans des jeux
  crypto_feed.py    cours crypto en direct (Binance, secours CoinGecko)
  guide.py          textes du guide
  fonts/            polices Poppins

Variables d'environnement : TOKEN (ou DISCORD_TOKEN), DATA_DIR
================================================================================
"""
import os
import re
import sys
import time
import asyncio
import logging
import traceback
from io import BytesIO
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands

import core as C
from core import Store, parse_eur, payout_of, vip_for, next_vip, level_of, JOBS, JOB_BY_KEY, sha256
from games import GAMES, ENGINES, ALIASES, Crash, Dice, MINES_TILES, LADDER_DIFF, DRAGON_DIFF, ROULETTE_BETS
from gfx import eur, xfmt, now_paris
import screens_apps as SA
import screens_games as SG
from crypto_feed import CryptoFeed, COINS, META
from guide import GUIDE

# ========================= CONFIG =========================
TOKEN = os.environ.get("TOKEN") or os.environ.get("DISCORD_TOKEN")
DATA_DIR = os.environ.get("DATA_DIR")
if not TOKEN or not DATA_DIR:
    print("[ERREUR] Définis les variables d'environnement TOKEN et DATA_DIR (ex : DATA_DIR=/data).")
    sys.exit(1)
os.makedirs(DATA_DIR, exist_ok=True)

DEFAULT_BUYER_IDS = [142365250803466240, 1546586066407133308]
PHONE_TIMEOUT = 300
CRASH_TICK = 1.25
TOAST_SECONDS = 3

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%d/%m/%Y %H:%M:%S")
log = logging.getLogger("casino")

store = Store(os.path.join(DATA_DIR, "phone_casino.db"), DEFAULT_BUYER_IDS)
feed = CryptoFeed()
PHONES = {}           # user_id -> Phone ouvert
CRASH_RECENT = []     # derniers crashs (tous joueurs)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix=lambda b, m: store.cfg("prefix", "$"), intents=intents, help_command=None, case_insensitive=True)

GREY, BLUE, GREEN, RED = (discord.ButtonStyle.secondary, discord.ButtonStyle.primary,
                          discord.ButtonStyle.success, discord.ButtonStyle.danger)


# ========================= HELPERS =========================
def brand_of(user):
    """Nom de marque du téléphone : basé sur le nom d'utilisateur (pas le pseudo)."""
    name = re.sub(r"[^A-Za-z0-9_.]", "", user.name or "")
    name = name.strip("._") or "Joueur"
    return name[:1].upper() + name[1:16]


def prefix():
    return store.cfg("prefix", "$")


def when(ts):
    d = datetime.fromtimestamp(ts, now_paris().tzinfo)
    today = now_paris().date()
    if d.date() == today:
        day = "Aujourd'hui"
    elif d.date() == today - timedelta(days=1):
        day = "Hier"
    else:
        day = d.strftime("%d/%m")
    return f"{day}, {d.strftime('%H:%M')}"


def duration(sec):
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m:02d}"
    return f"{m:02d}:{s:02d}"


def member_name(guild, uid):
    m = guild.get_member(int(uid)) if guild else None
    return brand_of(m) if m else f"joueur {str(uid)[-4:]}"


async def safe_defer(inter):
    try:
        if not inter.response.is_done():
            await inter.response.defer()
    except discord.HTTPException:
        pass


def resolve_member(guild, raw):
    raw = (raw or "").strip()
    if not guild or not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if digits and len(digits) >= 15:
        return guild.get_member(int(digits))
    low = raw.lstrip("@").lower()
    return discord.utils.find(lambda m: m.name.lower() == low or (m.global_name or "").lower() == low
                              or m.display_name.lower() == low, guild.members)


def ok_embed(title, desc=""):
    return discord.Embed(title=title, description=desc, color=0x43b581)


def err_embed(title, desc=""):
    return discord.Embed(title=title, description=desc, color=0xf04747)


async def send_log(guild, em):
    if not guild:
        return
    r = store.db.one("SELECT channel_id FROM log_channels WHERE guild_id = ?", (str(guild.id),))
    ch = guild.get_channel(int(r["channel_id"])) if r else None
    if ch:
        try:
            await ch.send(embed=em, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass


# ========================= GUIDE (embeds) =========================
def guide_embed(key):
    name, _tag, color, _cat = GAMES[key]
    but, how, pay, tip = GUIDE[key]
    em = discord.Embed(title=f"📖 {name}", description=f"**{but}**", color=int(color.lstrip("#"), 16))
    em.add_field(name="🕹️ Comment jouer", value=how, inline=False)
    em.add_field(name="💰 Gains", value=pay, inline=False)
    em.add_field(name="💡 Astuce", value=tip, inline=False)
    em.set_footer(text=f"Joue avec {prefix()}{key} [mise] · monnaie virtuelle, aucune valeur réelle")
    return em


def beginner_embed():
    p = prefix()
    buy = f"{store.setting('buy_fee_bp') / 100:g} %".replace(".", ",")
    sell = f"{store.setting('sell_fee_bp') / 100:g} %".replace(".", ",")
    em = discord.Embed(title="🌱 Guide du débutant", color=0x2BD67B,
                       description=f"Tout se passe sur ton téléphone : tape **`{p}phone`** pour l'allumer, puis utilise les boutons et les menus.")
    em.add_field(name="1. Gagne de l'argent (Banque)", inline=False,
                 value=f"Tout ce que tu gagnes arrive sur ta **Banque**, en euros : récompense quotidienne (`{p}daily`), "
                       f"salaire de ton métier (app **Métiers**, bouton Travailler), intérêts de ton livret d'épargne.")
    em.add_field(name="2. Achète de la crypto (Wallet)", inline=False,
                 value=f"Le casino se joue **uniquement en crypto**. Ouvre l'app **Wallet**, choisis une crypto dans le menu "
                       f"« Acheter » et indique combien d'euros de ta banque tu veux convertir (frais : {buy}).\n"
                       f"Pour débuter, prends de l'**USDT** : sa valeur reste stable. Les autres cryptos (BTC, ETH…) suivent le vrai cours et peuvent monter ou baisser.")
    em.add_field(name="3. Joue au casino", inline=False,
                 value="Ouvre l'app **Casino**, choisis la crypto avec laquelle tu joues dans le dernier menu, puis un jeu. "
                       "Ta mise est indiquée en euros et prise dans ta crypto ; tes gains reviennent dans la même crypto.")
    em.add_field(name="4. Récupère tes gains", inline=False,
                 value=f"Dans le **Wallet**, choisis ta crypto puis **Vendre (wallet → banque)** : l'argent revient sur ta banque "
                       f"(frais : {sell}). C'est avec ta banque que tu achètes dans la **Boutique** et que tu fais des virements.")
    em.add_field(name="Commandes utiles", inline=False,
                 value=f"`{p}phone` · `{p}banque` · `{p}wallet` · `{p}casino` · `{p}daily` · `{p}work` · `{p}guide <jeu>`")
    em.set_footer(text="Monnaie virtuelle : rien ne s'achète ni ne se retire avec de l'argent réel.")
    return em


def guide_home_embed():
    em = discord.Embed(title="📖 Guide",
                       description="Nouveau ? Choisis **Guide du débutant** dans le menu. Sinon, choisis un jeu pour voir ses règles en 30 secondes.",
                       color=0x5865F2)
    em.add_field(name="⭐ Originals", value=" · ".join(v[0] for v in GAMES.values() if v[3] == "originals"), inline=False)
    em.add_field(name="🃏 Casino", value=" · ".join(v[0] for v in GAMES.values() if v[3] == "casino"), inline=False)
    return em


class GuideView(discord.ui.View):
    def __init__(self, author_id=None):
        super().__init__(timeout=300)
        self.author_id = author_id
        opts = [discord.SelectOption(label="Guide du débutant", value="__debutant", emoji="🌱",
                                     description="Banque, Wallet, crypto, casino : comment tout utiliser")]
        opts += [discord.SelectOption(label=v[0], value=k, description=GUIDE[k][0][:100]) for k, v in GAMES.items()]
        sel = discord.ui.Select(placeholder="📖 Choisis un guide…", options=opts)
        sel.callback = self._pick
        self.sel = sel
        self.add_item(sel)

    async def _pick(self, inter):
        v = self.sel.values[0]
        em = beginner_embed() if v == "__debutant" else guide_embed(v)
        if self.author_id and inter.user.id != self.author_id:
            return await inter.response.send_message(embed=em, ephemeral=True)
        await inter.response.edit_message(embed=em, view=self)


# ========================= MODALE GÉNÉRIQUE =========================
class Ask(discord.ui.Modal):
    def __init__(self, phone, title, fields, on_submit):
        super().__init__(title=title[:45])
        self.phone, self.cb = phone, on_submit
        self.inputs = []
        for label, placeholder, required in fields:
            ti = discord.ui.TextInput(label=label[:45], placeholder=placeholder[:100], required=required, max_length=80)
            self.inputs.append(ti)
            self.add_item(ti)

    async def on_submit(self, inter):
        vals = [str(t.value).strip() for t in self.inputs]
        await self.phone.run(inter, lambda i: self.cb(i, *vals))


# ========================= LE TÉLÉPHONE =========================
class Phone(discord.ui.View):
    def __init__(self, member, guild):
        super().__init__(timeout=PHONE_TIMEOUT)
        self.m, self.uid, self.guild = member, member.id, guild
        self.brand = brand_of(member)
        self.screen, self.arg = "home", None
        self.lock = asyncio.Lock()
        self.message = None
        self.opts, self.bets = {}, {}
        self.game = None          # partie en cours
        self.last = None          # (clé, état, résultat, footer) du dernier coup
        self.closed = False
        self.rid = 0              # numéro du dernier affichage (sert à effacer les notifications)
        self.page, self.coin, self.lb = 0, "BTC", "fortune"
        self.play_sym = None      # crypto choisie pour jouer au casino

    # ---------- infra ----------
    async def interaction_check(self, inter):
        if inter.user.id != self.uid:
            await inter.response.send_message(f"Ce n'est pas ton téléphone 🙂 Ouvre le tien avec `{prefix()}phone`.", ephemeral=True)
            return False
        return True

    async def run(self, inter, cb):
        if self.closed:
            return await safe_defer(inter)
        async with self.lock:
            if self.closed:
                return await safe_defer(inter)
            try:
                await cb(inter)
            except Exception as e:
                log.error(f"Téléphone {self.uid} : {e}\n{traceback.format_exc()}")
                try:
                    if not inter.response.is_done():
                        await inter.response.send_message("❌ Petite erreur, réessaie.", ephemeral=True)
                except discord.HTTPException:
                    pass

    def B(self, label, cb, style=GREY, row=None, emoji=None, disabled=False):
        b = discord.ui.Button(label=label, style=style, row=row, emoji=emoji, disabled=disabled)

        async def callback(inter):
            await self.run(inter, cb)
        b.callback = callback
        self.add_item(b)
        return b

    def S(self, placeholder, options, cb, row=None):
        s = discord.ui.Select(placeholder=placeholder, options=options[:25], row=row)

        async def callback(inter):
            await self.run(inter, lambda i: cb(i, s.values[0]))
        s.callback = callback
        self.add_item(s)
        return s

    def go(self, screen, arg=None):
        async def cb(inter):
            self.screen, self.arg = screen, arg
            await self.show(inter)
        return cb

    async def show(self, inter=None, toast=None):
        self.rid += 1
        rid = self.rid
        self.build()
        data = await asyncio.to_thread(self.draw, toast)
        file = discord.File(BytesIO(data), filename="phone.webp")
        try:
            if inter is not None and not inter.response.is_done():
                await inter.response.edit_message(content=None, embed=None, attachments=[file], view=self)
                if inter.message:
                    self.message = inter.message
            elif self.message is not None:
                await self.message.edit(content=None, embed=None, attachments=[file], view=self)
        except discord.HTTPException as e:
            log.warning(f"Affichage téléphone impossible : {e}")
        if toast:
            self.clear_toast_later(rid)

    def clear_toast_later(self, rid):
        """La notification disparaît après TOAST_SECONDS : on réaffiche l'écran tel quel, sans elle."""
        async def later():
            await asyncio.sleep(TOAST_SECONDS)
            async with self.lock:
                if not self.closed and self.rid == rid:
                    await self.show(None)
        asyncio.create_task(later())

    async def on_timeout(self):
        async with self.lock:
            await self.shutdown()

    async def shutdown(self):
        """Ferme le téléphone : termine proprement une partie en cours puis affiche l'écran verrouillé."""
        if self.closed:
            return
        if self.game:
            await self.auto_end()
        self.closed = True
        self.stop()
        if PHONES.get(self.uid) is self:
            PHONES.pop(self.uid, None)
        if self.message:
            try:
                data = await asyncio.to_thread(SA.lock, self.brand, self.notifs())
                await self.message.edit(attachments=[discord.File(BytesIO(data), filename="phone.webp")], view=None)
            except discord.HTTPException:
                pass

    # ---------- données ----------
    def bank(self):
        return store.user(self.uid)["bank"]

    def playing(self):
        """Crypto utilisée au casino : (sym, prix €, quantité, valeur en centimes). Choisit la plus grosse si besoin."""
        hold = store.holdings(self.uid)
        if not hold:
            return None
        if self.play_sym not in hold:
            self.play_sym = max(hold, key=lambda s: hold[s]["qty"] * (feed.price(s) or 0))
        sym = self.play_sym
        p = feed.price(sym) or 0
        q = hold[sym]["qty"]
        return sym, p, q, int(q * p * 100)

    def play_value(self):
        p = self.playing()
        return p[3] if p else 0

    def notifs(self):
        u = store.user(self.uid)
        out = []
        if time.time() - u["last_daily"] >= 86400:
            out.append((f"{self.brand} Casino", "#7C4DFF", "dice", "maintenant", "Ta récompense quotidienne est prête."))
        sal = store.db.one("SELECT * FROM ledger WHERE user_id = ? AND label LIKE 'Salaire%' ORDER BY id DESC LIMIT 1", (str(self.uid),))
        if sal:
            out.append(("Banque", "#2F6BFF", "bank", when(sal["ts"]).split(", ")[-1], f"{sal['label']} : {eur(sal['amount'], True)}"))
        btc = feed.coin("BTC")
        if btc["price"]:
            out.append(("Crypto", "#17A660", "chart", "24 h", f"BTC {btc['change']:+.2f} % · {eur(int(btc['price'] * 100))}".replace(".", ",")))
        job = JOB_BY_KEY.get(u["job"], JOBS[0])
        if time.time() - u["last_work"] >= job[4]:
            out.append(("Métiers", "#D9573B", "job", "maintenant", f"Ton service de {job[1].lower()} est disponible."))
        return out

    def crypto_value(self):
        hold = store.holdings(self.uid)
        val = cost = 0
        for sym, h in hold.items():
            p = feed.price(sym) or 0
            val += int(h["qty"] * p * 100)
            cost += h["cost"]
        return val, cost, hold

    # ---------- rendu (thread) ----------
    def draw(self, toast=None):
        s = self.screen
        u = store.user(self.uid)
        if s == "home":
            store.accrue(self.uid)
            u = store.user(self.uid)
            cval, _c, _h = self.crypto_value()
            vip = vip_for(u["wagered"])
            left = u["last_daily"] + 86400 - time.time()
            c = feed.coin("BTC")
            return SA.home(dict(brand=self.brand, bank=u["bank"], savings=u["savings"], crypto=cval,
                                total=u["bank"] + u["savings"] + cval, vip=vip[1], vip_color=vip[2],
                                daily_ready=left <= 0, streak=u["streak"], daily_in=duration(left),
                                coin=dict(sym="BTC", change=c["change"], price=int(c["price"] * 100), spark=c["spark"]) if c["price"] else None), toast)
        if s == "casino":
            p = self.playing()
            play = dict(sym=p[0], color=META[p[0]][2], value=p[3]) if p else None
            return SA.lobby(self.brand, play, [(k, v[0], v[1], v[2], v[3]) for k, v in GAMES.items()], "all", toast)
        if s == "game":
            return self.draw_game(u, toast)
        if s == "needcrypto":
            return SA.need_crypto(self.brand, u["bank"], toast)
        if s == "wallet":
            val, cost, hold = self.crypto_value()
            assets = []
            for sym, h in hold.items():
                co = feed.coin(sym)
                assets.append(dict(sym=sym, name=co["name"], color=co["color"], qty=h["qty"], value=int(h["qty"] * co["price"] * 100), change=co["change"]))
            assets.sort(key=lambda a: a["value"], reverse=True)
            p = self.playing()
            return SA.wallet(self.brand, val, val - cost, assets, p[0] if p else None, self.fees(), toast)
        if s == "bank":
            store.accrue(self.uid)
            u = store.user(self.uid)
            rate = store.setting("savings_rate_bp") / 100
            return SA.bank(self.brand, u["bank"], u["savings"],
                           (f"+{rate:g} % / jour".replace(".", ","), f"plafond {eur(store.setting('savings_cap'))}"),
                           [r[:5] for r in self.ledger_rows("bank")], toast)
        if s == "crypto":
            val, cost, hold = self.crypto_value()
            coins = feed.all()
            for co in coins:
                h = hold.get(co["sym"])
                co["qty"] = h["qty"] if h else 0
            return SA.crypto(self.brand, val, val - cost, coins, feed.live, self.page, toast)
        if s == "coin":
            co = feed.coin(self.coin)
            h = store.holdings(self.uid).get(self.coin)
            qty = h["qty"] if h else 0
            avg = int(h["cost"] / qty) if h and qty else None
            return SA.crypto_coin(co, qty, int(qty * co["price"] * 100), u["bank"], avg, self.fees(), toast)
        if s == "jobs":
            return self.draw_jobs(u, toast)
        if s == "profile":
            return self.draw_profile(u, toast)
        if s == "top":
            return self.draw_top(toast)
        if s == "shop":
            return SA.shop(u["bank"], self.shop_rows(), toast)
        if s == "fair":
            sd = store.seeds(self.uid)
            prev = (sd["prev_server"], sd["prev_client"], sd["prev_nonce"]) if sd["prev_server"] else None
            return SA.fair(sha256(sd["server_seed"]), sd["client_seed"], sd["nonce"], prev, toast)
        if s == "help":
            return SA.help_screen(self.help_groups(), toast)
        return SA.lock(self.brand, self.notifs(), toast)

    def shop_rows(self):
        roles = {str(r.id) for r in getattr(self.m, "roles", [])}
        out = []
        for i in store.shop_items():
            out.append(dict(id=i["item_id"], name=i["name"], price=i["price"], desc=i["description"], kind=i["kind"],
                            owned=i["kind"] == "role" and bool(i["role_id"]) and i["role_id"] in roles,
                            left=None if i["stock"] < 0 else max(0, i["stock"] - i["sold"]),
                            bought=store.user_orders_count(self.uid, i["item_id"]) if i["per_user"] else 0, limit=i["per_user"]))
        return out

    def ledger_rows(self, account):
        rows = []
        for r in store.ledger(self.uid, account, 6):
            label = r["label"]
            if label.startswith("@to:"):
                label = f"Virement à {member_name(self.guild, label[4:])}"
                badge, color = "@", "#C9CFDA"
            elif label.startswith("@from:"):
                label = f"Virement de {member_name(self.guild, label[6:])}"
                badge, color = "@", "#C9CFDA"
            elif label.startswith("Salaire"):
                badge, color = "€", "#2BD67B"
            elif "Intérêts" in label:
                badge, color = "%", "#F5C451"
            elif label.startswith(("Achat", "Vente")):
                badge, color = label.split()[-1][:3], "#17A660"
            else:
                badge, color = label[:2].upper(), "#7FB0FF"
            rows.append((label, when(r["ts"]), r["amount"], badge, color, r["ts"]))
        return rows

    @staticmethod
    def fees():
        f = lambda bp: f"{bp / 100:g} %".replace(".", ",")
        return f(store.setting("buy_fee_bp")), f(store.setting("sell_fee_bp"))

    def draw_jobs(self, u, toast):
        lvl, xp, need = level_of(u["xp"])
        job = JOB_BY_KEY.get(u["job"], JOBS[0])
        pay = int(job[3] * (1 + 0.04 * max(0, lvl - job[2])))
        left = u["last_work"] + job[4] - time.time()
        trained = set(filter(None, u["trained"].split(",")))
        rows = []
        for k, name, req, base, cd, cost, color, ic in JOBS:
            unlocked = lvl >= req and (not cost or k in trained)
            if k == job[0]:
                state = "Actuel"
            elif lvl < req:
                state = f"Niv. {req} requis"
            elif cost and k not in trained:
                state = f"Formation {eur(cost)}"
            else:
                state = "Débloqué"
            sub = f"Niveau {req} · toutes les {cd // 60} min" + (f" · formation {cost // 100} €" if cost else "")
            rows.append((name, sub, eur(base), state, color, unlocked or k == job[0], k == job[0]))
        ready_txt = "Service disponible : appuie sur Travailler" if left <= 0 else f"Prochain service dans {duration(left)}"
        return SA.jobs((job[1], job[6], job[7], eur(pay)), lvl, xp, need, ready_txt, left <= 0, rows, toast)

    def draw_profile(self, u, toast):
        vip, nxt = vip_for(u["wagered"]), next_vip(u["wagered"])
        fav = store.db.one("SELECT game, COUNT(*) AS n FROM bets WHERE user_id = ? GROUP BY game ORDER BY n DESC LIMIT 1", (str(self.uid),))
        lvl = level_of(u["xp"])[0]
        job = JOB_BY_KEY.get(u["job"], JOBS[0])
        badges = []
        if u["best_mult"] >= 100:
            badges.append(("x100", "#3B2E0A", "#F5C451"))
        elif u["best_mult"] >= 10:
            badges.append(("x10", "#3B2E0A", "#F5C451"))
        if u["streak"] >= 7:
            badges.append(("7 j", "#0E3324", "#2BD67B"))
        if u["games"] >= 1000:
            badges.append(("1000", "#14264A", "#7FB0FF"))
        elif u["games"] >= 100:
            badges.append(("100", "#14264A", "#7FB0FF"))
        if store.holdings(self.uid):
            badges.append(("HODL", "#2A1F4D", "#B9A2FF"))
        if vip[0] >= 250_000:
            badges.append(("VIP", "#3B2E0A", "#F5C451"))
        fortunes = self.fortunes()
        mine = fortunes.get(str(self.uid), 0)
        rank = sum(1 for v in fortunes.values() if v > mine) + 1
        pct = (u["wagered"] - vip[0]) / max(1, nxt[0] - vip[0]) if nxt else 1
        return SA.profile(dict(name=self.brand, vip=vip[1], vip_color=vip[2], next_vip=nxt[1] if nxt else None, pct=min(1, pct),
                               left=(nxt[0] - u["wagered"]) if nxt else 0, job=f"{job[1]} niv. {lvl}",
                               stats=[("Parties jouées", f"{u['games']:,}".replace(",", " "), "#F2F4F8"), ("Total misé", eur(u["wagered"]), "#F2F4F8"),
                                      ("Profit", eur(u["profit"], True), "#2BD67B" if u["profit"] >= 0 else "#FF7A84"),
                                      ("Plus gros gain", eur(max(0, u["biggest_win"])), "#F5C451")],
                               fav=GAMES[fav["game"]][0] if fav and fav["game"] in GAMES else None, badges=badges, rank=rank), toast)

    LB = {"fortune": "Fortune (banque + épargne + crypto)", "wagered": "Total misé au casino", "profit": "Profit au casino"}

    @staticmethod
    def fortunes():
        """Fortune de chaque joueur en centimes : banque + épargne + valeur de sa crypto au cours actuel."""
        out = {r["user_id"]: r["bank"] + r["savings"] for r in store.db.all("SELECT user_id, bank, savings FROM users")}
        for h in store.db.all("SELECT user_id, sym, qty FROM holdings WHERE qty > 0"):
            out[h["user_id"]] = out.get(h["user_id"], 0) + int(h["qty"] * (feed.price(h["sym"]) or 0) * 100)
        return out

    def draw_top(self, toast):
        label = self.LB[self.lb]
        if self.lb == "fortune":
            vals = self.fortunes()
        else:
            vals = {r["user_id"]: r["v"] for r in store.db.all(f"SELECT user_id, {self.lb} AS v FROM users")}
        ranked = sorted(vals.items(), key=lambda kv: kv[1], reverse=True)
        out = [(i + 1, member_name(self.guild, uid), eur(v), uid == str(self.uid)) for i, (uid, v) in enumerate(ranked[:10])]
        me = None
        if not any(r[3] for r in out):
            pos = next((i + 1 for i, (uid, _v) in enumerate(ranked) if uid == str(self.uid)), len(ranked) + 1)
            me = (pos, eur(vals.get(str(self.uid), 0)))
        return SA.leaderboard(label, out, me, toast)

    def help_groups(self):
        p = prefix()
        g = [("Jouer", [("Casino", f"19 jeux en crypto · {p}casino ou {p}<jeu> [mise]", "#7C4DFF", "dice"),
                        ("Guide", f"Débutant et règles des jeux · {p}guide", "#5A6578", "book"),
                        ("Provably fair", "Vérifie chaque tirage", "#0E8A8A", "shield")]),
             ("Argent", [("Banque", f"Salaires, daily, épargne, virements · {p}banque", "#2F6BFF", "bank"),
                         ("Wallet crypto", f"Acheter, vendre, jouer · {p}wallet {p}marche", "#E0A526", "wallet"),
                         ("Métiers et Daily", f"Gagne de l'argent · {p}metiers {p}daily", "#D9573B", "job")])]
        r = store.rank(self.uid)
        if r >= 2:
            g.append(("Staff", [("Économie", f"{p}addmoney {p}removemoney {p}setmoney {p}resetbalance", "#5A6578", "wallet"),
                                ("Boutique", f"{p}additem {p}edititem {p}items {p}commandes", "#D6336C", "bag"),
                                ("Salons", f"{p}allow {p}unallow {p}setorders {p}setlog", "#3B4252", "sliders")]))
        return g

    # ---------- construction des boutons ----------
    def build(self):
        self.clear_items()
        s = self.screen
        if s == "home":
            u = store.user(self.uid)
            ready = time.time() - u["last_daily"] >= 86400
            for label, scr, st in (("Casino", "casino", BLUE), ("Wallet", "wallet", GREY), ("Banque", "bank", GREY),
                                   ("Marché", "crypto", GREY), ("Métiers", "jobs", GREY)):
                self.B(label, self.go(scr), st, 0)
            for label, scr in (("Profil", "profile"), ("Top", "top"), ("Boutique", "shop")):
                self.B(label, self.go(scr), GREY, 1)
            self.B("Daily", self.daily, GREEN if ready else GREY, 1, disabled=not ready)
            self.B("Fair", self.go("fair"), GREY, 1)
            self.B("Guide", self.guide_btn, GREY, 2, emoji="📖")
            self.B("Aide", self.go("help"), GREY, 2)
            self.B("Verrouiller", self.lock_btn, RED, 2, emoji="🔒")
        elif s == "casino":
            for row, cat, ph in ((0, "originals", "⭐ Originals : choisis un jeu…"), (1, "casino", "🃏 Casino : choisis un jeu…")):
                opts = [discord.SelectOption(label=v[0], value=k, description=GUIDE[k][0][:100]) for k, v in GAMES.items() if v[3] == cat]
                self.S(ph, opts, self.pick_game, row)
            hold = store.holdings(self.uid)
            if hold:
                p = self.playing()
                opts = []
                for sym, h in hold.items():
                    v = int(h["qty"] * (feed.price(sym) or 0) * 100)
                    opts.append(discord.SelectOption(label=f"Jouer en {sym} · {META[sym][1]}", value=sym, default=bool(p) and sym == p[0],
                                                     description=f"Solde : {eur(v)}"[:100]))
                self.S("Choisis la crypto avec laquelle tu joues…", opts, self.set_play, 2)
                self.B("Accueil", self.go("home"), GREY, 3)
                self.B("Wallet", self.go("wallet"), GREY, 3)
                self.B("Guide", self.guide_btn, GREY, 3, emoji="📖")
            else:
                self.B("Acheter de la crypto pour jouer", self.go("needcrypto"), GREEN, 2, emoji="🪙")
                self.B("Accueil", self.go("home"), GREY, 2)
                self.B("Guide", self.guide_btn, GREY, 2, emoji="📖")
        elif s == "needcrypto":
            self.B("Acheter de l'USDT (stable)", self.open_coin("USDT"), GREEN, 0, emoji="🪙")
            self.B("Choisir une autre crypto", self.go("crypto"), BLUE, 0)
            self.B("Guide débutant", self.beginner_btn, GREY, 1, emoji="📖")
            self.B("Banque", self.go("bank"), GREY, 1)
            self.B("Accueil", self.go("home"), GREY, 1)
        elif s == "game":
            if self.game:
                self.build_live()
            else:
                self.build_setup()
        elif s == "wallet":
            self.S("Acheter une crypto avec ma banque…", self.coin_options(), self.pick_coin, 0)
            hold = store.holdings(self.uid)
            if hold:
                self.S("Mes cryptos : vendre vers la banque, jouer…",
                       [discord.SelectOption(label=f"{sym} · {META[sym][1]}", value=sym,
                                             description=f"{h['qty']:.8g} {sym} · {eur(int(h['qty'] * (feed.price(sym) or 0) * 100))}"[:100])
                        for sym, h in hold.items()], self.pick_coin, 1)
            self.B("Casino", self.go("casino"), BLUE, 2, emoji="🎰")
            self.B("Marché", self.go("crypto"), GREY, 2)
            self.B("Banque", self.go("bank"), GREY, 2)
            self.B("Accueil", self.go("home"), GREY, 2)
        elif s == "bank":
            self.B("Acheter de la crypto", self.go("wallet"), GREEN, 0, emoji="🪙")
            self.B("Virement", self.wire, BLUE, 0)
            self.B("Épargner", self.to_savings, GREY, 1)
            self.B("Débloquer l'épargne", self.from_savings, GREY, 1)
            self.B("Accueil", self.go("home"), GREY, 2)
            self.B("Wallet", self.go("wallet"), GREY, 2)
            self.B("Boutique", self.go("shop"), GREY, 2)
        elif s == "crypto":
            self.S("Choisis une crypto à acheter…", self.coin_options(), self.pick_coin, 0)
            self.B("◀", self.crypto_page(-1), GREY, 1, disabled=self.page == 0)
            self.B("▶", self.crypto_page(1), GREY, 1, disabled=self.page >= 1)
            self.B("Actualiser", self.go("crypto"), GREY, 1)
            self.B("Wallet", self.go("wallet"), GREY, 1)
            self.B("Accueil", self.go("home"), GREY, 1)
        elif s == "coin":
            held = store.qty_of(self.uid, self.coin) > 0
            self.B("Acheter (banque → wallet)", self.buy_coin, GREEN, 0)
            self.B("Vendre (wallet → banque)", self.sell_coin, RED, 0, disabled=not held)
            self.B("Tout vendre", self.sell_all, GREY, 1, disabled=not held)
            self.B(f"Jouer au casino en {self.coin}", self.play_with(self.coin), BLUE, 1, emoji="🎰", disabled=not held)
            self.B("Wallet", self.go("wallet"), GREY, 2)
            self.B("Marché", self.go("crypto"), GREY, 2)
            self.B("Accueil", self.go("home"), GREY, 2)
        elif s == "jobs":
            u = store.user(self.uid)
            job = JOB_BY_KEY.get(u["job"], JOBS[0])
            ready = time.time() - u["last_work"] >= job[4]
            self.B("Travailler", self.work, GREEN if ready else GREY, 0, disabled=not ready)
            lvl = level_of(u["xp"])[0]
            opts = [discord.SelectOption(label=j[1], value=j[0], default=j[0] == job[0],
                                         description=(f"Niveau {j[2]} · {eur(j[3])} / service" + (f" · formation {eur(j[5])}" if j[5] else ""))[:100])
                    for j in JOBS if lvl >= j[2]]
            self.S("Changer de métier…", opts, self.change_job, 1)
            self.B("Accueil", self.go("home"), GREY, 2)
            self.B("Banque", self.go("bank"), GREY, 2)
        elif s == "profile":
            u = store.user(self.uid)
            rb = int(u["rakeback"])
            self.B(f"Rakeback {eur(rb)}" if rb else "Rakeback", self.rakeback, GREEN if rb else GREY, 0, disabled=rb < 1)
            self.B("Classement", self.go("top"), GREY, 0)
            self.B("Provably fair", self.go("fair"), GREY, 0)
            self.B("Accueil", self.go("home"), GREY, 0)
        elif s == "top":
            for k, lab in (("fortune", "Fortune"), ("wagered", "Total misé"), ("profit", "Profit")):
                self.B(lab, self.set_lb(k), BLUE if self.lb == k else GREY, 0)
            self.B("Accueil", self.go("home"), GREY, 0)
        elif s == "shop":
            items = store.shop_items()
            if items:
                opts = []
                for i in items:
                    kind = C.ITEM_KINDS.get(i["kind"], C.ITEM_KINDS["custom"])[0]
                    left = "" if i["stock"] < 0 else f" · {max(0, i['stock'] - i['sold'])} en stock"
                    opts.append(discord.SelectOption(label=i["name"][:100], value=str(i["item_id"]),
                                                     description=f"{eur(i['price'])} · {kind}{left}"[:100]))
                self.S("Acheter un article…", opts, self.buy_item, 0)
            self.B("Accueil", self.go("home"), GREY, 1)
            self.B("Wallet", self.go("wallet"), GREY, 1)
        elif s == "fair":
            self.B("Changer de seed", self.new_seed, BLUE, 0)
            self.B("Accueil", self.go("home"), GREY, 0)
        elif s == "help":
            self.B("Guide des jeux", self.guide_btn, BLUE, 0, emoji="📖")
            self.B("Accueil", self.go("home"), GREY, 0)

    # ---------- actions générales ----------
    async def lock_btn(self, inter):
        await safe_defer(inter)
        await self.shutdown()

    async def guide_btn(self, inter):
        if self.screen == "game" and self.arg in GUIDE:
            await inter.response.send_message(embed=guide_embed(self.arg), ephemeral=True)
        else:
            await inter.response.send_message(embed=guide_home_embed(), view=GuideView(), ephemeral=True)

    async def daily(self, inter):
        amount, info = store.claim_daily(self.uid)
        if amount is None:
            return await self.show(inter, (f"Daily déjà récupérée · reviens dans {duration(info - time.time())}", "err"))
        await self.show(inter, (f"Daily : {eur(amount, True)} sur ta banque (série {info})", "gold"))

    async def rakeback(self, inter):
        amt = store.claim_rakeback(self.uid)
        await self.show(inter, (f"Rakeback versé en banque : {eur(amt, True)}", "ok") if amt else ("Rien à récupérer", "info"))

    def set_lb(self, k):
        async def cb(inter):
            self.lb = k
            await self.show(inter)
        return cb

    async def new_seed(self, inter):
        async def done(i, client):
            if client and not re.fullmatch(r"[\w\-]{1,64}", client):
                return await self.show(i, ("Seed client : lettres, chiffres, - et _", "err"))
            if store.active_game(self.uid):
                return await self.show(i, ("Termine ta partie avant de changer de seed", "err"))
            store.rotate_seeds(self.uid, client or None)
            await self.show(i, ("Nouveau seed · l'ancien est révélé", "ok"))
        await inter.response.send_modal(Ask(self, "Nouveau seed", [("Seed client (optionnel)", "laisse vide pour un seed aléatoire", False)], done))

    # ---------- argent ----------
    def _amount_modal(self, title, label, balance_fn, action):
        async def opener(inter):
            async def done(i, raw):
                amt = parse_eur(raw, balance_fn())
                if amt is None:
                    return await self.show(i, ("Montant invalide (ex : 12,50 · 1k · tout · 50%)", "err"))
                await action(i, amt)
            await inter.response.send_modal(Ask(self, title, [(label, "ex : 25 · 12,50 · tout · 50%", True)], done))
        return opener

    @property
    def to_savings(self):
        async def act(i, amt):
            ok = store.move(self.uid, "bank", "savings", amt, "Versement livret", "Versement livret")
            await self.show(i, (f"{eur(amt)} placés sur le livret", "ok") if ok else ("Compte en banque insuffisant", "err"))
        return self._amount_modal("Épargner", "Montant à placer", lambda: store.user(self.uid)["bank"], act)

    @property
    def from_savings(self):
        async def act(i, amt):
            ok = store.move(self.uid, "savings", "bank", amt, "Retrait livret", "Retrait livret")
            await self.show(i, (f"{eur(amt)} récupérés du livret", "ok") if ok else ("Livret insuffisant", "err"))
        return self._amount_modal("Débloquer l'épargne", "Montant à récupérer", lambda: store.user(self.uid)["savings"], act)

    def _transfer_modal(self, title, src):
        async def opener(inter):
            async def done(i, who, raw):
                target = resolve_member(self.guild, who)
                if not target or target.bot or target.id == self.uid:
                    return await self.show(i, ("Destinataire introuvable", "err"))
                bal = store.user(self.uid)[src]
                amt = parse_eur(raw, bal)
                if amt is None:
                    return await self.show(i, ("Montant invalide", "err"))
                if not store.transfer(self.uid, target.id, amt, src):
                    return await self.show(i, ("Solde insuffisant", "err"))
                await self.show(i, (f"{eur(amt)} envoyés à {brand_of(target)}", "ok"))
                em = discord.Embed(title="💸 Virement", color=0x3498db, timestamp=datetime.now(timezone.utc),
                                   description=f"{self.m.mention} → {target.mention} : **{eur(amt)}** (banque)")
                await send_log(self.guild, em)
            await inter.response.send_modal(Ask(self, title, [("Destinataire", "nom d'utilisateur, mention ou ID", True),
                                                              ("Montant", "ex : 20 · 5,50 · tout", True)], done))
        return opener

    @property
    def wire(self):
        return self._transfer_modal("Virement bancaire", "bank")

    # ---------- crypto (wallet) ----------
    def coin_options(self):
        opts = []
        for sym, name, _c, _g in COINS:
            p = feed.price(sym)
            extra = " · stable, idéal pour débuter" if sym == "USDT" else ""
            opts.append(discord.SelectOption(label=f"{sym} · {name}", value=sym,
                                             description=((SA._price(p) if p else "cours indisponible") + extra)[:100]))
        return opts

    def crypto_page(self, d):
        async def cb(inter):
            self.page = max(0, min(1, self.page + d))
            await self.show(inter)
        return cb

    async def pick_coin(self, inter, sym):
        self.coin, self.screen = sym, "coin"
        await self.show(inter)

    def open_coin(self, sym):
        async def cb(inter):
            await self.pick_coin(inter, sym)
        return cb

    async def set_play(self, inter, sym):
        self.play_sym = sym
        await self.show(inter, (f"Tu joues maintenant en {sym}", "ok"))

    def play_with(self, sym):
        async def cb(inter):
            self.play_sym = sym
            self.screen = "casino"
            await self.show(inter, (f"Tu joues maintenant en {sym}", "ok"))
        return cb

    @property
    def buy_coin(self):
        async def act(i, amt):
            qty, info = store.buy_crypto(self.uid, self.coin, amt, feed.price(self.coin))
            if qty is None:
                return await self.show(i, (info, "err"))
            if self.play_sym is None:
                self.play_sym = self.coin
            await self.show(i, (f"+{qty:.6g} {self.coin} dans ton Wallet · frais {eur(info)}", "ok"))
        return self._amount_modal(f"Acheter du {self.coin}", "Montant pris sur ta banque (€)", lambda: store.user(self.uid)["bank"], act)

    @property
    def sell_coin(self):
        def value():
            return int(store.qty_of(self.uid, self.coin) * (feed.price(self.coin) or 0) * 100)

        async def act(i, amt):
            got, info = store.sell_crypto(self.uid, self.coin, amt, feed.price(self.coin), all_=amt >= value())
            if got is None:
                return await self.show(i, (info, "err"))
            await self.show(i, (f"{eur(got, True)} versés sur ta banque · frais {eur(info)}", "ok"))
        return self._amount_modal(f"Vendre du {self.coin}", "Montant à envoyer vers la banque (€)", value, act)

    async def sell_all(self, inter):
        got, info = store.sell_crypto(self.uid, self.coin, 0, feed.price(self.coin), all_=True)
        if got is None:
            return await self.show(inter, (info, "err"))
        await self.show(inter, (f"Tout vendu : {eur(got, True)} sur ta banque · frais {eur(info)}", "ok"))

    async def beginner_btn(self, inter):
        await inter.response.send_message(embed=beginner_embed(), ephemeral=True)

    # ---------- métiers / boutique ----------
    async def work(self, inter):
        pay, info = store.work(self.uid)
        if pay is None:
            return await self.show(inter, (f"Encore {duration(info - time.time())} avant ton prochain service", "err"))
        await self.show(inter, (f"Salaire versé en banque : {eur(pay, True)} · +{info} XP", "ok"))

    async def change_job(self, inter, key):
        err = store.set_job(self.uid, key)
        await self.show(inter, (err, "err") if err else (f"Nouveau métier : {JOB_BY_KEY[key][1]}", "ok"))

    async def buy_item(self, inter, item_id):
        it = store.shop_item(item_id)
        if not it or not it["active"]:
            return await self.show(inter, ("Article introuvable", "err"))
        role = None
        if it["kind"] == "role":
            role = self.guild.get_role(int(it["role_id"])) if it["role_id"] else None
            if role is None:
                return await self.show(inter, ("Le rôle de cet article n'existe plus", "err"))
            if role in self.m.roles:
                return await self.show(inter, ("Tu possèdes déjà ce rôle", "info"))
        order, err = store.buy_item(self.uid, it["item_id"], self.guild.id)
        if err:
            return await self.show(inter, (err, "err"))
        if role:
            try:
                await self.m.add_roles(role, reason=f"Boutique · commande #{order['id']}")
            except discord.HTTPException:
                store.refund_order(order["id"])
                return await self.show(inter, ("Impossible de donner le rôle · remboursé", "err"))
            await self.show(inter, (f"{it['name']} acheté · rôle ajouté", "ok"))
            await send_log(self.guild, order_embed(order, self.m, "Livré automatiquement"))
            return
        await self.show(inter, (f"Commande #{order['id']} envoyée · le staff va te livrer", "gold"))
        await post_order(self.guild, order, self.m)

    # ======================= JEUX : écran de mise =======================
    async def pick_game(self, inter, key):
        self.open_game(key)
        await self.show(inter)

    def open_game(self, key, bet=None):
        if not store.holdings(self.uid) and not self.game:
            self.screen, self.arg = "needcrypto", None  # pas de crypto : on explique comment en acheter
            return
        self.screen, self.arg = "game", key
        eng = ENGINES[key]
        if key not in self.opts:
            self.opts[key] = {k: (list(v) if isinstance(v, list) else v) for k, v in eng.OPTIONS.items()}
        if bet is not None:
            self.bets[key] = bet
        self.bets.setdefault(key, max(store.setting("min_bet"), 100))
        self.clamp_bet(key)
        if not (self.last and self.last[0] == key):
            self.last = None

    def clamp_bet(self, key):
        mn, mx = store.setting("min_bet"), store.setting("max_bet")
        cash = self.play_value()
        hi = max(mn, cash if not mx else min(cash, mx))
        self.bets[key] = int(max(mn, min(self.bets[key], hi)))

    def header_balance(self):
        p = self.playing()
        return f"{p[0]} · {eur(p[3])}" if p else "0,00 €"

    def draw_game(self, u, toast):
        key = self.arg
        title = GAMES[key][0]
        bal = self.header_balance()
        if self.game:
            g = self.game
            st = g["e"].st
            return SG.render(key, title, bal, g["bet_total"], st, None, f"Partie #{g['gid']} · mise en {g['sym']} · provably fair", toast)
        bet = self.bets[key]
        if self.last and self.last[0] == key:
            _k, st, res, footer = self.last
            return SG.render(key, title, bal, res["bet"] if res else bet, st, res, footer, toast)
        eng = ENGINES[key]
        st = eng.idle(self.opts[key], CRASH_RECENT) if key == "crash" else eng.idle(self.opts[key])
        p = self.playing()
        sym = p[0] if p else "crypto"
        return SG.render(key, title, bal, bet, st, None, f"Mise : {eur(bet)} payés en {sym} · ajuste-la avec les boutons", toast)

    def build_setup(self):
        key = self.arg
        o = self.opts[key]
        self.B("½", self.bet_fn(lambda b: b // 2), GREY, 0)
        self.B("−1 €", self.bet_fn(lambda b: b - 100), GREY, 0)
        self.B("+1 €", self.bet_fn(lambda b: b + 100), GREY, 0)
        self.B("×2", self.bet_fn(lambda b: b * 2), GREY, 0)
        self.B(f"Mise {eur(self.bets[key])}", self.bet_modal, BLUE, 0)

        def opt(label, field, value, row, style_on=BLUE):
            on = o.get(field) == value
            self.B(label, self.set_opt(field, value), style_on if on else GREY, row)

        if key == "mines":
            for n in (1, 3, 5, 10, 15):
                opt(f"{n} mine{'s' if n > 1 else ''}", "n", n, 1)
            self.B(f"Autre ({o['n']})", self.num_modal("n", "Nombre de mines", f"1 à {MINES_TILES - 1}", lambda v: 1 <= v <= MINES_TILES - 1, int), GREY, 2)
        elif key == "crash":
            for lab, v in (("Manuel", 0), ("Auto x1,5", 1.5), ("Auto x2", 2), ("Auto x5", 5), ("Auto x10", 10)):
                opt(lab, "auto", v, 1)
            self.B("Auto perso", self.num_modal("auto", "Auto-cashout", "ex : 3,5 (0 = manuel)", lambda v: v == 0 or 1.01 <= v <= 1000, float), GREY, 2)
        elif key == "dice":
            self.B("Plus de" if o["dir"] == "over" else "Moins de", self.dice_flip, BLUE, 1, emoji="⇅")
            for d in (-10, -1, 1, 10):
                self.B(f"{d:+d}", self.dice_adj(d), GREY, 1)
            self.B(f"Cible {o['target']:.2f}".replace(".", ","), self.num_modal("target", "Cible du dé", "entre 1,01 et 98,99", lambda v: 1.01 <= v <= 98.99, float), GREY, 2)
        elif key == "limbo":
            for lab, v in (("x1,5", 1.5), ("x2", 2.0), ("x5", 5.0), ("x10", 10.0), ("x100", 100.0)):
                opt(lab, "target", v, 1)
            self.B(f"Cible {xfmt(o['target'])}", self.num_modal("target", "Cible Limbo", "entre 1,01 et 1 000 000", lambda v: 1.01 <= v <= 1_000_000, float), GREY, 2)
        elif key == "plinko":
            for lab in ("low", "medium", "high"):
                opt(lab.capitalize(), "risk", lab, 1)
            for r in (8, 12, 16):
                opt(f"{r} lignes", "rows", r, 2)
        elif key == "wheel":
            for lab in ("low", "medium", "high"):
                opt(lab.capitalize(), "risk", lab, 1)
        elif key == "keno":
            for n in (3, 5, 8, 10):
                self.B(f"{n} numéros", self.keno_random(n), BLUE if len(o["picks"]) == n else GREY, 1)
            self.B("Aléatoire", self.keno_random(len(o["picks"])), GREY, 1, emoji="🔀")
            self.B("Mes numéros", self.keno_modal, GREY, 2, emoji="✏️")
        elif key == "coinflip":
            opt("Pile", "choice", "pile", 1)
            opt("Face", "choice", "face", 1)
        elif key == "roulette":
            for k in ("red", "black", "even", "odd"):
                opt(ROULETTE_BETS[k][0], "choice", k, 1, RED if k == "red" else BLUE)
            for k in ("low", "high", "d1", "d2", "d3"):
                opt(ROULETTE_BETS[k][0], "choice", k, 2)
            self.B("Numéro plein (x36)", self.num_modal("choice", "Numéro plein", "0 à 36", lambda v: 0 <= v <= 36, int), GREY, 3)
        elif key == "baccarat":
            opt("Joueur x2", "side", "player", 1)
            opt("Banquier x1,95", "side", "banker", 1, RED)
            opt("Égalité x9", "side", "tie", 1)
        elif key == "dragon":
            for d in DRAGON_DIFF:
                opt(d.capitalize(), "diff", d, 1)
        elif key in ("chicken", "pump"):
            for d, p in LADDER_DIFF.items():
                opt(f"{d.capitalize()} {int(p * 100)} %", "diff", d, 1)
        play_label = {"slots": "Lancer", "case": "Ouvrir", "diamonds": "Révéler", "plinko": "Lâcher", "wheel": "Tourner",
                      "roulette": "Tourner", "keno": "Tirer", "blackjack": "Distribuer", "videopoker": "Distribuer",
                      "baccarat": "Distribuer", "coinflip": "Lancer", "dice": "Lancer", "crash": "Décoller"}.get(key, "Jouer")
        again = self.last is not None and self.last[0] == key
        self.B(("Rejouer · " if again else "") + play_label, self.play, GREEN, 4, emoji="🔁" if again else "▶️")
        self.B("Casino", self.go("casino"), GREY, 4)
        self.B("Guide", self.guide_btn, GREY, 4, emoji="📖")

    def bet_fn(self, fn):
        async def cb(inter):
            self.bets[self.arg] = fn(self.bets[self.arg])
            self.clamp_bet(self.arg)
            await self.show(inter)
        return cb

    async def bet_modal(self, inter):
        async def done(i, raw):
            v = parse_eur(raw, self.play_value())
            if v is None:
                return await self.show(i, ("Mise invalide (ex : 5 · 2,50 · tout · 25%)", "err"))
            self.bets[self.arg] = v
            self.clamp_bet(self.arg)
            await self.show(i)
        await inter.response.send_modal(Ask(self, "Ta mise", [("Montant", "ex : 5 · 2,50 · tout · 25%", True)], done))

    def set_opt(self, field, value):
        async def cb(inter):
            self.opts[self.arg][field] = value
            self.last = None
            await self.show(inter)
        return cb

    def num_modal(self, field, title, hint, valid, cast):
        async def opener(inter):
            async def done(i, raw):
                try:
                    v = cast(float(raw.replace(",", ".").lstrip("x")))
                except ValueError:
                    return await self.show(i, ("Valeur invalide", "err"))
                if not valid(v):
                    return await self.show(i, (f"Valeur attendue : {hint}", "err"))
                self.opts[self.arg][field] = round(v, 2) if cast is float else v
                if self.arg == "dice":
                    Dice.clamp(self.opts["dice"])
                self.last = None
                await self.show(i)
            await inter.response.send_modal(Ask(self, title, [(title, hint, True)], done))
        return opener

    async def dice_flip(self, inter):
        o = self.opts["dice"]
        o["dir"] = "under" if o["dir"] == "over" else "over"
        o["target"] = round(100 - o["target"], 2)
        Dice.clamp(o)
        self.last = None
        await self.show(inter)

    def dice_adj(self, d):
        async def cb(inter):
            o = self.opts["dice"]
            o["target"] += d
            Dice.clamp(o)
            self.last = None
            await self.show(inter)
        return cb

    def keno_random(self, n):
        async def cb(inter):
            import secrets as _s
            nums = list(range(1, 41))
            _s.SystemRandom().shuffle(nums)
            self.opts["keno"]["picks"] = sorted(nums[:n])
            self.last = None
            await self.show(inter)
        return cb

    async def keno_modal(self, inter):
        async def done(i, raw):
            nums = sorted({int(x) for x in re.findall(r"\d+", raw) if 1 <= int(x) <= 40})
            if not 1 <= len(nums) <= 10:
                return await self.show(i, ("Choisis 1 à 10 numéros entre 1 et 40", "err"))
            self.opts["keno"]["picks"] = nums
            self.last = None
            await self.show(i)
        await inter.response.send_modal(Ask(self, "Tes numéros Keno", [("Numéros (1 à 40)", "ex : 3 7 12 25 33", True)], done))

    # ======================= JEUX : partie =======================
    async def play(self, inter):
        key = self.arg
        p = self.playing()
        if not p:  # plus aucune crypto : écran explicatif + bouton d'achat
            self.screen, self.arg = "needcrypto", None
            return await self.show(inter)
        sym, price, qty_have, value = p
        if value < store.setting("min_bet"):
            return await self.show(inter, (f"Plus assez de {sym} · achète de la crypto dans le Wallet", "err"))
        self.clamp_bet(key)
        bet = self.bets[key]
        gid, err = store.start_game(self.uid, key, bet, sym, price)
        if err:
            return await self.show(inter, (err, "err"))
        rng = store.next_rng(self.uid)
        eng = ENGINES[key]
        footer = f"Partie #{gid} · mise en {sym} · nonce {rng.nonce} · provably fair"
        try:
            if eng.INSTANT:
                st, mult, label = eng.play(rng, self.opts[key])
                res = self.settle(gid, bet, mult, rng.nonce, label)
                self.last = (key, st, res, footer)
                await self.show(inter)
                await self.bigwin(key, res)
                return
            e = eng(bet, rng, self.opts[key])
            self.game = dict(key=key, e=e, gid=gid, nonce=rng.nonce, bet=bet, bet_total=bet, t0=None, sym=sym,
                             qty=bet / 100 / price, footer=footer)
            if key == "blackjack":
                r = e.opening()
                if r:
                    return await self.end_game(inter, *r)
            if key == "crash":
                e.recent = list(CRASH_RECENT)
                await self.show(inter)
                self.game["t0"] = time.monotonic()
                asyncio.create_task(self.crash_loop(self.game))
                return
            await self.show(inter)
        except Exception:
            self.game = None
            store.refund_game(gid)
            raise

    def settle(self, gid, bet, mult, nonce, label):
        payout = payout_of(bet, mult)
        r = store.settle_game(gid, payout, mult, nonce)
        if r is None:
            return None
        sym = r.get("sym") or ""
        return {"bet": r["bet"], "payout": r["payout"], "mult": mult, "label": f"{label} · {sym}".strip(" ·") if label else sym}

    async def end_game(self, inter, mult, label):
        g = self.game
        if g is None:
            return
        e = g["e"]
        e.over = True
        res = self.settle(g["gid"], g["bet_total"], mult, g["nonce"], label)
        if g["key"] == "crash":
            CRASH_RECENT.append(e.crash)
            del CRASH_RECENT[:-20]
        self.last = (g["key"], e.st, res, g["footer"])
        self.game = None
        await self.show(inter)
        await self.bigwin(g["key"], res)

    async def auto_end(self):
        """Fermeture / inactivité : on termine la partie au mieux pour le joueur."""
        g = self.game
        e = g["e"]
        k = g["key"]
        if k == "blackjack":
            m, lab = e.resolve()
            return await self.end_game(None, m, lab + " · auto")
        if k == "videopoker":
            m, lab = e.draw()
            return await self.end_game(None, m, lab)
        if k == "crash":
            return  # la boucle de vol se termine seule
        if e.progress and e.mult > 0:
            return await self.end_game(None, e.mult, f"Encaissé auto {xfmt(e.mult)}")
        store.refund_game(g["gid"])
        self.game = None

    async def bigwin(self, key, res):
        if not res or res["payout"] <= res["bet"] or res["mult"] < store.setting("bigwin_mult"):
            return
        em = discord.Embed(title=f"🏆 Gros gain — {GAMES[key][0]}", color=0xf1c40f, timestamp=datetime.now(timezone.utc),
                           description=f"{self.m.mention} gagne **{eur(res['payout'])}** avec {eur(res['bet'])} (**{xfmt(res['mult'])}**).")
        await send_log(self.guild, em)

    def build_live(self):
        g = self.game
        e, key = g["e"], g["key"]
        if key == "mines":
            for i in range(MINES_TILES):
                if i in e.revealed:
                    self.B(None, self.noop, GREEN, i // 5, emoji="💎", disabled=True)
                else:
                    self.B("⠀", self.mines_pick(i), GREY, i // 5)
            self.B(f"Encaisser {eur(payout_of(g['bet'], e.mult))}" if e.progress else "Encaisser", self.cashout, GREEN, 4, disabled=not e.progress)
            self.B("Case au hasard", self.mines_random, GREY, 4, emoji="🎲")
        elif key == "crash":
            self.B("Encaisser", self.crash_cash, GREEN, 0, emoji="💰")
        elif key == "hilo":
            self.B(f"Plus haut/égal {xfmt(e.mh())}", self.hilo(True), GREEN, 0, emoji="⬆️")
            self.B(f"Plus bas/égal {xfmt(e.ml())}", self.hilo(False), BLUE, 0, emoji="⬇️")
            self.B("Passer", self.hilo_skip, GREY, 1, emoji="⏭️")
            self.B(f"Encaisser {eur(payout_of(g['bet'], e.mult))}" if e.progress else "Encaisser", self.cashout, RED, 1, disabled=not e.progress)
        elif key == "dragon":
            for c in range(e.tiles):
                self.B(f"Case {c + 1}", self.dragon_pick(c), BLUE, 0)
            self.B(f"Encaisser {eur(payout_of(g['bet'], e.mult))}" if e.progress else "Encaisser", self.cashout, GREEN, 1, disabled=not e.progress)
        elif key in ("chicken", "pump"):
            self.B("Avancer" if key == "chicken" else "Gonfler", self.ladder_go, BLUE, 0, emoji="🐔" if key == "chicken" else "🎈")
            self.B(f"Encaisser {eur(payout_of(g['bet'], e.mult))}" if e.progress else "Encaisser", self.cashout, GREEN, 0, disabled=not e.progress)
        elif key == "blackjack":
            self.B("Tirer", self.bj_hit, BLUE, 0, emoji="🃏")
            self.B("Rester", self.bj_stand, GREEN, 0, emoji="✋")
            self.B("Doubler", self.bj_double, GREY, 0, emoji="✖️", disabled=len(e.player) != 2 or store.qty_of(self.uid, g["sym"]) < g["qty"] * (1 - 1e-9))
        elif key == "videopoker":
            for i in range(5):
                self.B(f"Garder {i + 1}", self.vp_toggle(i), GREEN if i in e.held else GREY, 0)
            self.B("Tirer", self.vp_draw, BLUE, 1, emoji="🎴")

    async def noop(self, inter):
        await safe_defer(inter)

    def live_ok(self):
        return self.game is not None and not self.game["e"].over

    async def cashout(self, inter):
        if not self.live_ok():
            return await safe_defer(inter)
        e = self.game["e"]
        if not e.progress:
            return await self.show(inter, ("Fais au moins un coup gagnant avant d'encaisser", "err"))
        await self.end_game(inter, e.mult, f"Encaissé {xfmt(e.mult)}")

    # --- mines ---
    def mines_pick(self, i):
        async def cb(inter):
            await self._mines(inter, i)
        return cb

    async def mines_random(self, inter):
        if not self.live_ok():
            return await safe_defer(inter)
        e = self.game["e"]
        hidden = [i for i in range(MINES_TILES) if i not in e.revealed]
        import secrets as _s
        await self._mines(inter, hidden[_s.randbelow(len(hidden))])

    async def _mines(self, inter, i):
        if not self.live_ok():
            return await safe_defer(inter)
        e = self.game["e"]
        r = e.pick(i)
        if r == "boom":
            return await self.end_game(inter, 0, "Boom !")
        if r == "win":
            return await self.end_game(inter, e.mult, "Grille nettoyée !")
        await self.show(inter)

    # --- crash ---
    async def crash_loop(self, g):
        e = g["e"]
        try:
            while True:
                await asyncio.sleep(CRASH_TICK)
                async with self.lock:
                    if self.game is not g or e.over:
                        return
                    m = e.growth(time.monotonic() - g["t0"])
                    if e.auto and e.auto < e.crash and m >= e.auto:
                        e.mult, e.cashed = e.auto, True
                        e.history.append(e.auto)
                        return await self.end_game(None, e.auto, f"Auto-cashout {xfmt(e.auto)}")
                    if m >= e.crash:
                        e.crashed = True
                        e.history.append(e.crash)
                        return await self.end_game(None, 0, f"Crash à {xfmt(e.crash)}")
                    e.mult = m
                    e.history.append(m)
                    await self.show(None)
        except Exception as ex:
            log.error(f"Boucle crash : {ex}\n{traceback.format_exc()}")
            async with self.lock:
                if self.game is g:
                    store.refund_game(g["gid"])
                    self.game = None
                    await self.show(None, ("Erreur pendant le vol · mise remboursée", "err"))

    async def crash_cash(self, inter):
        t = time.monotonic()
        if not self.live_ok() or self.game["key"] != "crash":
            return await safe_defer(inter)
        g = self.game
        e = g["e"]
        m = e.growth(t - g["t0"]) if g["t0"] else 1.0
        if m >= e.crash:
            e.crashed = True
            e.history.append(e.crash)
            return await self.end_game(inter, 0, f"Crash à {xfmt(e.crash)}")
        if m <= 1.0:
            return await self.show(inter, ("La fusée n'a pas encore décollé", "err"))
        e.mult, e.cashed = m, True
        e.history.append(m)
        await self.end_game(inter, m, f"Encaissé {xfmt(m)}")

    # --- hi-lo ---
    def hilo(self, high):
        async def cb(inter):
            if not self.live_ok():
                return await safe_defer(inter)
            e = self.game["e"]
            if not e.guess(high):
                return await self.end_game(inter, 0, "Raté")
            await self.show(inter)
        return cb

    async def hilo_skip(self, inter):
        if not self.live_ok():
            return await safe_defer(inter)
        if not self.game["e"].skip():
            return await self.show(inter, ("Trop de cartes passées", "err"))
        await self.show(inter)

    # --- dragon ---
    def dragon_pick(self, c):
        async def cb(inter):
            if not self.live_ok():
                return await safe_defer(inter)
            e = self.game["e"]
            r = e.climb(c)
            if r == "dead":
                return await self.end_game(inter, 0, "Dragon !")
            if r == "top":
                return await self.end_game(inter, e.mult, "Sommet atteint !")
            await self.show(inter)
        return cb

    # --- chicken / pump ---
    async def ladder_go(self, inter):
        if not self.live_ok():
            return await safe_defer(inter)
        e = self.game["e"]
        r = e.advance()
        if r == "dead":
            return await self.end_game(inter, 0, "Éclaté !" if self.game["key"] == "pump" else "Écrasé !")
        if r == "max":
            return await self.end_game(inter, e.mult, "Maximum atteint !")
        await self.show(inter)

    # --- blackjack ---
    async def bj_hit(self, inter):
        if not self.live_ok():
            return await safe_defer(inter)
        e = self.game["e"]
        v = e.hit()
        if v > 21:
            return await self.end_game(inter, *e.bust())
        if v == 21:
            return await self.end_game(inter, *e.resolve())
        await self.show(inter)

    async def bj_stand(self, inter):
        if not self.live_ok():
            return await safe_defer(inter)
        await self.end_game(inter, *self.game["e"].resolve())

    async def bj_double(self, inter):
        if not self.live_ok():
            return await safe_defer(inter)
        g = self.game
        e = g["e"]
        if len(e.player) != 2:
            return await self.show(inter, ("Double uniquement sur les 2 premières cartes", "err"))
        if not store.raise_bet(g["gid"], self.uid):
            return await self.show(inter, (f"Pas assez de {g['sym']} pour doubler", "err"))
        e.doubled = True
        g["bet_total"] = g["bet"] * 2
        if e.hit() > 21:
            return await self.end_game(inter, *e.bust())
        await self.end_game(inter, *e.resolve())

    # --- video poker ---
    def vp_toggle(self, i):
        async def cb(inter):
            if not self.live_ok():
                return await safe_defer(inter)
            self.game["e"].toggle(i)
            await self.show(inter)
        return cb

    async def vp_draw(self, inter):
        if not self.live_ok():
            return await safe_defer(inter)
        await self.end_game(inter, *self.game["e"].draw())


# ========================= OUVERTURE DU TÉLÉPHONE =========================
async def open_phone(ctx, screen="home", game=None, bet=None, toast=None, boot=False):
    old = PHONES.get(ctx.author.id)
    if old and not old.closed:
        if old.game:
            link = old.message.jump_url if old.message else ""
            return await ctx.reply(f"🎮 Tu as une partie en cours sur ton téléphone {link}", mention_author=False, delete_after=10)
        async with old.lock:
            await old.shutdown()
    ph = Phone(ctx.author, ctx.guild)
    PHONES[ctx.author.id] = ph
    if game:
        ph.open_game(game, bet)
    else:
        ph.screen = screen
    if boot:
        data = await asyncio.to_thread(SA.lock, ph.brand, ph.notifs())
        ph.message = await ctx.send(file=discord.File(BytesIO(data), filename="phone.webp"))
        await asyncio.sleep(0.6)
        await ph.show(None, toast)
        return
    ph.build()
    ph.rid += 1
    data = await asyncio.to_thread(ph.draw, toast)
    ph.message = await ctx.send(file=discord.File(BytesIO(data), filename="phone.webp"), view=ph)
    if toast:
        ph.clear_toast_later(ph.rid)


# ========================= CONTRÔLES GLOBAUX =========================
CHANNEL_EXEMPT = {"allow", "unallow", "allowed", "sys", "unsys", "owner", "unowner", "wl", "unwl", "prefix", "setlog", "config",
                  "addmoney", "removemoney", "setmoney", "resetbalance", "wipeeconomy", "additem", "delitem", "edititem",
                  "items", "commandes", "livrer", "rembourser", "setorders"}


def allowed_channels(gid):
    return {int(r["channel_id"]) for r in store.db.all("SELECT channel_id FROM allowed_channels WHERE guild_id = ?", (str(gid),))}


@bot.check
async def channel_ok(ctx):
    if ctx.guild is None:
        return False
    if ctx.command and ctx.command.name in CHANNEL_EXEMPT:
        return True
    if store.rank(ctx.author.id) >= 2:
        return True
    allowed = allowed_channels(ctx.guild.id)
    return not allowed or ctx.channel.id in allowed or getattr(ctx.channel, "parent_id", None) in allowed


async def gate(ctx, minimum):
    if store.rank(ctx.author.id) >= minimum:
        return True
    names = {4: "Buyer", 3: "Sys+", 2: "Owner+", 1: "Whitelist+"}
    await ctx.send(embed=err_embed("❌ Permission refusée", f"**{names.get(minimum, '')}** requis."), delete_after=8)
    return False


# ========================= COMMANDES JOUEURS =========================
@bot.command(name="phone", aliases=["tel", "telephone", "téléphone", "p", "menu", "home", "accueil"])
async def c_phone(ctx):
    await open_phone(ctx, "home", boot=True)


@bot.command(name="casino", aliases=["jeux", "games", "lobby"])
async def c_casino(ctx):
    await open_phone(ctx, "casino")


def _screen_cmd(screen):
    async def _cmd(ctx):
        await open_phone(ctx, screen)
    return _cmd


for _scr, _names in (("wallet", ["wallet", "portefeuille", "exodus"]), ("bank", ["banque", "bank", "bal", "balance", "solde"]),
                     ("crypto", ["marche", "marché", "crypto", "cryptos", "bourse"]), ("jobs", ["metiers", "métiers", "metier", "job", "jobs"]),
                     ("profile", ["profil", "profile", "stats"]), ("top", ["top", "lb", "leaderboard", "classement"]),
                     ("shop", ["boutique", "shop"]), ("fair", ["fair", "seeds", "provablyfair"]), ("help", ["aide", "help"])):
    bot.command(name=_names[0], aliases=_names[1:])(_screen_cmd(_scr))


@bot.command(name="daily", aliases=["quotidien"])
async def c_daily(ctx):
    amount, info = store.claim_daily(ctx.author.id)
    t = (f"Daily récupérée : {eur(amount, True)} (série {info})", "gold") if amount else (f"Daily déjà récupérée · reviens dans {duration(info - time.time())}", "err")
    await open_phone(ctx, "home", toast=t)


@bot.command(name="work", aliases=["travail", "travailler"])
async def c_work(ctx):
    pay, info = store.work(ctx.author.id)
    t = (f"Salaire versé en banque : {eur(pay, True)} · +{info} XP", "ok") if pay else (f"Encore {duration(info - time.time())} avant ton prochain service", "err")
    await open_phone(ctx, "jobs", toast=t)


def _game_cmd(key):
    async def _cmd(ctx, bet: str = None):
        amt = None
        if bet is not None:
            hold = store.holdings(ctx.author.id)
            best = max([int(h["qty"] * (feed.price(s) or 0) * 100) for s, h in hold.items()] or [0])
            amt = parse_eur(bet, best)
            if amt is None:
                return await ctx.reply("❌ Mise invalide. Exemples : `5`, `2,50`, `tout`, `25%`.", mention_author=False, delete_after=8)
        await open_phone(ctx, game=key, bet=amt)
    return _cmd


for _key in GAMES:
    bot.command(name=_key, aliases=ALIASES.get(_key, []))(_game_cmd(_key))


@bot.command(name="guide", aliases=["regles", "règles", "rules"])
async def c_guide(ctx, *, jeu: str = None):
    key = None
    if jeu:
        j = jeu.lower().strip().replace(" ", "").replace("-", "")
        if j in ("debutant", "débutant", "debut", "start", "tuto"):
            return await ctx.send(embed=beginner_embed(), view=GuideView(ctx.author.id))
        for k, v in GAMES.items():
            if j in (k, v[0].lower().replace(" ", "").replace("-", "")) or j in ALIASES.get(k, []):
                key = k
    view = GuideView(ctx.author.id)
    await ctx.send(embed=guide_embed(key) if key else guide_home_embed(), view=view)


@bot.command(name="debutant", aliases=["débutant", "tuto", "tutoriel", "start"])
async def c_beginner(ctx):
    await ctx.send(embed=beginner_embed(), view=GuideView(ctx.author.id))


@bot.command(name="verify", aliases=["verifier"])
async def c_verify(ctx, server: str = None, client: str = None, nonce: int = None):
    if not server or client is None or nonce is None:
        return await ctx.send(embed=err_embed("Usage", f"`{prefix()}verify <server_seed> <client_seed> <nonce>`"))
    f = C.FairRNG(server, client, nonce).random()
    em = discord.Embed(title="🔍 Vérification provably fair", description=f"Hash du seed serveur : `{sha256(server)}`", color=0x0E8A8A)
    em.add_field(name="1er tirage", value=f"`{f:.10f}`", inline=False)
    em.add_field(name="Dice", value=f"{min(10000, int(f * 10001)) / 100:.2f}")
    em.add_field(name="Limbo / Crash", value=f"x{C.crash_point_from(f):.2f}")
    em.add_field(name="Coinflip", value="Pile" if f < 0.5 else "Face")
    em.add_field(name="Roulette", value=str(min(36, int(f * 37))))
    await ctx.send(embed=em)


# ========================= COMMANDES STAFF =========================
async def _target_amount(ctx, who, raw, allow_zero=False):
    m = resolve_member(ctx.guild, who) if who else None
    if m is None:
        await ctx.send(embed=err_embed("Utilisateur introuvable", "Mention, ID ou nom d'utilisateur."))
        return None, None
    if allow_zero and str(raw).strip() == "0":
        return m, 0
    amt = parse_eur(raw)
    if amt is None:
        await ctx.send(embed=err_embed("Montant invalide", "Exemples : 25 · 12,50 · 1k"))
        return None, None
    return m, amt


async def admin_log(ctx, title, desc, color=0xfaa61a):
    em = discord.Embed(title=f"📋 {title}", description=desc, color=color, timestamp=datetime.now(timezone.utc))
    em.add_field(name="Par", value=f"{ctx.author.mention} ({ctx.author.id})")
    await send_log(ctx.guild, em)


@bot.command(name="addmoney", aliases=["addcash"])
async def c_addmoney(ctx, who: str = None, amount: str = None):
    if not await gate(ctx, 2):
        return
    m, amt = await _target_amount(ctx, who, amount)
    if m is None:
        return
    store.add_bank(m.id, amt, "Crédit staff")
    await ctx.send(embed=ok_embed("✅ Argent ajouté", f"{m.mention} : **+{eur(amt)}** · banque {eur(store.user(m.id)['bank'])}"))
    await admin_log(ctx, "Argent ajouté", f"{m.mention} : +{eur(amt)}", 0x43b581)


@bot.command(name="removemoney", aliases=["removecash"])
async def c_removemoney(ctx, who: str = None, amount: str = None):
    if not await gate(ctx, 2):
        return
    m, amt = await _target_amount(ctx, who, amount)
    if m is None:
        return
    bal = store.user(m.id)["bank"]
    store.set_bank(m.id, bal - amt)
    store.log(m.id, "bank", "Retrait staff", -min(bal, amt))
    await ctx.send(embed=ok_embed("✅ Argent retiré", f"{m.mention} : **-{eur(min(bal, amt))}** · banque {eur(store.user(m.id)['bank'])}"))
    await admin_log(ctx, "Argent retiré", f"{m.mention} : -{eur(min(bal, amt))}")


@bot.command(name="setmoney", aliases=["setcash"])
async def c_setmoney(ctx, who: str = None, amount: str = None):
    if not await gate(ctx, 2):
        return
    m, amt = await _target_amount(ctx, who, amount, allow_zero=True)
    if m is None:
        return
    store.set_bank(m.id, amt)
    await ctx.send(embed=ok_embed("✅ Banque définie", f"{m.mention} : **{eur(amt)}**"))
    await admin_log(ctx, "Banque définie", f"{m.mention} : {eur(amt)}")


@bot.command(name="resetbalance", aliases=["resetbal"])
async def c_reset(ctx, *, who: str = None):
    if not await gate(ctx, 2):
        return
    m = resolve_member(ctx.guild, who)
    if m is None:
        return await ctx.send(embed=err_embed("Utilisateur introuvable"))
    store.db.x("UPDATE users SET cash = 0, bank = ?, savings = 0 WHERE user_id = ?", (store.setting("start_bank"), str(m.id)))
    store.db.x("DELETE FROM holdings WHERE user_id = ?", (str(m.id),))
    await ctx.send(embed=ok_embed("✅ Comptes réinitialisés", f"{m.mention} : banque à {eur(store.setting('start_bank'))}, épargne et crypto vidées."))
    await admin_log(ctx, "Comptes réinitialisés", m.mention)


class WipeConfirm(discord.ui.View):
    def __init__(self, author_id):
        super().__init__(timeout=60)
        self.author_id = author_id

    async def interaction_check(self, inter):
        return inter.user.id == self.author_id

    @discord.ui.button(label="TOUT EFFACER", emoji="⚠️", style=discord.ButtonStyle.danger)
    async def ok(self, inter, _b):
        self.stop()
        n = store.db.one("SELECT COUNT(*) AS n FROM users")["n"]
        store.db.x("UPDATE users SET cash = 0, bank = ?, savings = 0, wagered = 0, won = 0, profit = 0, games = 0, biggest_win = 0, "
                   "best_mult = 0, rakeback = 0, streak = 0", (store.setting("start_bank"),))
        for t in ("bets", "ledger", "holdings"):
            store.db.x(f"DELETE FROM {t}")
        await inter.response.edit_message(embed=ok_embed("✅ Économie remise à zéro", f"{n} compte(s)."), view=None)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def no(self, inter, _b):
        self.stop()
        await inter.response.edit_message(embed=err_embed("Annulé"), view=None)


@bot.command(name="wipeeconomy", aliases=["resetall"])
async def c_wipe(ctx):
    if not await gate(ctx, 4):
        return
    await ctx.send(embed=err_embed("⚠️ Confirmation", "Remettre **tous** les comptes à zéro (wallet, banque, crypto, stats) ?"), view=WipeConfirm(ctx.author.id))


@bot.command(name="allow")
async def c_allow(ctx, channel: discord.TextChannel = None):
    if not await gate(ctx, 2):
        return
    channel = channel or ctx.channel
    store.db.x("INSERT OR IGNORE INTO allowed_channels VALUES (?, ?)", (str(ctx.guild.id), str(channel.id)))
    await ctx.send(embed=ok_embed("✅ Salon autorisé", f"Le casino est ouvert dans {channel.mention}."))


@bot.command(name="unallow", aliases=["disallow"])
async def c_unallow(ctx, channel: discord.TextChannel = None):
    if not await gate(ctx, 2):
        return
    channel = channel or ctx.channel
    store.db.x("DELETE FROM allowed_channels WHERE guild_id = ? AND channel_id = ?", (str(ctx.guild.id), str(channel.id)))
    left = allowed_channels(ctx.guild.id)
    await ctx.send(embed=ok_embed("🚫 Salon retiré", f"{channel.mention} n'est plus autorisé." + ("" if left else "\nAucun salon configuré : casino ouvert partout.")))


@bot.command(name="allowed", aliases=["salons"])
async def c_allowed(ctx):
    if not await gate(ctx, 2):
        return
    ids = allowed_channels(ctx.guild.id)
    await ctx.send(embed=ok_embed("📺 Salons du casino", ", ".join(f"<#{c}>" for c in ids) if ids else "Aucun salon configuré : ouvert partout."))


# ========================= BOUTIQUE (staff) =========================
KIND_HELP = {
    "role": "Le rôle est donné **automatiquement** au joueur dès l'achat.",
    "nitro": "Le joueur passe commande : elle arrive dans le salon des commandes, un membre du staff lui envoie le Nitro "
             "(lien cadeau en MP) puis clique sur **Livré**.",
    "custom": "N'importe quelle récompense (carte cadeau, objet, service…) : commande livrée à la main par le staff, comme le Nitro.",
}
STATUS_TXT = {"pending": "⏳ À livrer", "delivered": "✅ Livrée", "refunded": "↩️ Remboursée"}
STATUS_COLOR = {"pending": 0xF5C451, "delivered": 0x2BD67B, "refunded": 0xFF5A66}


def orders_channel(guild):
    cid = store.cfg(f"orders_{guild.id}")
    ch = guild.get_channel(int(cid)) if cid else None
    if ch is None:
        r = store.db.one("SELECT channel_id FROM log_channels WHERE guild_id = ?", (str(guild.id),))
        ch = guild.get_channel(int(r["channel_id"])) if r else None
    return ch


def order_embed(o, member=None, status=None):
    kind = C.ITEM_KINDS.get(o["kind"], C.ITEM_KINDS["custom"])
    em = discord.Embed(title=f"🛒 Commande #{o['id']} · {o['name']}", color=STATUS_COLOR.get(o["status"], 0x2b2d31),
                       timestamp=datetime.fromtimestamp(o["ts"], timezone.utc))
    who = member.mention if member else f"<@{o['user_id']}>"
    em.add_field(name="Joueur", value=f"{who} ({o['user_id']})", inline=True)
    em.add_field(name="Type", value=kind[0], inline=True)
    em.add_field(name="Prix payé", value=eur(o["price"]), inline=True)
    em.add_field(name="Statut", value=status or STATUS_TXT.get(o["status"], o["status"]), inline=False)
    if o["status"] == "pending":
        em.description = "Livre la récompense au joueur, puis clique sur **Livré**. **Rembourser** lui rend son argent."
    return em


class OrderButton(discord.ui.DynamicItem[discord.ui.Button], template=r"order:(?P<act>done|refund):(?P<oid>\d+)"):
    """Boutons persistants (fonctionnent même après un redémarrage du bot)."""

    def __init__(self, act, oid):
        label, style, emoji = ("Livré", GREEN, "✅") if act == "done" else ("Rembourser", RED, "↩️")
        super().__init__(discord.ui.Button(label=label, style=style, emoji=emoji, custom_id=f"order:{act}:{oid}"))
        self.act, self.oid = act, int(oid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["act"], int(match["oid"]))

    async def callback(self, inter):
        if store.rank(inter.user.id) < 2:
            return await inter.response.send_message("Réservé au staff (Owner+).", ephemeral=True)
        o = store.order(self.oid)
        if not o or o["status"] != "pending":
            await inter.response.edit_message(embed=order_embed(o) if o else None, view=None)
            return
        if self.act == "done":
            store.deliver_order(self.oid, inter.user.id)
            status, dm = f"✅ Livrée par {inter.user.mention}", f"✅ Ta commande **{o['name']}** (#{o['id']}) a été livrée. Merci !"
        else:
            store.refund_order(self.oid, inter.user.id)
            status, dm = f"↩️ Remboursée par {inter.user.mention}", f"↩️ Ta commande **{o['name']}** (#{o['id']}) a été annulée : {eur(o['price'])} remboursés sur ton wallet."
        member = inter.guild.get_member(int(o["user_id"])) if inter.guild else None
        await inter.response.edit_message(embed=order_embed(store.order(self.oid), member, status), view=None)
        if member:
            try:
                await member.send(dm)
            except discord.HTTPException:
                pass


def order_view(oid):
    v = discord.ui.View(timeout=None)
    v.add_item(OrderButton("done", oid))
    v.add_item(OrderButton("refund", oid))
    return v


async def post_order(guild, order, member):
    ch = orders_channel(guild)
    if ch is None:
        log.warning(f"Commande #{order['id']} : aucun salon de commandes ni de logs configuré ({prefix()}setorders).")
        return
    try:
        await ch.send(embed=order_embed(order, member), view=order_view(order["id"]),
                      allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as e:
        log.warning(f"Commande #{order['id']} non publiée : {e}")


class ItemTextModal(discord.ui.Modal, title="Nom et description"):
    def __init__(self, editor):
        super().__init__()
        self.ed = editor
        d = editor.d
        self.name = discord.ui.TextInput(label="Nom de l'article", default=d.get("name") or None, max_length=60, placeholder="ex : Nitro Boost 1 mois")
        self.desc = discord.ui.TextInput(label="Description (optionnelle)", default=d.get("description") or None, required=False,
                                         max_length=120, style=discord.TextStyle.paragraph, placeholder="ex : Livré en cadeau sous 24 h")
        self.add_item(self.name)
        self.add_item(self.desc)

    async def on_submit(self, inter):
        self.ed.d["name"] = str(self.name.value).strip()
        self.ed.d["description"] = str(self.desc.value).strip()
        await self.ed.refresh(inter)


class ItemPriceModal(discord.ui.Modal, title="Prix, stock et limite"):
    def __init__(self, editor):
        super().__init__()
        self.ed = editor
        d = editor.d
        self.price = discord.ui.TextInput(label="Prix en euros virtuels", default=f"{d['price'] / 100:g}".replace(".", ",") if d.get("price") else None,
                                          placeholder="ex : 500 · 12,50 · 2k", max_length=15)
        self.stock = discord.ui.TextInput(label="Stock (vide = illimité)", required=False, max_length=6,
                                          default=str(d["stock"]) if d.get("stock", -1) >= 0 else None, placeholder="ex : 3")
        self.limit = discord.ui.TextInput(label="Limite par joueur (vide = aucune)", required=False, max_length=4,
                                          default=str(d["per_user"]) if d.get("per_user") else None, placeholder="ex : 1")
        for t in (self.price, self.stock, self.limit):
            self.add_item(t)

    async def on_submit(self, inter):
        p = parse_eur(str(self.price.value))
        s, lim = str(self.stock.value).strip(), str(self.limit.value).strip()
        if p is None or (s and not s.isdigit()) or (lim and not lim.isdigit()):
            return await inter.response.send_message("❌ Prix, stock ou limite invalide (nombres entiers pour le stock et la limite).", ephemeral=True)
        self.ed.d.update(price=p, stock=int(s) if s else -1, per_user=int(lim) if lim else 0)
        await self.ed.refresh(inter)


class ItemEditor(discord.ui.View):
    """Panneau de création / modification d'un article de la boutique."""

    def __init__(self, author, guild, draft):
        super().__init__(timeout=900)
        self.author, self.guild, self.d = author, guild, draft
        self.warning = None
        self.rebuild()

    async def interaction_check(self, inter):
        if inter.user.id != self.author.id:
            await inter.response.send_message("Ce panneau n'est pas à toi.", ephemeral=True)
            return False
        return True

    def missing(self):
        out = []
        if not self.d.get("name"):
            out.append("le nom")
        if not self.d.get("price"):
            out.append("le prix")
        if self.d["kind"] == "role" and not self.d.get("role_id"):
            out.append("le rôle à donner")
        return out

    def embed(self):
        d = self.d
        label, color, _ic, _auto = C.ITEM_KINDS[d["kind"]]
        title = f"✏️ Modifier l'article #{d['item_id']}" if d.get("item_id") else "🛒 Nouvel article"
        em = discord.Embed(title=title, color=int(color.lstrip("#"), 16),
                           description="Configure l'article avec les menus et les boutons ci-dessous, puis clique sur **Enregistrer**.")
        em.add_field(name="Nom", value=d.get("name") or "*à définir*", inline=True)
        em.add_field(name="Prix", value=eur(d["price"]) if d.get("price") else "*à définir*", inline=True)
        em.add_field(name="Type", value=label, inline=True)
        em.add_field(name="Description", value=d.get("description") or "*aucune*", inline=False)
        if d["kind"] == "role":
            em.add_field(name="Rôle donné", value=f"<@&{d['role_id']}>" if d.get("role_id") else "*à choisir dans le menu*", inline=True)
        else:
            ch = orders_channel(self.guild)
            em.add_field(name="Salon des commandes", value=ch.mention if ch else "⚠️ *aucun : choisis-en un dans le menu*", inline=True)
        em.add_field(name="Stock", value="Illimité" if d.get("stock", -1) < 0 else str(d["stock"]), inline=True)
        em.add_field(name="Limite par joueur", value=str(d["per_user"]) if d.get("per_user") else "Aucune", inline=True)
        em.add_field(name="Livraison", value=KIND_HELP[d["kind"]], inline=False)
        if self.warning:
            em.add_field(name="⚠️ Attention", value=self.warning, inline=False)
        miss = self.missing()
        em.set_footer(text=("Il manque : " + ", ".join(miss)) if miss else "Tout est prêt : clique sur Enregistrer.")
        return em

    def rebuild(self):
        self.clear_items()
        kind_sel = discord.ui.Select(placeholder="Type d'article…", row=0, options=[
            discord.SelectOption(label="Rôle", value="role", emoji="👑", description="Donné automatiquement à l'achat", default=self.d["kind"] == "role"),
            discord.SelectOption(label="Nitro / Nitro Boost", value="nitro", emoji="💎", description="Livré par le staff", default=self.d["kind"] == "nitro"),
            discord.SelectOption(label="Autre récompense", value="custom", emoji="🎁", description="Carte cadeau, objet, service… livré par le staff",
                                 default=self.d["kind"] == "custom")])

        async def on_kind(inter):
            self.d["kind"] = kind_sel.values[0]
            self.warning = None
            await self.refresh(inter)
        kind_sel.callback = on_kind
        self.add_item(kind_sel)

        if self.d["kind"] == "role":
            rs = discord.ui.RoleSelect(placeholder="Rôle à donner à l'achat…", row=1)

            async def on_role(inter):
                role = rs.values[0]
                me = self.guild.me
                if role.managed or role.is_default():
                    self.warning = "Ce rôle ne peut pas être donné (rôle géré par Discord ou @everyone)."
                    return await self.refresh(inter)
                self.warning = None
                if me and role >= me.top_role:
                    self.warning = f"Mon rôle est plus bas que {role.mention} : place mon rôle au-dessus, sinon l'achat sera remboursé."
                self.d["role_id"] = role.id
                await self.refresh(inter)
            rs.callback = on_role
            self.add_item(rs)
        else:
            cs = discord.ui.ChannelSelect(placeholder="Salon où arrivent les commandes à livrer…", row=1,
                                          channel_types=[discord.ChannelType.text])

            async def on_channel(inter):
                store.set_cfg(f"orders_{self.guild.id}", cs.values[0].id)
                await self.refresh(inter)
            cs.callback = on_channel
            self.add_item(cs)

        def btn(label, emoji, style, row, cb, disabled=False):
            b = discord.ui.Button(label=label, emoji=emoji, style=style, row=row, disabled=disabled)
            b.callback = cb
            self.add_item(b)

        async def open_text(inter):
            await inter.response.send_modal(ItemTextModal(self))

        async def open_price(inter):
            await inter.response.send_modal(ItemPriceModal(self))

        async def save(inter):
            if self.missing():
                return await inter.response.send_message("Il manque : " + ", ".join(self.missing()), ephemeral=True)
            iid = store.save_item(self.d)
            self.stop()
            em = discord.Embed(title=f"✅ Article #{iid} enregistré", color=0x43b581,
                               description=f"**{self.d['name']}** · {eur(self.d['price'])} · {C.ITEM_KINDS[self.d['kind']][0]}\n"
                                           f"Il est en vente dans l'app Boutique du téléphone.")
            await inter.response.edit_message(embed=em, view=None)
            em2 = discord.Embed(title="📋 Boutique : article enregistré", color=0x43b581, timestamp=datetime.now(timezone.utc),
                                description=f"#{iid} **{self.d['name']}** · {eur(self.d['price'])} · par {inter.user.mention}")
            await send_log(self.guild, em2)

        async def cancel(inter):
            self.stop()
            await inter.response.edit_message(embed=err_embed("Création annulée"), view=None)

        btn("Nom et description", "✏️", BLUE, 2, open_text)
        btn("Prix, stock et limite", "💶", BLUE, 2, open_price)
        btn("Enregistrer", "✅", GREEN, 3, save, disabled=bool(self.missing()))
        btn("Annuler", None, GREY, 3, cancel)

    async def refresh(self, inter):
        self.rebuild()
        await inter.response.edit_message(embed=self.embed(), view=self)


@bot.command(name="additem", aliases=["ajouterarticle"])
async def c_additem(ctx):
    if not await gate(ctx, 2):
        return
    ed = ItemEditor(ctx.author, ctx.guild, {"kind": "role", "stock": -1, "per_user": 0})
    await ctx.send(embed=ed.embed(), view=ed)


@bot.command(name="edititem", aliases=["modifierarticle"])
async def c_edititem(ctx, item_id: int = None):
    if not await gate(ctx, 2):
        return
    it = store.shop_item(item_id) if item_id else None
    if not it:
        return await ctx.send(embed=err_embed("Article introuvable", f"Usage : `{prefix()}edititem <id>` · liste avec `{prefix()}items`"))
    d = {"item_id": it["item_id"], "name": it["name"], "description": it["description"] or "", "price": it["price"], "kind": it["kind"],
         "role_id": int(it["role_id"]) if it["role_id"] else None, "stock": it["stock"], "per_user": it["per_user"]}
    ed = ItemEditor(ctx.author, ctx.guild, d)
    await ctx.send(embed=ed.embed(), view=ed)


@bot.command(name="delitem", aliases=["removeitem"])
async def c_delitem(ctx, item_id: int = None):
    if not await gate(ctx, 2):
        return
    n = store.db.x("UPDATE shop SET active = 0 WHERE item_id = ? AND active = 1", (item_id,)).rowcount
    await ctx.send(embed=ok_embed("✅ Article retiré de la vente", "Les commandes déjà passées restent visibles.") if n else err_embed("Article introuvable"))


@bot.command(name="items", aliases=["articles"])
async def c_items(ctx):
    if not await gate(ctx, 2):
        return
    items = store.shop_items()
    em = discord.Embed(title="🛒 Articles en vente", color=0xD6336C,
                       description=f"`{prefix()}additem` créer · `{prefix()}edititem <id>` modifier · `{prefix()}delitem <id>` retirer")
    for i in items[:25]:
        stock = "illimité" if i["stock"] < 0 else f"{max(0, i['stock'] - i['sold'])}/{i['stock']}"
        em.add_field(name=f"#{i['item_id']} · {i['name']}", inline=False,
                     value=f"{eur(i['price'])} · {C.ITEM_KINDS.get(i['kind'], C.ITEM_KINDS['custom'])[0]} · stock {stock} · {i['sold']} vendu(s)"
                           + (f" · max {i['per_user']}/joueur" if i["per_user"] else ""))
    if not items:
        em.add_field(name="Aucun article", value=f"Crée le premier avec `{prefix()}additem`.")
    await ctx.send(embed=em)


@bot.command(name="commandes", aliases=["orders"])
async def c_orders(ctx):
    if not await gate(ctx, 2):
        return
    rows = store.pending_orders(ctx.guild.id)
    em = discord.Embed(title=f"⏳ Commandes à livrer ({len(rows)})", color=0xF5C451,
                       description=f"`{prefix()}livrer <n°>` ou `{prefix()}rembourser <n°>`, ou les boutons dans le salon des commandes.")
    for o in rows:
        em.add_field(name=f"#{o['id']} · {o['name']}", value=f"<@{o['user_id']}> · {eur(o['price'])} · <t:{o['ts']}:R>", inline=False)
    await ctx.send(embed=em, allowed_mentions=discord.AllowedMentions.none())


async def _close_order(ctx, oid, act):
    if not await gate(ctx, 2):
        return
    o = store.order(oid) if oid else None
    if not o or o["status"] != "pending":
        return await ctx.send(embed=err_embed("Commande introuvable ou déjà traitée"))
    if act == "done":
        store.deliver_order(oid, ctx.author.id)
    else:
        store.refund_order(oid, ctx.author.id)
    o = store.order(oid)
    await ctx.send(embed=order_embed(o, None, f"{STATUS_TXT[o['status']]} par {ctx.author.mention}"), allowed_mentions=discord.AllowedMentions.none())
    m = ctx.guild.get_member(int(o["user_id"]))
    if m:
        try:
            await m.send(f"Ta commande **{o['name']}** (#{o['id']}) : {STATUS_TXT[o['status']].lower()}.")
        except discord.HTTPException:
            pass


@bot.command(name="livrer", aliases=["deliver"])
async def c_deliver(ctx, oid: int = None):
    await _close_order(ctx, oid, "done")


@bot.command(name="rembourser", aliases=["refund"])
async def c_refund(ctx, oid: int = None):
    await _close_order(ctx, oid, "refund")


@bot.command(name="setorders")
async def c_setorders(ctx, channel: discord.TextChannel = None):
    if not await gate(ctx, 3):
        return
    if not channel:
        return await ctx.send(embed=err_embed("Mentionne un salon", f"`{prefix()}setorders #commandes`"))
    store.set_cfg(f"orders_{ctx.guild.id}", channel.id)
    await ctx.send(embed=ok_embed("✅ Salon des commandes", f"Les commandes Nitro et récompenses arrivent dans {channel.mention}."))


@bot.command(name="config", aliases=["settings"])
async def c_config(ctx, key: str = None, value: str = None):
    if not await gate(ctx, 3):
        return
    if key and value is not None:
        if key not in C.DEFAULT_SETTINGS or not value.isdigit():
            return await ctx.send(embed=err_embed("Réglage invalide", f"Clés : {', '.join(C.DEFAULT_SETTINGS)} · valeur entière."))
        store.set_cfg(f"set_{key}", int(value))
    em = discord.Embed(title="⚙️ Configuration", description=f"Modifier : `{prefix()}config <clé> <valeur>` (montants en centimes)", color=0x2b2d31)
    for k, label in C.SETTINGS_META.items():
        em.add_field(name=k, value=f"{label}\n**{store.setting(k)}**", inline=True)
    await ctx.send(embed=em)


@bot.command(name="prefix")
async def c_prefix(ctx, new: str = None):
    if not await gate(ctx, 4):
        return
    if new:
        store.set_cfg("prefix", new[:5])
    await ctx.send(embed=ok_embed("Prefix", f"Prefix actuel : `{prefix()}`"))


@bot.command(name="setlog")
async def c_setlog(ctx, channel: discord.TextChannel = None):
    if not await gate(ctx, 4):
        return
    if not channel:
        return await ctx.send(embed=err_embed("Mentionne un salon"))
    store.db.x("INSERT OR REPLACE INTO log_channels VALUES (?, ?)", (str(ctx.guild.id), str(channel.id)))
    await ctx.send(embed=ok_embed("✅ Salon de logs", f"Gros gains, virements et actions staff dans {channel.mention}."))


async def _rank_cmd(ctx, who, level, minimum, label, add=True):
    if not await gate(ctx, minimum):
        return
    if who is None:
        ids = [u for u, r in store.ranks.items() if r == level]
        return await ctx.send(embed=ok_embed(f"📋 {label} ({len(ids)})", "\n".join(f"<@{u}>" for u in ids)[:4000] or "Aucun."))
    m = resolve_member(ctx.guild, who)
    if m is None:
        return await ctx.send(embed=err_embed("Utilisateur introuvable"))
    if add:
        if store.rank(m.id) >= level:
            return await ctx.send(embed=err_embed("Déjà ce rang (ou supérieur)"))
        store.set_rank(m.id, level)
    else:
        if store.rank(m.id) != level:
            return await ctx.send(embed=err_embed(f"{m.display_name} n'est pas {label}"))
        store.set_rank(m.id, 0)
    await ctx.send(embed=ok_embed(f"✅ {label} {'ajouté' if add else 'retiré'}", m.mention))
    await admin_log(ctx, f"{label} {'ajouté' if add else 'retiré'}", m.mention)


@bot.command(name="sys")
async def c_sys(ctx, *, who: str = None):
    await _rank_cmd(ctx, who, 3, 4, "Sys")


@bot.command(name="unsys")
async def c_unsys(ctx, *, who: str = None):
    await _rank_cmd(ctx, who, 3, 4, "Sys", add=False)


@bot.command(name="owner")
async def c_owner(ctx, *, who: str = None):
    await _rank_cmd(ctx, who, 2, 3, "Owner")


@bot.command(name="unowner")
async def c_unowner(ctx, *, who: str = None):
    await _rank_cmd(ctx, who, 2, 3, "Owner", add=False)


@bot.command(name="wl")
async def c_wl(ctx, *, who: str = None):
    await _rank_cmd(ctx, who, 1, 2, "Whitelist")


@bot.command(name="unwl")
async def c_unwl(ctx, *, who: str = None):
    await _rank_cmd(ctx, who, 1, 2, "Whitelist", add=False)


# ========================= EVENTS =========================
_ready = {"done": False}


async def _setup_hook():
    bot.add_dynamic_items(OrderButton)  # boutons Livré / Rembourser actifs après redémarrage


bot.setup_hook = _setup_hook


@bot.event
async def on_ready():
    log.info(f"Connecté : {bot.user} · prefix {prefix()} · {len(bot.guilds)} serveur(s)")
    if not _ready["done"]:
        _ready["done"] = True
        n = store.refund_all_active()
        if n:
            log.info(f"{n} partie(s) interrompue(s) par le redémarrage : mises remboursées.")
        feed.start()
        await asyncio.to_thread(lambda: SA.lock("Boot", []))  # préchauffe polices et fonds d'écran
    try:
        await bot.change_presence(activity=discord.Game(name=f"{prefix()}phone · 📱"))
    except discord.HTTPException:
        pass


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandInvokeError):
        error = error.original
    if isinstance(error, (commands.CommandNotFound, commands.CheckFailure)):
        return
    if isinstance(error, (commands.BadArgument, commands.MissingRequiredArgument)):
        return await ctx.send(embed=err_embed("Argument invalide", str(error)[:300]), delete_after=10)
    log.error(f"Commande {ctx.command} : {error}\n" + "".join(traceback.format_exception(type(error), error, error.__traceback__)))
    try:
        await ctx.send(embed=err_embed("Erreur interne", "Une erreur inattendue est survenue."), delete_after=10)
    except discord.HTTPException:
        pass


if __name__ == "__main__":
    bot.run(TOKEN, log_handler=None)
