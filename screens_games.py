"""
screens_games.py — rendu des 19 jeux dans le téléphone.
render(key, cash, bet, st, result=None, footer=None, t=None) -> bytes
`st` est l'état du jeu (dict). `result` = dict(bet, payout, mult, label) quand la partie est finie.
"""
import math
import skia

from gfx import (W, H, BG, SURF, SURF2, LINE, TXT, MUT, DIM, GOLD, GREEN, GREEN_BG, GREEN_LINE, RED, RED_SOFT, RED_BG,
                 BLUE, phone, finish, app_header, pill, stat_boxes, footer_note, result_card, toast, text_w, eur,
                 xfmt, mfmt, playing_card, mix, sparkline)

CONTENT_TOP = 100
STATS_Y = 596


def hint_card(cv, title, sub="", color=TXT):
    y = H - 168
    cv.rr(14, y, W - 28, 116, 24, SURF)
    cv.rr(14.5, y + 0.5, W - 29, 115, 24, LINE, stroke=1)
    cv.text(W / 2, y + 34, title, 20, "b", color, anchor="c", maxw=W - 60)
    if sub:
        cv.text(W / 2, y + 70, sub, 12.5, "m", MUT, anchor="c", maxw=W - 60)


def mult_color(m):
    if m <= 0:
        return "#2A3140"
    if m < 1:
        return "#4A5568"
    if m < 1.5:
        return "#2BD67B"
    if m < 2.5:
        return "#4C8DFF"
    if m < 5:
        return "#9B6BFF"
    if m < 15:
        return "#F5A524"
    return "#FF4D6A"


