"""
screens_apps.py — écrans "système" du téléphone : verrouillage, accueil, apps.
Chaque fonction renvoie les octets de l'image (WebP).
"""
from gfx import (W, H, BG, SURF, SURF2, LINE, TXT, MUT, DIM, GOLD, GREEN, GREEN_BG, GREEN_LINE, RED_SOFT, BLUE,
                 phone, finish, app_header, pill, card, app_icon, avatar, sparkline, progress, toast, stat_boxes,
                 footer_note, text_w, eur, eur_short, now_paris, JOURS, MOIS, mix)

APPS = [  # clé, nom, couleur, icône
    ("casino", "Casino", "#7C4DFF", "dice"), ("wallet", "Wallet", "#E0A526", "wallet"),
    ("bank", "Banque", "#2F6BFF", "bank"), ("crypto", "Crypto", "#17A660", "chart"),
    ("jobs", "Métiers", "#D9573B", "job"), ("top", "Top", "#C08A1E", "trophy"),
    ("shop", "Boutique", "#D6336C", "bag"), ("daily", "Daily", "#B8860B", "gift"),
    ("fair", "Fair", "#0E8A8A", "shield"), ("guide", "Guide", "#5A6578", "book"),
    ("profile", "Profil", "#3E4A5E", "user"), ("help", "Aide", "#3B4252", "help"),
]
APP_BY_KEY = {a[0]: a for a in APPS}


def _toast(cv, t):
    if t:
        toast(cv, t[0], t[1])


# =============== VERROUILLAGE ===============
def lock(brand, notifs, t=None):
    cv = phone("lock")
    n = now_paris()
    cv.icon("lock", W / 2 - 9, 74, 18, TXT, 2)
    cv.text(W / 2, 104, f"{JOURS[n.weekday()]} {n.day} {MOIS[n.month - 1]}", 17, "s", "#D5D9E2", anchor="c")
    cv.text(W / 2, 122, n.strftime("%H:%M"), 92, "s", TXT, anchor="c")
    y = 290
    for app, color, icon, when, text in notifs[:4]:
        cv.rr(16, y, W - 32, 70, 22, "#1E222C", 200)
        cv.rr(16.5, y + 0.5, W - 33, 69, 22, "#FFFFFF", 14, stroke=1)
        cv.rr(30, y + 16, 38, 38, 10, color)
        cv.icon(icon, 39, y + 25, 20, "#FFFFFF", 2.2)
        cv.text(80, y + 15, app, 14, "s", TXT, maxw=180)
        cv.text(W - 30, y + 16, when, 11.5, "r", "#A9B1BF", anchor="r")
        cv.text(80, y + 36, text, 13.5, "r", "#D5D9E2", maxw=W - 112)
        y += 80
    for x, ic in ((46, "flash"), (W - 96, "camera")):
        cv.circ(x + 25, H - 74, 25, "#1E222C", 210)
        cv.icon(ic, x + 14, H - 85, 22, TXT, 2)
    cv.text(W / 2, H - 74, "Appuie sur Déverrouiller", 13, "m", "#D5D9E2", anchor="c", valign="mid")
    _toast(cv, t)
    return finish(cv)


# =============== ACCUEIL ===============
def home(d, t=None):
    """d: brand, cash, bank, savings, crypto, total, vip, vip_color, daily_ready, streak, daily_in, coin(sym, change, spark)"""
    cv = phone("home")
    # widget solde
    x, y, w = 18, 62, W - 36
    cv.rr(x, y, w, 132, 24, "#161A23", 215)
    cv.rr(x + 0.5, y + 0.5, w - 1, 131, 24, "#FFFFFF", 16, stroke=1)
    cv.text(x + 18, y + 16, "Solde total", 13, "m", MUT)
    pill(cv, x + w - 16, y + 13, f"VIP {d['vip']}", d["vip_color"], BG, 11, "b", anchor="r")
    cv.text(x + 18, y + 34, eur(d["total"]), 36, "b", TXT, maxw=w - 36)
    cx = x + 18
    for label, v, c in (("Wallet", d["cash"], TXT), ("Banque", d["bank"] + d["savings"], TXT), ("Crypto", d["crypto"], GREEN)):
        cv.text(cx, y + 96, label, 12, "m", MUT)
        cv.text(cx, y + 110, eur_short(v), 13, "b", c)
        cx += (w - 36) / 3
    # petits widgets
    y2 = y + 146
    hw = (w - 12) / 2
    cv.rr(x, y2, hw, 92, 22, "#161A23", 215)
    cv.text(x + 16, y2 + 14, "Daily", 12, "m", MUT)
    if d["daily_ready"]:
        cv.text(x + 16, y2 + 32, "Prête", 19, "b", GOLD)
    else:
        cv.text(x + 16, y2 + 32, d["daily_in"], 19, "b", TXT, maxw=hw - 30)
    cv.text(x + 16, y2 + 62, f"Série de {d['streak']} jour{'s' if d['streak'] > 1 else ''}", 12, "r", MUT)
    bx = x + hw + 12
    cv.rr(bx, y2, hw, 92, 22, "#161A23", 215)
    coin = d.get("coin")
    if coin:
        up = coin["change"] >= 0
        c = GREEN if up else RED_SOFT
        cv.text(bx + 16, y2 + 14, coin["sym"], 12, "m", MUT)
        cv.text(bx + hw - 16, y2 + 14, f"{'+' if up else ''}{coin['change']:.2f} %".replace(".", ","), 12, "b", c, anchor="r")
        cv.text(bx + 16, y2 + 30, eur_short(coin["price"]), 17, "b", TXT, maxw=hw - 30)
        sparkline(cv, bx + 16, y2 + 58, hw - 32, 22, coin["spark"], c, 2)
    else:
        cv.text(bx + 16, y2 + 14, "Marché", 12, "m", MUT)
        cv.text(bx + 16, y2 + 34, "Connexion…", 15, "s", DIM)
    # grille d'apps
    gy = y2 + 112
    size = 62
    gap = (W - 36 - size * 4) / 3
    for i, (key, name, color, ic) in enumerate(APPS):
        cx = 18 + (i % 4) * (size + gap)
        cy = gy + (i // 4) * 98
        app_icon(cv, cx, cy, size, color, ic, name)
        if key == "daily" and d["daily_ready"]:
            cv.circ(cx + size - 2, cy + 2, 10, "#FF3B30")
            cv.text(cx + size - 2, cy + 2, "1", 11, "b", "#FFFFFF", anchor="c", valign="mid")
    # dock
    dy = H - 112
    cv.rr(14, dy, W - 28, 86, 30, "#1E222C", 190)
    for i, key in enumerate(("casino", "wallet", "crypto", "profile")):
        a = APP_BY_KEY[key]
        app_icon(cv, 30 + i * 86, dy + 12, 62, a[2], a[3])
    _toast(cv, t)
    return finish(cv)


# =============== CASINO (lobby) ===============
def lobby(brand, cash, games, cat="all", t=None):
    """games: liste (key, nom, tag, couleur, catégorie)"""
    cv = phone()
    cv.rr(18, 56, 36, 36, 11, "#7C4DFF")
    cv.icon("dice", 25, 63, 22, "#FFFFFF", 2)
    cv.text(64, 54, f"{brand.upper()} CASINO", 18, "x", TXT, maxw=180)
    cv.text(64, 79, f"{len(games)} jeux · provably fair", 11, "m", DIM)
    s = eur(cash)
    tw = text_w(s, 13, "b")
    cv.rr(W - 18 - tw - 22, 58, tw + 22, 32, 11, SURF)
    cv.text(W - 29, 74, s, 13, "b", TXT, anchor="r", valign="mid")
    x = 18
    for k, label in (("all", "Tous"), ("originals", "Originals"), ("casino", "Casino")):
        on = k == cat
        x += pill(cv, x, 104, label, TXT if on else SURF, BG if on else "#C9CFDA", 13, "s", h=32, px=15) + 8
    shown = [g for g in games if cat == "all" or g[4] == cat]
    cols, gap = 3, 8
    tw_ = (W - 36 - gap * (cols - 1)) / cols
    th = 80 if len(shown) > 15 else 96
    for i, (key, name, tag, color, _c) in enumerate(shown):
        gx = 18 + (i % cols) * (tw_ + gap)
        gy = 148 + (i // cols) * (th + gap)
        cv.rr(gx, gy, tw_, th, 16, color, shader=cv.lin(gx, gy, gx + tw_, gy + th, mix(color, "#FFFFFF", 0.1), mix(color, "#000000", 0.25)))
        cv.clip_rr(gx, gy, tw_, th, 16)
        cv.circ(gx + tw_ - 8, gy + 8, 30, "#FFFFFF", 30)
        cv.c.restore()
        cv.text(gx + 11, gy + th - 40, name, 14, "b", "#FFFFFF", maxw=tw_ - 18)
        cv.text(gx + 11, gy + th - 21, tag, 11, "m", "#FFFFFF", a=200, maxw=tw_ - 18)
    _toast(cv, t)
    return finish(cv)


# =============== WALLET ===============
def wallet(brand, cash, txs, t=None):
    cv = phone()
    cv.text(20, 52, "Wallet", 30, "x")
    x, y, w, h = 18, 104, W - 36, 200
    cv.shadow(x, y, w, h, 24, 18, 150, 12)
    cv.rr(x, y, w, h, 24, "#1A1530")
    cv.c.save()
    import skia
    cv.c.clipRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), 24, 24), skia.ClipOp.kIntersect, True)
    cv.circ(x + w + 10, y - 10, 150, "#7C4DFF", 150, blur=28)
    cv.circ(x - 20, y + h + 30, 140, "#E0A526", 100, blur=28)
    cv.c.restore()
    cv.text(x + 20, y + 20, brand.upper(), 17, "x", TXT)
    cv.rr(x + w - 60, y + 18, 40, 30, 6, "#D8B25A")
    cv.line(x + w - 60, y + 33, x + w - 20, y + 33, "#A88A3A", 1)
    cv.text(x + 20, y + 92, "Espèces disponibles", 12, "m", "#D5CCF5")
    cv.text(x + 20, y + 108, eur(cash), 34, "b", TXT, maxw=w - 40)
    cv.text(x + 20, y + h - 34, "•••• " + str(abs(hash(brand)) % 9000 + 1000), 14, "s", "#D5CCF5")
    cv.text(x + w - 20, y + h - 34, brand.upper(), 14, "s", "#D5CCF5", anchor="r", maxw=150)
    acts = (("send", "Envoyer"), ("bank", "Banque"), ("chart", "Crypto"), ("bag", "Boutique"))
    aw = (W - 36) / 4
    for i, (ic, label) in enumerate(acts):
        cx = 18 + aw * i + aw / 2
        cv.circ(cx, 350, 27, SURF2)
        cv.icon(ic, cx - 11, 339, 22, TXT, 2)
        cv.text(cx, 384, label, 12, "m", "#C9CFDA", anchor="c")
    cv.text(20, 418, "Transactions", 17, "b")
    _tx_list(cv, 450, txs, 6)
    _toast(cv, t)
    return finish(cv)