# ======================= MINES =======================
def d_mines(cv, bet, st, final):
    n, rev, mines, hit = st["n"], set(st["revealed"]), st.get("mines") or set(), st.get("hit")
    mult, nxt = st.get("mult", 1.0), st.get("next", 1.0)
    playing = st.get("active")
    cv.rr(18, 104, W - 36, 86, 22, GREEN_BG if mult > 1 else SURF)
    cv.rr(18.5, 104.5, W - 37, 85, 22, GREEN_LINE if mult > 1 else LINE, stroke=1)
    cv.text(36, 118, "Multiplicateur actuel", 12, "m", "#8FD9B0" if mult > 1 else MUT)
    cv.text(36, 136, xfmt(mult), 36, "b", GREEN if mult > 1 else TXT)
    cv.text(W - 36, 118, "Gain si tu encaisses", 12, "m", "#8FD9B0" if mult > 1 else MUT, anchor="r")
    cv.text(W - 36, 142, eur(int(bet * mult)) if mult > 1 else "—", 20, "b", TXT, anchor="r")
    tw, th, gap = 64, 68, 8
    x0, y0 = (W - (tw * 5 + gap * 4)) / 2, 212
    show = final or st.get("reveal")
    for i in range(20):
        x = x0 + (i % 5) * (tw + gap)
        y = y0 + (i // 5) * (th + gap)
        if i == hit:
            cv.rr(x, y, tw, th, 14, "#5A1620")
            cv.rr(x + 1, y + 1, tw - 2, th - 2, 14, RED, stroke=2)
            _bomb(cv, x + tw / 2, y + th / 2, 17)
        elif i in rev:
            cv.rr(x, y, tw, th, 14, "#123323")
            cv.rr(x + 1, y + 1, tw - 2, th - 2, 14, GREEN, stroke=2)
            _gem(cv, x + tw / 2, y + th / 2, 30, GREEN)
        elif show and i in mines:
            cv.rr(x, y, tw, th, 14, "#1A1216")
            _bomb(cv, x + tw / 2, y + th / 2, 13, a=150)
        elif show:
            cv.rr(x, y, tw, th, 14, "#121821")
            _gem(cv, x + tw / 2, y + th / 2, 22, GREEN, a=90)
        else:
            cv.rr(x, y + 4, tw, th - 4, 14, "#141A24")
            cv.rr(x, y, tw, th - 4, 14, SURF2, shader=cv.lin(x, y, x, y + th, "#232B3A", "#1A2130"))
    stat_boxes(cv, STATS_Y - 72, [("Mise", eur(bet)), ("Mines", str(n), RED_SOFT),
                                  ("Prochaine gemme", xfmt(nxt), GREEN)])
    if playing:
        return ("Choisis une case", f"{len(rev)} gemme{'s' if len(rev) > 1 else ''} trouvée{'s' if len(rev) > 1 else ''} · encaisse quand tu veux")
    return ("Choisis le nombre de mines", "Plus de mines = plus gros multiplicateurs")


def _gem(cv, cx, cy, s, color, a=255):
    cv.shape("M6 3h12l4 6-10 12L2 9z", cx - s / 2, cy - s / 2, s, color, a)
    k = s / 24
    p = skia.Path()
    for seg in (((2, 9), (22, 9)), ((12, 21), (8, 9)), ((8, 9), (12, 3)), ((12, 3), (16, 9)), ((16, 9), (12, 21))):
        p.moveTo(cx - s / 2 + seg[0][0] * k, cy - s / 2 + seg[0][1] * k)
        p.lineTo(cx - s / 2 + seg[1][0] * k, cy - s / 2 + seg[1][1] * k)
    cv.path(p, "#0B3D22" if color == GREEN else "#000000", min(a, 160), stroke=1.1)


def _bomb(cv, cx, cy, r, a=255):
    cv.circ(cx, cy + 2, r, "#1B1E25", a)
    cv.circ(cx - r * 0.35, cy - r * 0.25, r * 0.28, "#FFFFFF", min(a, 70))
    cv.line(cx + r * 0.55, cy - r * 0.6, cx + r * 0.95, cy - r * 1.05, "#C9A27A", 2.2, a)
    cv.circ(cx + r * 1.0, cy - r * 1.12, 3.2, "#FFB020", a)


# ======================= CRASH =======================
def d_crash(cv, bet, st, final):
    recent = st.get("recent", [])
    x = 18
    for m in recent[-7:][::-1]:
        c = GREEN if m >= 2 else RED_SOFT
        x += pill(cv, x, 102, xfmt(m), GREEN_BG if m >= 2 else RED_BG, c, 11.5, "b", h=24, px=8) + 6
        if x > W - 60:
            break
    gx, gy, gw, gh = 18, 136, W - 36, 400
    cv.rr(gx, gy, gw, gh, 22, "#10141C")
    cv.rr(gx + 0.5, gy + 0.5, gw - 1, gh - 1, 22, "#202734", stroke=1)
    for i in range(1, 5):
        cv.line(gx + 12, gy + i * gh / 5, gx + gw - 12, gy + i * gh / 5, "#1A2130", 1)
    hist = st.get("history") or [1.0]
    crashed, cashed = st.get("crashed"), st.get("cashed")
    cur = st.get("mult", 1.0)
    top = max(2.0, max(hist) * 1.15)
    n = len(hist)
    color = RED if crashed else GREEN
    if n >= 2:
        pts = []
        for i, m in enumerate(hist):
            px = gx + 24 + (gw - 60) * (i / (n - 1))
            py = gy + gh - 28 - (gh - 70) * ((m - 1) / (top - 1))
            pts.append((px, py))
        # courbe lissée
        p = skia.Path()
        p.moveTo(*pts[0])
        for i in range(1, len(pts)):
            x0, y0 = pts[i - 1]
            x1, y1 = pts[i]
            p.cubicTo(x0 + (x1 - x0) / 2, y0, x0 + (x1 - x0) / 2, y1, x1, y1)
        f = skia.Path(p)
        f.lineTo(pts[-1][0], gy + gh - 28)
        f.lineTo(pts[0][0], gy + gh - 28)
        f.close()
        cv.path(f, color, shader=cv.lin(0, gy, 0, gy + gh, color, color, 70, 0))
        cv.path(p, color, stroke=4)
        ex, ey = pts[-1]
        cv.glow(ex, ey, 26, color, 120)
        cv.circ(ex, ey, 8, color)
    shown = st.get("crash") if crashed else cur
    cv.text(W / 2, gy + 120, xfmt(shown), 74, "b", RED if crashed else TXT, anchor="c")
    sub = "CRASH" if crashed else ("ENCAISSÉ" if cashed else ("EN VOL" if st.get("active") else "PRÊT AU DÉCOLLAGE"))
    cv.text(W / 2, gy + 214, sub, 13, "x", RED if crashed else (GREEN if cashed or st.get("active") else MUT), anchor="c")
    auto = st.get("auto") or 0
    stat_boxes(cv, STATS_Y - 42, [("Mise", eur(bet)), ("Auto-cashout", xfmt(auto) if auto else "Manuel"),
                                  ("Gain actuel", eur(int(bet * cur)) if st.get("active") else "—", GREEN)])
    if st.get("active"):
        return (f"{xfmt(cur)} · {eur(int(bet * cur))}", "Appuie sur Encaisser avant le crash")
    return ("Choisis ton auto-cashout", "La fusée peut exploser à tout moment")


# ======================= DICE =======================
def d_dice(cv, bet, st, final):
    target, d, roll = st["target"], st["dir"], st.get("roll")
    chance = (100 - target) if d == "over" else target
    mult = 99 / chance
    win = None
    if roll is not None:
        win = roll > target if d == "over" else roll < target
    cv.rr(18, 104, W - 36, 220, 26, SURF)
    if roll is None:
        cv.text(W / 2, 150, "—", 80, "b", DIM, anchor="c")
    else:
        cv.text(W / 2, 140, f"{roll:.2f}".replace(".", ","), 80, "b", GREEN if win else RED, anchor="c")
    cv.text(W / 2, 270, f"{'Plus de' if d == 'over' else 'Moins de'} {target:.2f}".replace(".", ","), 16, "s", MUT, anchor="c")
    # barre
    bx, by, bw = 34, 380, W - 68
    cv.rr(bx - 10, by - 26, bw + 20, 76, 20, SURF)
    tx = bx + bw * target / 100
    lose_c, win_c = RED, GREEN
    if d == "over":
        cv.rr(bx, by, tx - bx, 12, 6, lose_c)
        cv.rr(tx, by, bx + bw - tx, 12, 6, win_c)
    else:
        cv.rr(bx, by, tx - bx, 12, 6, win_c)
        cv.rr(tx, by, bx + bw - tx, 12, 6, lose_c)
    cv.rr(tx - 9, by - 8, 18, 28, 6, TXT)
    for i in range(3):
        cv.line(tx - 3 + i * 3, by - 1, tx - 3 + i * 3, by + 13, "#7A8496", 1)
    for v in (0, 25, 50, 75, 100):
        cv.text(bx + bw * v / 100, by + 26, str(v), 11, "m", DIM, anchor="c")
    if roll is not None:
        rx = bx + bw * roll / 100
        c = GREEN if win else RED
        cv.shadow(rx - 26, by - 70, 52, 40, 10, 8, 120, 4)
        cv.rr(rx - 26, by - 70, 52, 40, 10, c)
        cv.shape("M0 0h12l-6 7z", rx - 6, by - 31, 12, c, vb=12)
        cv.text(rx, by - 50, f"{roll:.2f}".replace(".", ","), 13, "b", BG, anchor="c", valign="mid")
    stat_boxes(cv, STATS_Y - 120, [("Multiplicateur", xfmt(mult, 4)), ("Cible", f"{target:.2f}".replace(".", ",")),
                                   ("Chance", f"{chance:.2f} %".replace(".", ","))])
    return ("Règle ta cible puis lance", f"Gain potentiel : {eur(int(bet * mult))}")


# ======================= LIMBO =======================
def d_limbo(cv, bet, st, final):
    target, res = st["target"], st.get("result")
    cv.rr(18, 104, W - 36, 300, 26, SURF)
    if res is None:
        cv.text(W / 2, 190, "x?", 96, "b", DIM, anchor="c")
    else:
        win = res >= target
        cv.glow(W / 2, 250, 140, GREEN if win else RED, 70)
        cv.text(W / 2, 190, xfmt(res), 84 if res < 1000 else 60, "b", GREEN if win else RED, anchor="c", maxw=W - 60)
    cv.text(W / 2, 344, f"Il faut atteindre {xfmt(target)}", 15, "s", MUT, anchor="c")
    chance = 99 / target
    stat_boxes(cv, STATS_Y - 140, [("Cible", xfmt(target)), ("Chance", f"{chance:.4f} %".replace(".", ",")),
                                   ("Gain potentiel", eur(int(bet * target)), GREEN)])
    return ("Choisis ta cible puis joue", "Plus la cible est haute, plus c'est rare")


# ======================= PLINKO =======================
def d_plinko(cv, bet, st, final):
    rows, mults, path = st["rows"], st["mults"], st.get("path")
    cx, y0 = W / 2, 128
    dx = (W - 44) / (rows + 1)
    dy = 400 / rows
    cv.rr(14, 104, W - 28, 470, 22, "#10141C")
    k = 0
    ball_cols = []
    if path:
        for r in range(rows):
            k += 1 if path[r] else 0
            ball_cols.append(k)
    for r in range(rows):
        y = y0 + r * dy
        for j in range(r + 3):
            px = cx + (j - (r + 2) / 2) * dx
            cv.circ(px, y, 3.6 if rows < 16 else 3, "#5A6578")
    if path:
        pts = [(cx, y0 - dy * 0.6)]
        for r in range(rows):
            pts.append((cx + (ball_cols[r] - (r + 1) / 2) * dx, y0 + r * dy + dy * 0.5))
        cv.poly(pts, GOLD, 2, 120)
        bx, by = pts[-1]
        cv.glow(bx, by, 20, GOLD, 160)
        cv.circ(bx, by, 7, GOLD)
    by = y0 + rows * dy - 4
    land = sum(path) if path else None
    bw = dx - 3
    for i, m in enumerate(mults):
        x = cx + (i - rows / 2) * dx
        t = abs(i - rows / 2) / (rows / 2)
        c = mix("#FFE21A", "#FF3B4E", t)
        hl = land == i
        cv.rr(x - bw / 2, by + (4 if hl else 0), bw, 30, 6, c)
        if hl:
            cv.rr(x - bw / 2 - 2, by + 2, bw + 4, 34, 7, TXT, stroke=2)
        cv.text(x, by + 15 + (4 if hl else 0), mfmt(m), 9 if rows < 16 else 7, "b", BG, anchor="c", valign="mid", maxw=bw - 2)
    stat_boxes(cv, STATS_Y - 12, [("Risque", st["risk"].capitalize()), ("Lignes", str(rows)), ("Gain max", xfmt(max(mults), 0), GOLD)])
    return ("Choisis le risque puis lâche la bille", "La bille rebondit au hasard sur les clous")


# ======================= WHEEL =======================
def d_wheel(cv, bet, st, final):
    seg, landed = st["segments"], st.get("landed")
    cx, cy, r = W / 2, 300, 160
    n = len(seg)
    sweep = 360 / n
    rot = -(landed + 0.5) * sweep if landed is not None else 0
    cv.glow(cx, cy, r + 40, "#7C4DFF", 60)
    cv.circ(cx, cy, r + 10, "#1A2130")
    oval = skia.Rect.MakeXYWH(cx - r, cy - r, 2 * r, 2 * r)
    for i, m in enumerate(seg):
        start = -90 + rot + i * sweep
        p = cv.P(mult_color(m))
        cv.c.drawArc(oval, start, sweep - 0.8, True, p)
    cv.circ(cx, cy, r * 0.62, "#0B0E14")
    cv.circ(cx, cy, r * 0.62, "#252D3B", stroke=2)
    if landed is not None:
        m = seg[landed]
        cv.text(cx, cy - 4, xfmt(m, 2) if m else "x0", 36, "b", mult_color(m) if m else RED_SOFT, anchor="c", valign="mid")
        cv.text(cx, cy + 30, "résultat", 12, "m", MUT, anchor="c", valign="mid")
    else:
        cv.text(cx, cy, st["risk"].upper(), 22, "x", TXT, anchor="c", valign="mid")
    cv.shape("M0 0h20l-10 18z", cx - 10, cy - r - 22, 20, TXT, vb=20)
    uniq = sorted(set(seg))
    x, y = 18, 482
    for m in uniq:
        cnt = seg.count(m)
        lbl = f"{xfmt(m, 2) if m else 'x0'} · {cnt}/{n}"
        w = text_w(lbl, 11, "b") + 28
        if x + w > W - 18:
            x, y = 18, y + 34
        cv.rr(x, y, w, 28, 14, SURF)
        cv.circ(x + 13, y + 14, 5, mult_color(m) if m else "#4A5263")
        cv.text(x + 23, y + 14, lbl, 11, "b", TXT, valign="mid")
        x += w + 6
    stat_boxes(cv, STATS_Y - 60, [("Risque", st["risk"].capitalize()), ("Segments", str(n)), ("Gain max", xfmt(max(seg), 2), GOLD)])
    return ("Choisis le risque puis fais tourner", "Le multiplicateur sous la flèche est ton gain")


# ======================= KENO =======================
def d_keno(cv, bet, st, final):
    picks, drawn, table = set(st["picks"]), st.get("drawn"), st["table"]
    ts, gap = 40, 4
    x0 = (W - (ts * 8 + gap * 7)) / 2
    y0 = 110
    for i in range(40):
        num = i + 1
        x = x0 + (i % 8) * (ts + gap)
        y = y0 + (i // 8) * (ts + gap)
        picked = num in picks
        hit = drawn is not None and num in drawn
        if picked and hit:
            cv.rr(x, y, ts, ts, 10, GREEN)
            fg = BG
        elif picked:
            cv.rr(x, y, ts, ts, 10, "#7C4DFF")
            fg = "#FFFFFF"
        elif hit:
            cv.rr(x, y, ts, ts, 10, SURF2)
            cv.rr(x + 1, y + 1, ts - 2, ts - 2, 10, RED_SOFT, stroke=1.5)
            fg = RED_SOFT
        else:
            cv.rr(x, y, ts, ts, 10, SURF2)
            fg = MUT
        cv.text(x + ts / 2, y + ts / 2, str(num), 14, "b", fg, anchor="c", valign="mid")
    hits = len(picks & drawn) if drawn is not None else None
    ty = y0 + 5 * (ts + gap) + 20
    cv.text(20, ty, "GAINS SELON LE NOMBRE DE NUMÉROS TROUVÉS", 10.5, "s", DIM)
    n = len(table)
    cw = (W - 36 - 4 * (n - 1)) / n
    for h, m in enumerate(table):
        x = 18 + h * (cw + 4)
        on = hits == h
        cv.rr(x, ty + 22, cw, 56, 10, (GREEN if m > 0 else "#4A5263") if on else SURF)
        cv.text(x + cw / 2, ty + 36, mfmt(m) if m else "0", 11 if n < 9 else 9, "b", BG if on else (GOLD if m >= 1 else MUT), anchor="c", valign="mid", maxw=cw - 4)
        cv.text(x + cw / 2, ty + 62, str(h), 10, "m", BG if on else DIM, anchor="c", valign="mid")
    stat_boxes(cv, STATS_Y - 40, [("Numéros", str(len(picks))), ("Trouvés", "—" if hits is None else f"{hits}/{len(picks)}", GREEN),
                                  ("Gain max", xfmt(max(table), 0), GOLD)])
    return ("Choisis tes numéros puis tire", "10 numéros sont tirés sur 40")


# ======================= DIAMONDS =======================
DIAMOND_COLORS = ["#FF4D5E", "#FF8A3D", "#FFD23F", "#2BD67B", "#3FA2FF", "#A66BFF", "#E8EDF5"]


def d_diamonds(cv, bet, st, final):
    gems, label = st.get("gems"), st.get("label")
    cv.rr(18, 104, W - 36, 190, 26, SURF)
    gw = (W - 36 - 40) / 5
    for i in range(5):
        cx = 38 + i * (gw + 2.5) + gw / 2 - 6
        cv.rr(cx - 28, 236, 56, 12, 6, "#0E121A")
        if gems:
            c = DIAMOND_COLORS[gems[i]]
            cv.glow(cx, 196, 34, c, 90)
            _gem(cv, cx, 196, 54, c)
        else:
            _gem(cv, cx, 196, 54, "#2A3140")
    cv.text(W / 2, 258, label or "5 gemmes au hasard", 15, "b", TXT if label else MUT, anchor="c")
    table = st["table"]
    y = 308
    cv.rr(18, y, W - 36, 34 * len(table) + 12, 20, SURF)
    for i, (name, m) in enumerate(table):
        ry = y + 6 + i * 34
        on = label == name
        if on:
            cv.rr(24, ry, W - 48, 32, 12, GREEN_BG if m > 0 else SURF2)
        cv.text(40, ry + 16, name, 13.5, "s", TXT if on else "#C9CFDA", valign="mid")
        cv.text(W - 40, ry + 16, xfmt(m, 2) if m else "x0", 13.5, "b", (GREEN if m > 0 else MUT) if on else GOLD, anchor="r", valign="mid")
    return ("Appuie sur Révéler", "Fais des paires, brelans, carrés… de couleurs")


# ======================= CASES =======================
CASE_RARITY = ["#5A6578", "#6B7A90", "#3FA2FF", "#3FA2FF", "#2BD67B", "#2BD67B", "#A66BFF", "#A66BFF", "#F5A524", "#FF4D6A"]


def d_case(cv, bet, st, final):
    mults, weights, strip, reward = st["mults"], st["weights"], st.get("strip"), st.get("reward")
    tot = sum(weights)
    cv.rr(0, 120, W, 160, 0, "#10141C")
    items = strip or [mults[i % len(mults)] for i in (3, 1, 5, 0, 7, 2, 4)]
    cw, gap = 96, 10
    center = len(items) // 2
    for i, m in enumerate(items):
        x = W / 2 - cw / 2 + (i - center) * (cw + gap)
        if x > W or x + cw < 0:
            continue
        ti = mults.index(m) if m in mults else 0
        c = CASE_RARITY[ti]
        on = strip is not None and i == center
        cv.rr(x, 140, cw, 120, 16, mix(c, BG, 0.72))
        cv.rr(x, 248, cw, 12, 0, c)
        cv.rr(x + 0.5, 140.5, cw - 1, 119, 16, c if on else mix(c, BG, 0.5), stroke=2.5 if on else 1)
        cv.text(x + cw / 2, 190, xfmt(m, 2) if m else "x0", 20, "b", TXT if on or strip is None else MUT, anchor="c", valign="mid")
    cv.shape("M0 0h20l-10 14z", W / 2 - 10, 124, 20, GOLD, vb=20)
    cv.shape("M0 14h20l-10-14z", W / 2 - 10, 262, 20, GOLD, vb=20)
    y = 300
    cv.text(20, y, "CONTENU DE LA CAISSE", 10.5, "s", DIM)
    cw2 = (W - 36 - 8) / 2
    for i, (m, w) in enumerate(zip(mults, weights)):
        x = 18 + (i % 2) * (cw2 + 8)
        ry = y + 20 + (i // 2) * 46
        on = reward == m and strip is not None
        cv.rr(x, ry, cw2, 40, 12, mix(CASE_RARITY[i], BG, 0.55) if on else SURF)
        cv.rr(x, ry, 6, 40, 3, CASE_RARITY[i])
        cv.text(x + 18, ry + 20, xfmt(m, 2) if m else "x0", 14, "b", TXT, valign="mid")
        cv.text(x + cw2 - 12, ry + 20, f"{100 * w / tot:.1f} %".replace(".", ","), 12, "m", MUT, anchor="r", valign="mid")
    return ("Appuie sur Ouvrir", "Chaque caisse contient un multiplicateur")


# ======================= COINFLIP =======================
def d_coinflip(cv, bet, st, final):
    face, choice = st.get("face"), st["choice"]
    cx, cy, r = W / 2, 290, 120
    shown = face or choice
    gold = shown == "pile"
    c1, c2 = ("#FFE08A", "#C9921C") if gold else ("#F2F4F8", "#8A93A6")
    cv.glow(cx, cy, r + 70, c1, 70)
    cv.circ(cx, cy + 8, r, mix(c2, "#000000", 0.35))
    cv.circ(cx, cy, r, c1, shader=cv.lin(cx - r, cy - r, cx + r, cy + r, c1, c2))
    cv.circ(cx, cy, r * 0.82, mix(c2, "#000000", 0.15), stroke=4)
    cv.text(cx, cy, "P" if gold else "F", 96, "x", mix(c2, "#000000", 0.35), anchor="c", valign="mid")
    if face:
        win = face == choice
        cv.text(cx, cy + r + 30, face.upper(), 22, "x", GREEN if win else RED, anchor="c")
    stat_boxes(cv, STATS_Y - 100, [("Ton choix", choice.capitalize()), ("Paiement", "x1,98", GREEN), ("Chance", "50 %")])
    return ("Pile ou face ?", "Choisis ton côté puis lance la pièce")


# ======================= HI-LO =======================
def d_hilo(cv, bet, st, final):
    card, last, hist = st["card"], st.get("last"), st.get("hist", [])
    mult = st.get("mult", 1.0)
    if last:
        playing_card(cv, 30, 150, 74, 104, last[0], last[1], dim=True, rot=-8)
        cv.text(67, 270, "précédente", 11, "m", DIM, anchor="c")
    lost = st.get("lost")
    playing_card(cv, W / 2 - 70, 120, 140, 196, card[0], card[1], glow=RED if lost else None)
    bw = (W - 36 - 10) / 2
    for i, (lab, m, p) in enumerate((("Plus haut ou égal", st["mh"], st["ph"]), ("Plus bas ou égal", st["ml"], st["pl"]))):
        x = 18 + i * (bw + 10)
        cv.rr(x, 340, bw, 84, 18, SURF)
        cv.icon("up" if i == 0 else "down", x + 14, 354, 20, GREEN if i == 0 else BLUE, 2.4)
        cv.text(x + 40, 356, lab, 12.5, "s", TXT, maxw=bw - 50)
        cv.text(x + 14, 386, xfmt(m), 20, "b", GREEN if i == 0 else BLUE)
        cv.text(x + bw - 14, 392, f"{p * 100:.1f} %".replace(".", ","), 12, "m", MUT, anchor="r")
    if hist:
        cv.text(20, 440, "HISTORIQUE", 10.5, "s", DIM)
        for i, (rk, s) in enumerate(hist[-8:]):
            playing_card(cv, 18 + i * 44, 460, 38, 54, rk, s)
    stat_boxes(cv, STATS_Y - 14, [("Mise", eur(bet)), ("Multiplicateur", xfmt(mult), GREEN if mult > 1 else TXT),
                                  ("Gain", eur(int(bet * mult)) if st.get("streak") else "—", GREEN)])
    if st.get("active"):
        return ("Plus haut ou plus bas ?", "Enchaîne les bons choix, encaisse quand tu veux")
    return ("Devine la carte suivante", "As = plus petite carte, Roi = plus grande")


# ======================= DRAGON TOWER =======================
def d_dragon(cv, bet, st, final):
    tiles, safe, level, path, dead = st["tiles"], st["safe"], st["level"], st.get("path", []), st.get("dead")
    rows = len(safe)
    show = final or st.get("reveal")
    picked = set(path)
    rh, rg = 44, 6
    x0, y_bottom = 18, 560
    tw = (W - 36 - (tiles - 1) * 8) / tiles
    for r in range(rows):
        y = y_bottom - (r + 1) * (rh + rg) + rg
        cur = r == level and st.get("active")
        if cur:
            cv.rr(x0 - 6, y - 4, W - 24, rh + 8, 14, GOLD, 50)
        for c in range(tiles):
            x = x0 + c * (tw + 8)
            if (r, c) == dead:
                cv.rr(x, y, tw, rh, 12, "#5A1620")
                cv.rr(x + 1, y + 1, tw - 2, rh - 2, 12, RED, stroke=2)
                _dragon_head(cv, x + tw / 2, y + rh / 2, 14)
            elif (r, c) in picked:
                cv.rr(x, y, tw, rh, 12, "#123323")
                cv.rr(x + 1, y + 1, tw - 2, rh - 2, 12, GREEN, stroke=2)
                _egg(cv, x + tw / 2, y + rh / 2, 11, GREEN)
            elif show and r <= max(level, 0) + 8:
                is_safe = c in safe[r]
                cv.rr(x, y, tw, rh, 12, "#121821")
                if is_safe:
                    _egg(cv, x + tw / 2, y + rh / 2, 9, GREEN, 90)
                else:
                    _dragon_head(cv, x + tw / 2, y + rh / 2, 10, 110)
            else:
                cv.rr(x, y, tw, rh, 12, SURF2 if cur else "#161C27")
                if cur:
                    cv.text(x + tw / 2, y + rh / 2, xfmt(st["step"] ** (r + 1)), 12, "b", GOLD, anchor="c", valign="mid", a=170)
    stat_boxes(cv, STATS_Y + 0, [("Étage", f"{level}/{rows}"), ("Multiplicateur", xfmt(st.get("mult", 1.0)), GREEN),
                                 ("Prochain", xfmt(st["step"] ** (level + 1)))])
    if st.get("active"):
        return ("Choisis une case", "Évite les dragons, grimpe et encaisse")
    return ("Choisis la difficulté", "Moins de cases sûres = plus gros gains")


def _egg(cv, cx, cy, r, c, a=255):
    p = skia.Path()
    p.addOval(skia.Rect.MakeXYWH(cx - r * 0.8, cy - r, r * 1.6, r * 2))
    cv.path(p, c, a)


def _dragon_head(cv, cx, cy, s, a=255):
    cv.shape("M2 14C2 8 7 4 13 4L20 2L18 7C21 9 22 12 22 14L17 13L15 17H9L7 13Z", cx - s, cy - s, s * 2, "#FF5A66", a)
    cv.circ(cx + s * 0.35, cy - s * 0.15, s * 0.14, "#1B1E25", a)


# ======================= CHICKEN =======================
def d_chicken(cv, bet, st, final):
    steps, step_m, dead = st.get("steps", 0), st["step_m"], st.get("dead")
    cv.rr(14, 104, W - 28, 470, 22, "#2A2F3A")
    lane_h = 74
    first = max(0, steps - 1)
    for k in range(6):
        idx = first + k
        y = 574 - (k + 1) * lane_h
        if idx == 0:
            cv.rr(14, y, W - 28, lane_h, 0, "#3B5A2E")
            cv.text(W - 30, y + lane_h / 2, "DÉPART", 11, "x", "#A8D08D", anchor="r", valign="mid")
        else:
            cv.rect(14, y, W - 28, lane_h, "#2F3542" if idx % 2 else "#2A2F3A")
            for dx in range(30, W - 30, 44):
                cv.rr(dx, y - 1, 22, 3, 1.5, "#F2F4F8", 120)
            m = step_m ** idx
            done = idx <= steps
            pill(cv, W - 30, y + lane_h / 2 - 13, xfmt(m), GREEN_BG if done else "#1C2330", GREEN if done else GOLD, 12, "b", h=26, anchor="r")
        if idx == steps:
            cxk, cyk = 120, y + lane_h / 2
            if dead and idx == steps + 0:
                pass
            _chicken(cv, cxk, cyk, 20, dead=False)
        if dead and idx == steps + 1:
            _chicken(cv, 120, y + lane_h / 2, 20, dead=True)
            cv.rr(60, y + 12, 120, lane_h - 24, 12, "#C43C30")
            cv.rr(70, y + 18, 34, lane_h - 36, 6, "#7FB0FF", 160)
    stat_boxes(cv, STATS_Y + 0, [("Difficulté", st["diff"].capitalize()), ("Voies traversées", str(steps)),
                                 ("Prochaine", xfmt(step_m ** (steps + 1)), GOLD)])
    if st.get("active"):
        return ("Avancer ou encaisser ?", f"{int(st['p'] * 100)} % de chance de passer chaque voie")
    return ("Choisis la difficulté", "Traverse la route sans te faire écraser")


def _chicken(cv, cx, cy, r, dead=False):
    body = "#9AA3B2" if dead else "#FFFFFF"
    cv.circ(cx, cy, r, body)
    cv.circ(cx + r * 0.7, cy - r * 0.6, r * 0.55, body)
    cv.shape("M0 0L8 3L0 6z", cx + r * 1.15, cy - r * 0.75, r * 0.6, "#FFA62B", vb=8)
    cv.circ(cx + r * 0.8, cy - r * 1.1, r * 0.22, "#FF4D5E")
    cv.circ(cx + r * 0.85, cy - r * 0.65, r * 0.1, "#111318")


# ======================= PUMP =======================
def d_pump(cv, bet, st, final):
    steps, dead = st.get("steps", 0), st.get("dead")
    cx, cy = W / 2, 320
    r = min(150, 56 + steps * 7)
    if dead:
        for i in range(10):
            a = i * 36
            x = cx + math.cos(math.radians(a)) * 110
            y = cy + math.sin(math.radians(a)) * 110
            cv.c.save()
            cv.c.rotate(a, x, y)
            cv.rr(x - 18, y - 8, 36, 16, 6, "#E8424F")
            cv.c.restore()
        cv.text(cx, cy, "POP !", 54, "x", RED, anchor="c", valign="mid")
    else:
        cv.glow(cx, cy, r + 50, "#FF4D5E", 80)
        cv.line(cx, cy + r + 12, cx + 6, 560, "#C9CFDA", 1.6)
        cv.shape("M0 0h16l-8 12z", cx - 8, cy + r - 2, 16, "#B5283A", vb=16)
        p = skia.Path()
        p.addOval(skia.Rect.MakeXYWH(cx - r * 0.92, cy - r, r * 1.84, r * 2.04))
        cv.path(p, "#E8424F", shader=cv.rad(cx - r * 0.3, cy - r * 0.4, r * 1.6, "#FF7A86", "#9E1E2E", 255, 255))
        e = skia.Path()
        e.addOval(skia.Rect.MakeXYWH(cx - r * 0.55, cy - r * 0.75, r * 0.32, r * 0.5))
        cv.path(e, "#FFFFFF", 70)
        cv.text(cx, cy, xfmt(st.get("mult", 1.0)), max(22, r * 0.36), "b", "#FFFFFF", anchor="c", valign="mid")
    stat_boxes(cv, STATS_Y + 0, [("Difficulté", st["diff"].capitalize()), ("Pompages", str(steps)),
                                 ("Prochain", xfmt(st.get("next", 1.0)), GOLD)])
    if st.get("active"):
        return ("Gonfler ou encaisser ?", f"{int(st['p'] * 100)} % de chance que le ballon tienne")
    return ("Choisis la difficulté", "Gonfle le ballon, encaisse avant qu'il éclate")


# ======================= SLOTS =======================
SLOT_ORDER = ["cherry", "lemon", "grape", "bell", "star", "diamond", "seven"]


def slot_symbol(cv, sym, cx, cy, s, a=255):
    if sym == "cherry":
        cv.line(cx - s * 0.3, cy + s * 0.05, cx + s * 0.15, cy - s * 0.5, "#3E8E3E", 3, a)
        cv.line(cx + s * 0.3, cy + s * 0.1, cx + s * 0.15, cy - s * 0.5, "#3E8E3E", 3, a)
        cv.circ(cx - s * 0.3, cy + s * 0.25, s * 0.26, "#D7263D", a)
        cv.circ(cx + s * 0.3, cy + s * 0.3, s * 0.26, "#C01F33", a)
    elif sym == "lemon":
        p = skia.Path()
        p.addOval(skia.Rect.MakeXYWH(cx - s * 0.48, cy - s * 0.34, s * 0.96, s * 0.68))
        cv.path(p, "#F7D23E", a)
    elif sym == "grape":
        for gx, gy in ((-0.24, -0.22), (0, -0.22), (0.24, -0.22), (-0.12, 0.02), (0.12, 0.02), (0, 0.26)):
            cv.circ(cx + gx * s, cy + gy * s, s * 0.15, "#7B3FE4", a)
    elif sym == "bell":
        cv.shape("M12 2C8 2 6 5 6 9v6l-2 3h16l-2-3V9C18 5 16 2 12 2zM10 19h4C14 21 10 21 10 19z", cx - s / 2, cy - s / 2, s, "#E0A526", a)
    elif sym == "star":
        cv.shape("M12 2l3 6.5 7 .8-5.2 4.8 1.4 7L12 17.6 5.8 21.1l1.4-7L2 9.3l7-.8z", cx - s / 2, cy - s / 2, s, "#FFC93C", a)
    elif sym == "diamond":
        _gem(cv, cx, cy, s, "#3FA2FF", a)
    elif sym == "seven":
        cv.text(cx, cy, "7", s * 1.05, "x", "#E0263A", anchor="c", valign="mid", a=a)


def d_slots(cv, bet, st, final):
    reels, pays = st.get("reels"), st["pays"]
    cv.rr(16, 104, W - 32, 300, 28, "#3A1D0C")
    cv.rr(17, 105, W - 34, 298, 28, "#B8601A", stroke=3)
    cv.text(W / 2, 120, "777 · MACHINE À SOUS", 15, "x", GOLD, anchor="c")
    rx0, ry0, rw, rh = 32, 156, (W - 64 - 16) / 3, 228
    cv.rr(rx0 - 8, ry0 - 8, W - 48, rh + 16, 18, "#0B0E14")
    for i in range(3):
        x = rx0 + i * (rw + 8)
        cv.rr(x, ry0, rw, rh, 12, "#F4F1EA")
        center = reels[i] if reels else (6 if i != 1 else 4)
        above, below = (center + 3 + i) % 7, (center + 5 + 2 * i) % 7
        for k, sym in enumerate((above, center, below)):
            slot_symbol(cv, SLOT_ORDER[sym], x + rw / 2, ry0 + 38 + k * 76, 44, 255 if k == 1 else 90)
        cv.rr(x, ry0, rw, 24, 0, "#000000", 40)
    win = st.get("win")
    cv.rr(rx0 - 6, ry0 + 76, W - 52, 76, 12, GOLD if win else "#F5C451", stroke=3 if win else 2, a=255 if win else 160)
    y = 418
    cv.text(20, y, "TABLE DES GAINS · 3 IDENTIQUES", 10.5, "s", DIM)
    cw = (W - 36 - 8) / 2
    for i, (sym, m) in enumerate(pays):
        x = 18 + (i % 2) * (cw + 8)
        ry = y + 20 + (i // 2) * 40
        cv.rr(x, ry, cw, 34, 10, SURF)
        if sym == "2cherry":
            slot_symbol(cv, "cherry", x + 18, ry + 17, 18)
            slot_symbol(cv, "cherry", x + 36, ry + 17, 18)
            cv.text(x + 50, ry + 17, "(2)", 11, "m", MUT, valign="mid")
        else:
            for k in range(3):
                slot_symbol(cv, sym, x + 18 + k * 20, ry + 17, 18)
        cv.text(x + cw - 12, ry + 17, xfmt(m, 2), 13, "b", GOLD, anchor="r", valign="mid")
    return ("Appuie sur Lancer", "Aligne 3 symboles identiques sur la ligne du milieu")


# ======================= BLACKJACK =======================
def d_blackjack(cv, bet, st, final):
    dealer, player = st.get("dealer", []), st.get("player", [])
    hide = st.get("hide", True)
    cv.rr(14, 104, W - 28, 476, 28, "#0E3A2A")
    cv.rr(14, 104, W - 28, 476, 28, "#000000", 90, shader=cv.rad(W / 2, 340, 300, "#000000", "#000000", 0, 120))
    cv.rr(20, 110, W - 40, 464, 24, "#0A2C20", stroke=6)
    cv.text(W / 2, 124, "CROUPIER", 11.5, "s", "#9FD6BE", anchor="c")
    if dealer:
        pill(cv, W / 2, 144, str(st.get("dv", "")), "#062016", TXT, 13, "b", anchor="c", h=24)
        n = len(dealer)
        cw = 78
        x0 = W / 2 - (cw + (n - 1) * 34) / 2
        for i, (rk, s) in enumerate(dealer):
            playing_card(cv, x0 + i * 34, 178, cw, 110, rk, s, hidden=hide and i == 0)
    cv.rr(W / 2 - 128, 312, 256, 28, 14, "#E9C46A", 120, stroke=1)
    cv.text(W / 2, 326, "LE BLACKJACK PAIE 3 CONTRE 2", 10.5, "s", "#E9C46A", anchor="c", valign="mid")
    if player:
        n = len(player)
        cw = 78
        x0 = W / 2 - (cw + (n - 1) * 34) / 2
        res = st.get("res")
        for i, (rk, s) in enumerate(player):
            playing_card(cv, x0 + i * 34, 364, cw, 110, rk, s,
                         glow=(GREEN if res == "win" else RED if res == "lose" else None) if i == n - 1 else None)
        pill(cv, W / 2, 488, str(st.get("pv", "")), "#062016", TXT, 13, "b", anchor="c", h=24)
    cv.text(W / 2, 520, "TOI", 11.5, "s", "#9FD6BE", anchor="c")
    cv.circ(W / 2 - 40, 552, 15, "#C43C30")
    cv.circ(W / 2 - 40, 552, 11, "#F2F4F8", stroke=2)
    cv.text(W / 2 - 18, 552, eur(bet * (2 if st.get("doubled") else 1)) + (" · doublé" if st.get("doubled") else ""), 13, "b", TXT, valign="mid")
    if st.get("active"):
        return ("Tirer, rester ou doubler ?", "Approche-toi de 21 sans dépasser")
    return ("Appuie sur Distribuer", "Bats le croupier · Blackjack payé x2,5")


# ======================= ROULETTE =======================
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def r_color(n):
    return "#1E9E5A" if n == 0 else ("#C8202F" if n in RED_NUMBERS else "#1B1E25")


def d_roulette(cv, bet, st, final):
    res, wins = st.get("result"), st.get("wins", set())
    cx = 70
    cv.rr(18, 104, W - 36, 96, 22, SURF)
    if res is None:
        cv.circ(cx, 152, 34, SURF2)
        cv.text(cx, 152, "?", 30, "b", DIM, anchor="c", valign="mid")
    else:
        cv.circ(cx, 152, 36, r_color(res))
        cv.circ(cx, 152, 36, "#FFFFFF", stroke=2)
        cv.text(cx, 152, str(res), 30, "b", "#FFFFFF", anchor="c", valign="mid")
    cv.text(122, 122, "Ton pari", 12, "m", MUT)
    cv.text(122, 140, st["label"], 18, "b", TXT, maxw=160)
    cv.text(W - 36, 122, "Paiement", 12, "m", MUT, anchor="r")
    cv.text(W - 36, 140, f"x{st['pay']}", 18, "b", GOLD, anchor="r")
    hist = st.get("hist", [])
    x = 122
    for n in hist[-6:][::-1]:
        cv.circ(x + 9, 186, 9, r_color(n))
        cv.text(x + 9, 186, str(n), 8.5, "b", "#FFFFFF", anchor="c", valign="mid")
        x += 22
    gx, gy, cw, ch = 30, 246, (W - 60) / 3, 25
    cv.rr(gx, 212, W - 60, 28, 8, r_color(0))
    if 0 in wins:
        cv.rr(gx, 212, W - 60, 28, 8, GOLD, stroke=2.5)
    cv.text(W / 2, 226, "0", 13, "b", "#FFFFFF", anchor="c", valign="mid")
    for n in range(1, 37):
        col_, row = (n - 1) % 3, (n - 1) // 3
        x, y = gx + col_ * cw, gy + row * (ch + 2)
        cv.rr(x + 1, y, cw - 2, ch, 6, r_color(n), 255 if (not wins or n in wins) else 110)
        if n in wins:
            cv.rr(x + 1.5, y + 0.5, cw - 3, ch - 1, 6, GOLD, stroke=2)
        if res == n:
            cv.rr(x + 1, y, cw - 2, ch, 6, "#FFFFFF", stroke=3)
        cv.text(x + cw / 2, y + ch / 2, str(n), 12, "b", "#FFFFFF", anchor="c", valign="mid", a=255 if (not wins or n in wins) else 140)
    return ("Choisis ton pari puis tourne", "Roulette européenne · 37 cases")


# ======================= BACCARAT =======================
def d_baccarat(cv, bet, st, final):
    s = st.get("state")
    side = st["side"]
    labels = {"player": "Joueur", "banker": "Banquier", "tie": "Égalité"}
    for i, (key, title, color) in enumerate((("player", "JOUEUR", BLUE), ("banker", "BANQUIER", RED_SOFT))):
        y = 104 + i * 220
        won = s and s[4] == key
        cv.rr(18, y, W - 36, 208, 24, mix(color, BG, 0.85) if won else SURF)
        cv.rr(18.5, y + 0.5, W - 37, 207, 24, color if won else LINE, stroke=2 if won else 1)
        cv.text(36, y + 16, title, 13, "x", color)
        if side == key:
            pill(cv, W - 34, y + 12, "TON PARI", GOLD, BG, 10.5, "b", anchor="r", h=22)
        if s:
            cards = s[0] if key == "player" else s[1]
            val = s[2] if key == "player" else s[3]
            for j, (rk, su) in enumerate(cards):
                playing_card(cv, 36 + j * 86, y + 52, 76, 108, rk, su)
            cv.circ(W - 64, y + 106, 32, color)
            cv.text(W - 64, y + 106, str(val), 30, "b", "#FFFFFF", anchor="c", valign="mid")
        else:
            for j in range(2):
                playing_card(cv, 36 + j * 86, y + 52, 76, 108, hidden=True)
    if s and s[4] == "tie":
        pill(cv, W / 2, 312, "ÉGALITÉ", GOLD, BG, 13, "x", anchor="c", h=28)
    stat_boxes(cv, STATS_Y - 40, [("Ton pari", labels[side]), ("Paiement", {"player": "x2", "banker": "x1,95", "tie": "x9"}[side], GOLD),
                                  ("Résultat", labels[s[4]] if s else "—")])
    return ("Choisis ton camp puis distribue", "Le plus proche de 9 gagne")


# ======================= VIDEO POKER =======================
def d_videopoker(cv, bet, st, final):
    hand, held, pays, cur = st.get("hand"), st.get("held", set()), st["pays"], st.get("label")
    y = 104
    cv.rr(18, y, W - 36, 24 * len(pays) + 12, 18, "#0E1A33")
    for i, (name, m) in enumerate(pays):
        ry = y + 6 + i * 24
        on = name == cur
        if on:
            cv.rr(24, ry, W - 48, 24, 8, GOLD)
        cv.text(38, ry + 12, name, 12.5, "s", BG if on else "#C9D6F5", valign="mid")
        cv.text(W - 38, ry + 12, xfmt(m, 0), 12.5, "b", BG if on else GOLD, anchor="r", valign="mid")
    cy = y + 24 * len(pays) + 36
    cw, gap = 64, 7
    x0 = (W - (cw * 5 + gap * 4)) / 2
    for i in range(5):
        x = x0 + i * (cw + gap)
        if hand:
            rk, s = hand[i]
            playing_card(cv, x, cy + (-8 if i in held else 0), cw, 92, rk, s, glow=GOLD if i in held else None)
        else:
            playing_card(cv, x, cy, cw, 92, hidden=True)
        if i in held:
            pill(cv, x + cw / 2, cy + 98, "GARDÉE", GOLD, BG, 9.5, "b", anchor="c", h=20, px=6)
    stat_boxes(cv, STATS_Y - 20, [("Main", cur or "—"), ("Mise", eur(bet)), ("Paiement", xfmt(dict(pays).get(cur, 0), 0) if cur else "—", GOLD)])
    if st.get("active"):
        return ("Garde tes cartes puis tire", "Les cartes non gardées sont remplacées")
    return ("Appuie sur Distribuer", "Jacks or Better · paire de valets minimum")


DRAW = {
    "mines": d_mines, "crash": d_crash, "dice": d_dice, "limbo": d_limbo, "plinko": d_plinko, "wheel": d_wheel,
    "keno": d_keno, "diamonds": d_diamonds, "case": d_case, "coinflip": d_coinflip, "hilo": d_hilo,
    "dragon": d_dragon, "chicken": d_chicken, "pump": d_pump, "slots": d_slots, "blackjack": d_blackjack,
    "roulette": d_roulette, "baccarat": d_baccarat, "videopoker": d_videopoker,
}


def render(key, title, cash, bet, st, result=None, footer=None, t=None):
    cv = phone()
    app_header(cv, title.upper(), cash, "Casino")
    hint = DRAW[key](cv, bet, st, result is not None)
    if result:
        result_card(cv, result["bet"], result["payout"], result["mult"], result.get("label", ""))
    elif hint:
        hint_card(cv, *hint)
    if footer:
        footer_note(cv, footer, H - 42)
    if t:
        toast(cv, t[0], t[1])
    return finish(cv)