def _tx_list(cv, y, txs, n):
    if not txs:
        cv.rr(18, y, W - 36, 64, 18, SURF)
        cv.text(W / 2, y + 32, "Aucune opération pour l'instant", 13, "m", DIM, anchor="c", valign="mid")
        return
    rows = txs[:n]
    cv.rr(18, y, W - 36, 56 * len(rows), 18, SURF)
    for i, (label, sub, amount, badge, bcolor) in enumerate(rows):
        ry = y + i * 56
        if i:
            cv.line(64, ry, W - 18, ry, "#202734", 1)
        cv.rr(30, ry + 10, 36, 36, 11, mix(bcolor, BG, 0.75))
        cv.text(48, ry + 28, badge, 11, "b", bcolor, anchor="c", valign="mid", maxw=32)
        cv.text(78, ry + 11, label, 14, "s", TXT, maxw=180)
        cv.text(78, ry + 31, sub, 11.5, "r", MUT, maxw=180)
        cv.text(W - 32, ry + 28, eur(amount, sign=True), 14, "b", GREEN if amount > 0 else (RED_SOFT if amount < 0 else MUT),
                anchor="r", valign="mid")


# =============== BANQUE ===============
def bank(brand, balance, savings, rate_txt, ops, t=None):
    cv = phone()
    cv.text(20, 52, "Banque", 30, "x")
    cv.rr(W - 58, 56, 40, 40, 12, "#2F6BFF")
    cv.icon("bank", W - 49, 65, 22, "#FFFFFF", 2)
    cv.rr(18, 108, W - 36, 116, 24, "#12224A")
    cv.rr(18.5, 108.5, W - 37, 115, 24, "#24407F", stroke=1)
    cv.text(38, 126, "Compte courant", 13, "m", "#A9C2F5")
    cv.text(38, 144, eur(balance), 36, "b", TXT, maxw=W - 80)
    cv.text(38, 194, f"FR76 {brand.upper()[:4]:<4} •••• {abs(hash(brand + 'b')) % 9000 + 1000} · à l'abri des jeux", 11.5, "r", "#A9C2F5", maxw=W - 80)
    cv.rr(18, 234, W - 36, 80, 22, SURF)
    cv.icon("piggy", 34, 260, 28, GOLD, 2)
    cv.text(74, 250, "Livret épargne", 13, "m", MUT)
    cv.text(74, 268, eur(savings), 22, "b", TXT, maxw=170)
    cv.text(W - 36, 254, rate_txt[0], 14, "b", GREEN, anchor="r")
    cv.text(W - 36, 276, rate_txt[1], 11.5, "r", MUT, anchor="r")
    aw = (W - 36 - 16) / 3
    for i, (ic, label) in enumerate((("down", "Déposer"), ("up", "Retirer"), ("swap", "Virement"))):
        ax = 18 + i * (aw + 8)
        cv.rr(ax, 326, aw, 76, 18, SURF)
        cv.icon(ic, ax + aw / 2 - 11, 340, 22, "#7FB0FF", 2.2)
        cv.text(ax + aw / 2, 372, label, 13, "s", TXT, anchor="c")
    cv.text(20, 420, "Relevé", 17, "b")
    _tx_list(cv, 452, ops, 6)
    _toast(cv, t)
    return finish(cv)


# =============== CRYPTO ===============
def crypto(brand, portfolio, pnl, coins, live, page=0, t=None):
    """coins: dicts sym, name, color, price, change, spark, qty"""
    cv = phone()
    cv.text(20, 50, "Crypto", 30, "x")
    c = GREEN if live else GOLD
    cv.circ(W - 64, 72, 4, c)
    cv.text(W - 56, 72, "LIVE" if live else "HORS LIGNE", 11.5, "b", c, valign="mid")
    cv.rr(18, 104, W - 36, 96, 20, GREEN_BG)
    cv.rr(18.5, 104.5, W - 37, 95, 20, GREEN_LINE, stroke=1)
    cv.text(34, 118, "Mon portefeuille", 12, "m", "#8FD9B0")
    cv.text(34, 134, eur(portfolio), 26, "b", TXT, maxw=200)
    pc = GREEN if pnl >= 0 else RED_SOFT
    cv.text(34, 172, f"{eur(pnl, sign=True)} latent", 12.5, "s", pc)
    if coins:
        ref = coins[0]
        sparkline(cv, W - 150, 126, 112, 50, ref["spark"], GREEN if ref["change"] >= 0 else RED_SOFT)
    cv.text(22, 214, "MARCHÉ · EN EUROS", 11, "s", DIM)
    cv.text(W - 22, 214, "24 H", 11, "s", DIM, anchor="r")
    per = 9
    shown = coins[page * per:(page + 1) * per]
    for i, co in enumerate(shown):
        ry = 236 + i * 56
        cv.circ(38, ry + 24, 18, co["color"])
        cv.text(38, ry + 24, co["sym"][:4], 9.5 if len(co["sym"]) > 3 else 11, "b", "#FFFFFF", anchor="c", valign="mid")
        cv.text(66, ry + 8, co["sym"], 14, "s", TXT)
        sub = co["name"] if not co.get("qty") else f"{co['qty']:.6g} détenu"
        cv.text(66, ry + 28, sub, 11, "r", GOLD if co.get("qty") else MUT, maxw=96)
        up = co["change"] >= 0
        lc = GREEN if up else RED_SOFT
        sparkline(cv, 170, ry + 12, 72, 24, co["spark"], lc, 1.8, fill=False)
        cv.text(W - 22, ry + 8, _price(co["price"]), 14, "s", TXT, anchor="r")
        cv.text(W - 22, ry + 28, f"{'+' if up else ''}{co['change']:.2f} %".replace(".", ","), 12, "s", lc, anchor="r")
    pages = (len(coins) + per - 1) // per
    if pages > 1:
        for p in range(pages):
            cv.circ(W / 2 - (pages - 1) * 8 + p * 16, H - 34, 3.5, TXT if p == page else "#4A5263")
    _toast(cv, t)
    return finish(cv)


def _price(cents_f):
    """Prix en euros (float, en euros) avec précision adaptée."""
    v = cents_f
    if v >= 1000:
        s = f"{v:,.0f}".replace(",", " ")
    elif v >= 1:
        s = f"{v:,.2f}".replace(",", " ").replace(".", ",")
    elif v >= 0.01:
        s = f"{v:.4f}".replace(".", ",")
    else:
        s = f"{v:.8f}".rstrip("0").replace(".", ",")
    return s + " €"


def crypto_coin(co, qty, value_cents, cash, avg_cents=None, t=None):
    cv = phone()
    app_header(cv, co["sym"], cash, "Crypto")
    cv.circ(W / 2, 140, 34, co["color"])
    cv.text(W / 2, 140, co["sym"][:4], 15, "b", "#FFFFFF", anchor="c", valign="mid")
    cv.text(W / 2, 184, co["name"], 15, "s", MUT, anchor="c")
    cv.text(W / 2, 206, _price(co["price"]), 38, "b", TXT, anchor="c", maxw=W - 40)
    up = co["change"] >= 0
    lc = GREEN if up else RED_SOFT
    pill(cv, W / 2, 262, f"{'+' if up else ''}{co['change']:.2f} % · 24 h".replace(".", ","), mix(lc, BG, 0.8), lc, 13, "b", anchor="c")
    cv.rr(18, 304, W - 36, 210, 22, SURF)
    sparkline(cv, 34, 324, W - 68, 170, co["spark"], lc, 2.5)
    stat_boxes(cv, 530, [("Détenu", f"{qty:.6g}" if qty else "0"), ("Valeur", eur(value_cents), GOLD),
                         ("Prix moyen", eur(avg_cents) if avg_cents else "—")])
    cv.rr(18, 604, W - 36, 64, 18, SURF)
    cv.text(34, 618, "Frais de transaction", 12, "m", MUT)
    cv.text(34, 636, "0,10 % à l'achat et à la vente", 13, "s", TXT)
    footer_note(cv, "Cours en direct · monnaie virtuelle du bot", 690)
    _toast(cv, t)
    return finish(cv)


# =============== MÉTIERS ===============
def jobs(cur, level, xp, xp_need, ready_txt, ready, job_list, t=None):
    """cur: (nom, couleur, icône, salaire_txt) · job_list: (nom, sous-titre, salaire, état, couleur, débloqué, actuel)"""
    cv = phone()
    cv.text(20, 50, "Métiers", 30, "x")
    y = 104
    cv.rr(18, y, W - 36, 168, 24, "#2E1610")
    cv.rr(18.5, y + 0.5, W - 37, 167, 24, "#6B2E1E", stroke=1)
    cv.rr(36, y + 18, 56, 56, 16, cur[1])
    cv.icon(cur[2], 50, y + 32, 28, "#FFFFFF", 2)
    cv.text(106, y + 22, "Ton métier", 12, "m", "#F0B3A3")
    cv.text(106, y + 40, f"{cur[0]} · niv. {level}", 19, "b", TXT, maxw=150)
    cv.text(W - 36, y + 26, cur[3], 17, "b", TXT, anchor="r")
    cv.text(W - 36, y + 48, "par service", 11, "r", "#F0B3A3", anchor="r")
    cv.text(36, y + 94, f"XP vers le niveau {level + 1}", 12, "m", "#F0B3A3")
    cv.text(W - 36, y + 94, f"{xp} / {xp_need}", 12, "b", "#F0B3A3", anchor="r")
    progress(cv, 36, y + 114, W - 72, 8, xp / max(1, xp_need), "#FF8A65", "#4A2219")
    cv.text(36, y + 134, ready_txt, 13.5, "s", GREEN if ready else TXT)
    cv.text(20, 290, "Carrières", 17, "b")
    rows = job_list[:7]
    cv.rr(18, 322, W - 36, 58 * len(rows), 20, SURF)
    for i, (name, sub, pay, state, color, unlocked, current) in enumerate(rows):
        ry = 322 + i * 58
        if i:
            cv.line(64, ry, W - 18, ry, "#202734", 1)
        a = 255 if unlocked else 140
        cv.rr(30, ry + 10, 38, 38, 12, color, a)
        cv.text(49, ry + 29, name[:2].upper(), 12, "b", "#FFFFFF", anchor="c", valign="mid", a=a)
        cv.text(80, ry + 11, name, 14, "s", TXT, a=a, maxw=170)
        cv.text(80, ry + 31, sub, 11.5, "r", MUT, a=a, maxw=170)
        cv.text(W - 32, ry + 11, pay, 14, "b", TXT, anchor="r", a=a)
        cv.text(W - 32, ry + 31, state, 11, "s", GOLD if current else (GREEN if unlocked else MUT), anchor="r")
    _toast(cv, t)
    return finish(cv)


# =============== PROFIL ===============
def profile(d, t=None):
    """d: name, vip, vip_color, next_vip, pct, left, job, stats[(label,val,color)], fav, badges[(txt,bg,fg)], rank"""
    cv = phone()
    app_header(cv, "PROFIL", None)
    avatar(cv, W / 2, 152, 44, d["name"], d["vip_color"])
    cv.text(W / 2, 208, d["name"], 22, "b", TXT, anchor="c", maxw=W - 60)
    x = W / 2
    w1 = text_w(f"VIP {d['vip']}", 11.5, "b") + 20
    w2 = text_w(d["job"], 11.5, "s") + 20
    sx = x - (w1 + w2 + 8) / 2
    pill(cv, sx, 242, f"VIP {d['vip']}", d["vip_color"], BG, 11.5, "b")
    pill(cv, sx + w1 + 8, 242, d["job"], SURF2, "#C9CFDA", 11.5, "s")
    y = 282
    cv.rr(18, y, W - 36, 78, 20, SURF)
    if d["next_vip"]:
        cv.text(34, y + 14, f"Vers VIP {d['next_vip']}", 13, "m", MUT)
        cv.text(W - 34, y + 14, f"{int(d['pct'] * 100)} %", 13, "b", TXT, anchor="r")
        progress(cv, 34, y + 36, W - 68, 10, d["pct"], d["vip_color"])
        cv.text(34, y + 54, f"Encore {eur(d['left'])} à miser", 11.5, "r", MUT)
    else:
        cv.text(34, y + 28, "Niveau VIP maximum atteint", 15, "b", GOLD)
    gy = 372
    gw = (W - 36 - 10) / 2
    for i, (label, val, c) in enumerate(d["stats"][:4]):
        gx = 18 + (i % 2) * (gw + 10)
        yy = gy + (i // 2) * 82
        cv.rr(gx, yy, gw, 72, 18, SURF)
        cv.text(gx + 14, yy + 14, label, 12, "m", MUT)
        cv.text(gx + 14, yy + 34, val, 20, "b", c, maxw=gw - 24)
    by = gy + 170
    cv.rr(18, by, W - 36, 110, 20, SURF)
    cv.text(34, by + 14, "Badges", 12, "m", MUT)
    if d["fav"]:
        cv.text(W - 34, by + 14, f"Jeu préféré : {d['fav']}", 12, "s", TXT, anchor="r", maxw=200)
    if d["badges"]:
        for i, (txt, bg, fg) in enumerate(d["badges"][:5]):
            bx = 34 + i * 62
            cv.rr(bx, by + 42, 52, 52, 14, bg)
            cv.text(bx + 26, by + 68, txt, 11, "b", fg, anchor="c", valign="mid", maxw=46)
    else:
        cv.text(34, by + 60, "Joue pour débloquer tes premiers badges", 13, "m", DIM)
    if d.get("rank"):
        footer_note(cv, f"Classement richesse : #{d['rank']}", by + 128)
    _toast(cv, t)
    return finish(cv)


# =============== CLASSEMENT ===============
def leaderboard(kind_label, rows, me=None, t=None):
    """rows: (rang, nom, valeur_txt, est_moi)"""
    cv = phone()
    app_header(cv, "CLASSEMENT", None)
    cv.text(W / 2, 96, kind_label, 13, "s", MUT, anchor="c")
    podium = rows[:3]
    order = [1, 0, 2]
    heights = {0: 120, 1: 92, 2: 76}
    colors = {0: GOLD, 1: "#C9D1DC", 2: "#D39257"}
    for slot, idx in enumerate(order):
        if idx >= len(podium):
            continue
        rk, name, val, _me = podium[idx]
        px = 24 + slot * 116
        h = heights[idx]
        base = 330
        avatar(cv, px + 55, base - h - 50, 26, name, colors[idx], "#2A2F3D")
        cv.text(px + 55, base - h - 16, name, 13, "s", TXT, anchor="c", maxw=104)
        cv.rr(px, base - h + 6, 110, h, 14, mix(colors[idx], BG, 0.78))
        cv.text(px + 55, base - h + 22, str(rk), 26, "x", colors[idx], anchor="c")
        cv.text(px + 55, base - h + 60, val, 11.5, "b", TXT, anchor="c", maxw=100)
    rest = rows[3:10]
    y = 352
    if rest:
        cv.rr(18, y, W - 36, 48 * len(rest), 18, SURF)
    for i, (rk, name, val, is_me) in enumerate(rest):
        ry = y + i * 48
        if is_me:
            cv.rr(18, ry, W - 36, 48, 18, "#1F2A44")
        cv.text(38, ry + 24, str(rk), 14, "b", MUT, anchor="c", valign="mid")
        cv.text(62, ry + 24, name, 14, "s", TXT, valign="mid", maxw=170)
        cv.text(W - 32, ry + 24, val, 14, "b", TXT, anchor="r", valign="mid")
    if me:
        cv.rr(18, H - 92, W - 36, 50, 18, "#1F2A44")
        cv.text(38, H - 67, f"#{me[0]}", 14, "b", BLUE, valign="mid")
        cv.text(90, H - 67, "Toi", 14, "s", TXT, valign="mid")
        cv.text(W - 32, H - 67, me[1], 14, "b", TXT, anchor="r", valign="mid")
    _toast(cv, t)
    return finish(cv)


# =============== BOUTIQUE ===============
def shop(cash, items, t=None):
    """items: (id, nom, prix_cents, description, possédé)"""
    cv = phone()
    app_header(cv, "BOUTIQUE", cash)
    if not items:
        cv.rr(18, 110, W - 36, 120, 22, SURF)
        cv.icon("bag", W / 2 - 16, 130, 32, DIM, 2)
        cv.text(W / 2, 176, "La boutique est vide", 15, "s", TXT, anchor="c")
        cv.text(W / 2, 198, "Le staff peut ajouter des articles", 12, "r", MUT, anchor="c")
    for i, (iid, name, price, desc, owned) in enumerate(items[:8]):
        y = 104 + i * 76
        cv.rr(18, y, W - 36, 68, 18, SURF)
        cv.rr(30, y + 12, 44, 44, 12, "#D6336C")
        cv.text(52, y + 34, f"#{iid}", 12, "b", "#FFFFFF", anchor="c", valign="mid")
        cv.text(86, y + 13, name, 15, "s", TXT, maxw=170)
        cv.text(86, y + 35, desc or "Article", 11.5, "r", MUT, maxw=170)
        if owned:
            pill(cv, W - 30, y + 22, "Possédé", GREEN_BG, GREEN, 12, "b", anchor="r")
        else:
            cv.text(W - 32, y + 34, eur(price), 15, "b", GOLD if cash >= price else RED_SOFT, anchor="r", valign="mid")
    _toast(cv, t)
    return finish(cv)


# =============== PROVABLY FAIR ===============
def fair(server_hash, client, nonce, prev=None, t=None):
    cv = phone()
    app_header(cv, "PROVABLY FAIR", None)
    cv.rr(18, 104, W - 36, 96, 22, "#0B2E2E")
    cv.icon("shield", 34, 124, 30, "#3CC9C9", 2.2)
    cv.text(78, 120, "Chaque tirage est vérifiable", 15, "b", TXT, maxw=W - 110)
    cv.text(78, 142, "HMAC-SHA256(serveur, client:nonce)", 12, "m", "#9ADCDC", maxw=W - 110)
    cv.text(78, 162, "Le seed serveur est révélé quand tu le changes.", 11.5, "r", MUT, maxw=W - 110)

    def field(y, label, value, mono_color=TXT):
        cv.rr(18, y, W - 36, 72, 18, SURF)
        cv.text(34, y + 12, label, 12, "m", MUT)
        v = str(value)
        if len(v) > 34:
            cv.text(34, y + 30, v[:32], 12.5, "s", mono_color)
            cv.text(34, y + 48, v[32:64], 12.5, "s", mono_color)
        else:
            cv.text(34, y + 34, v, 15, "s", mono_color)
    field(214, "Seed serveur actuel (hash SHA-256)", server_hash)
    field(296, "Seed client", client)
    field(378, "Nonce (parties jouées avec ce seed)", nonce)
    if prev:
        cv.text(20, 470, "Ancien seed révélé", 15, "b")
        field(500, "Seed serveur", prev[0], GOLD)
        field(582, f"Client {prev[1]} · nonces 0 à {max(0, prev[2] - 1)}", prev[1])
    _toast(cv, t)
    return finish(cv)


# =============== AIDE ===============
def help_screen(groups, t=None):
    """groups: (titre, [(nom, desc, couleur, icône)])"""
    cv = phone()
    cv.text(20, 50, "Aide", 30, "x")
    y = 100
    for title, rows in groups:
        cv.text(24, y, title.upper(), 11.5, "s", DIM)
        y += 22
        cv.rr(18, y, W - 36, 54 * len(rows), 18, SURF)
        for i, (name, desc, color, ic) in enumerate(rows):
            ry = y + i * 54
            if i:
                cv.line(60, ry, W - 18, ry, "#202734", 1)
            cv.rr(30, ry + 12, 30, 30, 8, color)
            cv.icon(ic, 36, ry + 18, 18, "#FFFFFF", 2)
            cv.text(72, ry + 10, name, 14.5, "s", TXT, maxw=250)
            cv.text(72, ry + 30, desc, 11.5, "r", MUT, maxw=270)
        y += 54 * len(rows) + 18
    _toast(cv, t)
    return finish(cv)
