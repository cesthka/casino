"""
gfx.py — moteur de rendu (skia) : primitives, téléphone, composants communs.
Toutes les coordonnées sont en "points" (téléphone 390 x 844), rendues en x2.
"""
import os
import re
import math
import functools
from datetime import datetime

import skia

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Paris")
except Exception:  # pragma: no cover
    TZ = None

W, H = 390, 844
SCALE = 2
RADIUS = 46

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

# ---------- Palette ----------
BG = "#0B0E14"
BG_DEEP = "#07090E"
SURF = "#151A23"
SURF2 = "#1C2330"
LINE = "#252D3B"
TXT = "#F2F4F8"
MUT = "#A9B1BF"
DIM = "#8B95A7"
GOLD = "#F5C451"
GREEN = "#2BD67B"
GREEN_BG = "#0F2A1D"
GREEN_LINE = "#1D5238"
RED = "#FF5A66"
RED_SOFT = "#FF7A84"
RED_BG = "#2A1418"
BLUE = "#4C8DFF"


def col(c, a=255):
    if isinstance(c, int):
        return c
    if isinstance(c, tuple):
        r, g, b = c[:3]
        return skia.Color(r, g, b, c[3] if len(c) > 3 else a)
    c = c.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return skia.Color(int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), a)


def rgb(c):
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def mix(c1, c2, t):
    a, b = rgb(c1), rgb(c2)
    return "#%02X%02X%02X" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ---------- Polices ----------
WEIGHTS = {"r": "Regular", "m": "Medium", "s": "SemiBold", "b": "Bold", "x": "ExtraBold"}
_typefaces = {}


def typeface(w):
    if w not in _typefaces:
        path = os.path.join(FONTS_DIR, f"Poppins-{WEIGHTS[w]}.ttf")
        tf = skia.Typeface.MakeFromFile(path) if os.path.exists(path) else None
        _typefaces[w] = tf or skia.Typeface.MakeDefault()
    return _typefaces[w]


@functools.lru_cache(maxsize=512)
def font(size, w="m"):
    f = skia.Font(typeface(w), size)
    f.setSubpixel(True)
    f.setEdging(skia.Font.Edging.kAntiAlias)
    return f


def text_w(s, size, w="m"):
    return font(size, w).measureText(str(s))


# ---------- Mini parseur de chemins SVG (M L H V C Q Z) ----------
_TOK = re.compile(r"[MmLlHhVvCcQqZz]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?")


@functools.lru_cache(maxsize=512)
def svg_path(d):
    toks = _TOK.findall(d)
    p = skia.Path()
    i, cmd = 0, None
    x = y = sx = sy = 0.0

    def num():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                p.close()
                x, y = sx, sy
                continue
        rel = cmd.islower()
        C = cmd.upper()
        if C == "M":
            nx, ny = num(), num()
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            p.moveTo(x, y)
            sx, sy = x, y
            cmd = "l" if rel else "L"
        elif C == "L":
            nx, ny = num(), num()
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            p.lineTo(x, y)
        elif C == "H":
            nx = num()
            x = x + nx if rel else nx
            p.lineTo(x, y)
        elif C == "V":
            ny = num()
            y = y + ny if rel else ny
            p.lineTo(x, y)
        elif C == "C":
            v = [num() for _ in range(6)]
            if rel:
                v = [v[0] + x, v[1] + y, v[2] + x, v[3] + y, v[4] + x, v[5] + y]
            p.cubicTo(*v)
            x, y = v[4], v[5]
        elif C == "Q":
            v = [num() for _ in range(4)]
            if rel:
                v = [v[0] + x, v[1] + y, v[2] + x, v[3] + y]
            p.quadTo(*v)
            x, y = v[2], v[3]
        else:
            i += 1
    return p


# ---------- Icônes (viewBox 24) ----------
# ("p", chemin) trait · ("f", chemin) plein · ("c", cx, cy, r) cercle trait · ("d", cx, cy) point · ("r", x, y, w, h, rx) rect trait
ICONS = {
    "dice": [("r", 3, 3, 18, 18, 4), ("d", 8, 8), ("d", 16, 8), ("d", 12, 12), ("d", 8, 16), ("d", 16, 16)],
    "wallet": [("r", 3, 6, 18, 14, 3), ("p", "M3 10h18"), ("d", 16.5, 15)],
    "bank": [("p", "M3 10h18M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 21h18M12 3l9 5H3z")],
    "chart": [("p", "M3 17l6-6 4 4 8-8M15 7h6v6")],
    "job": [("r", 3, 8, 18, 12, 2), ("p", "M8 8V5h8v3M3 13h18")],
    "user": [("c", 12, 8, 4), ("p", "M4 21C4 16.6 7.6 13 12 13C16.4 13 20 16.6 20 21")],
    "trophy": [("p", "M8 21h8M12 17v4M7 4h10v5C17 11.8 14.8 14 12 14C9.2 14 7 11.8 7 9zM17 5h3v2C20 8.7 18.7 10 17 10M7 5H4v2C4 8.7 5.3 10 7 10")],
    "bag": [("p", "M5 8h14l-1 13H6zM9 8V6C9 4.3 10.3 3 12 3C13.7 3 15 4.3 15 6v2")],
    "help": [("c", 12, 12, 9), ("p", "M9.5 9.5C9.5 8.1 10.6 7 12 7C13.4 7 14.5 8.1 14.5 9.5C14.5 11 12 11.5 12 13.5"), ("d", 12, 17)],
    "gift": [("r", 4, 11, 16, 10, 1), ("r", 3, 7, 18, 4, 1), ("p", "M12 7v14M12 7C10 3 6 4 7.5 7M12 7C14 3 18 4 16.5 7")],
    "shield": [("p", "M12 3l8 3v6C20 17 16.5 20 12 21C7.5 20 4 17 4 12V6zM9 12l2 2 4-4")],
    "book": [("p", "M4 5C4 4 5 3 6 3h14v15H6C5 18 4 19 4 20zM4 20C4 21 5 21 6 21h14v-3")],
    "sliders": [("p", "M4 7h10M18 7h2M4 17h4M12 17h8"), ("c", 16, 7, 2), ("c", 10, 17, 2)],
    "back": [("p", "M15 5l-7 7 7 7")],
    "chev": [("p", "M9 5l7 7-7 7")],
    "send": [("p", "M5 12h14M13 6l6 6-6 6")],
    "recv": [("p", "M19 12H5M11 6l-6 6 6 6")],
    "down": [("p", "M12 5v14M5 12l7 7 7-7")],
    "up": [("p", "M12 19V5M5 12l7-7 7 7")],
    "swap": [("p", "M4 8h14l-3-3M20 16H6l3 3")],
    "lock": [("r", 5, 11, 14, 10, 2), ("p", "M8 11V7C8 4.8 9.8 3 12 3C14.2 3 16 4.8 16 7v4")],
    "check": [("p", "M5 12l5 5L19 7")],
    "x": [("p", "M6 6l12 12M18 6L6 18")],
    "crown": [("p", "M3 19h18M4 8l4 4 4-6 4 6 4-4-2 10H6z")],
    "piggy": [("p", "M5 11C5 7.7 8 5 12 5C16 5 19 7.7 19 11C19 13 18 14.5 17 15.5V19h-3v-2h-4v2H7v-3.5C5.8 14.5 5 13 5 11zM19 10h2"), ("d", 15, 10)],
    "flash": [("p", "M13 2L4 14h7l-1 8 9-12h-7z")],
    "camera": [("p", "M3 8h4l2-3h6l2 3h4v12H3z"), ("c", 12, 13, 4)],
    "bell": [("p", "M6 16V11C6 7.7 8.7 5 12 5C15.3 5 18 7.7 18 11v5l2 2H4zM10 20h4")],
    "star": [("f", "M12 2l3 6.5 7 .8-5.2 4.8 1.4 7L12 17.6 5.8 21.1l1.4-7L2 9.3l7-.8z")],
    "gem": [("f", "M6 3h12l4 6-10 12L2 9z")],
    "play": [("f", "M7 4l13 8-13 8z")],
}

SUIT_PATHS = {
    "D": "M12 2L20 12L12 22L4 12Z",
    "H": "M12 21C12 21 3 14.5 3 8.5C3 5.5 5.5 3 8.5 3C10.2 3 11.4 4 12 5C12.6 4 13.8 3 15.5 3C18.5 3 21 5.5 21 8.5C21 14.5 12 21 12 21Z",
    "S": "M12 2C12 2 3 9 3 14C3 16.8 5.2 19 8 19C9.6 19 11 18.2 11.5 17L10 22H14L12.5 17C13 18.2 14.4 19 16 19C18.8 19 21 16.8 21 14C21 9 12 2 12 2Z",
}


# ---------- Canvas ----------
class Cv:
    def __init__(self, w=W, h=H, scale=SCALE, clip_radius=RADIUS):
        self.w, self.h, self.s = w, h, scale
        self.surface = skia.Surface(int(w * scale), int(h * scale))
        self.c = self.surface.getCanvas()
        self.c.clear(skia.ColorTRANSPARENT)
        self.c.scale(scale, scale)
        if clip_radius:
            self.c.clipRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(0, 0, w, h), clip_radius, clip_radius),
                             skia.ClipOp.kIntersect, True)

    # ---- peinture ----
    @staticmethod
    def P(color=TXT, a=255, stroke=None, blur=None, shader=None, cap_round=True):
        p = skia.Paint(AntiAlias=True, Color=col(color, a))
        if stroke:
            p.setStyle(skia.Paint.kStroke_Style)
            p.setStrokeWidth(stroke)
            if cap_round:
                p.setStrokeCap(skia.Paint.kRound_Cap)
                p.setStrokeJoin(skia.Paint.kRound_Join)
        if blur:
            p.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, blur))
        if shader is not None:
            p.setShader(shader)
        return p

    def fill(self, color):
        self.c.drawPaint(self.P(color))

    def rr(self, x, y, w, h, r, color=SURF, a=255, stroke=None, blur=None, shader=None):
        self.c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), r, r),
                         self.P(color, a, stroke, blur, shader))

    def rect(self, x, y, w, h, color, a=255):
        self.c.drawRect(skia.Rect.MakeXYWH(x, y, w, h), self.P(color, a))

    def circ(self, x, y, r, color, a=255, stroke=None, blur=None, shader=None):
        self.c.drawCircle(x, y, r, self.P(color, a, stroke, blur, shader))

    def line(self, x1, y1, x2, y2, color, sw=1.5, a=255):
        self.c.drawLine(x1, y1, x2, y2, self.P(color, a, stroke=sw))

    def poly(self, pts, color, sw=2, a=255, close=False, fill=False):
        if len(pts) < 2:
            return
        p = skia.Path()
        p.moveTo(*pts[0])
        for q in pts[1:]:
            p.lineTo(*q)
        if close:
            p.close()
        self.c.drawPath(p, self.P(color, a, None if fill else sw))

    def path(self, path, color, a=255, stroke=None, blur=None, shader=None):
        self.c.drawPath(path, self.P(color, a, stroke, blur, shader))

    def shadow(self, x, y, w, h, r, sigma=14, a=110, dy=8):
        self.rr(x, y + dy, w, h, r, "#000000", a, blur=sigma)

    def lin(self, x1, y1, x2, y2, c1, c2, a1=255, a2=255):
        return skia.GradientShader.MakeLinear([skia.Point(x1, y1), skia.Point(x2, y2)], [col(c1, a1), col(c2, a2)])

    def rad(self, x, y, r, c1, c2, a1=255, a2=0):
        return skia.GradientShader.MakeRadial(skia.Point(x, y), r, [col(c1, a1), col(c2, a2)])

    def glow(self, x, y, r, color, a=150):
        self.circ(x, y, r, color, 255, shader=self.rad(x, y, r, color, color, a, 0))

    def clip_rr(self, x, y, w, h, r):
        """Restreint le dessin à un rectangle arrondi (à fermer par self.c.restore())."""
        self.c.save()
        self.c.clipRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), r, r), skia.ClipOp.kIntersect, True)

    # ---- texte ----
    def text(self, x, y, s, size=14, w="m", color=TXT, anchor="l", a=255, maxw=None, valign="top"):
        """Dessine `s`. y = haut de la ligne (valign top), centre (mid) ou ligne de base (base)."""
        s = str(s)
        f = font(size, w)
        if maxw is not None:
            while f.measureText(s) > maxw and size > 8:
                size -= 0.5
                f = font(size, w)
            if f.measureText(s) > maxw:
                while len(s) > 1 and f.measureText(s + "…") > maxw:
                    s = s[:-1]
                s += "…"
        tw = f.measureText(s)
        m = f.getMetrics()
        if valign == "top":
            by = y - m.fAscent
        elif valign == "mid":
            by = y - (m.fAscent + m.fDescent) / 2
        else:
            by = y
        if anchor == "c":
            x -= tw / 2
        elif anchor == "r":
            x -= tw
        self.c.drawString(s, x, by, f, self.P(color, a))
        return tw

    # ---- icônes ----
    def icon(self, name, x, y, size=24, color=TXT, sw=2, a=255):
        spec = ICONS.get(name)
        if not spec:
            return
        self.c.save()
        self.c.translate(x, y)
        k = size / 24
        self.c.scale(k, k)
        sw = sw / k
        for op in spec:
            if op[0] == "p":
                self.c.drawPath(svg_path(op[1]), self.P(color, a, stroke=sw))
            elif op[0] == "f":
                self.c.drawPath(svg_path(op[1]), self.P(color, a))
            elif op[0] == "c":
                self.c.drawCircle(op[1], op[2], op[3], self.P(color, a, stroke=sw))
            elif op[0] == "d":
                self.c.drawCircle(op[1], op[2], 1.6, self.P(color, a))
            elif op[0] == "r":
                self.c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(*op[1:5]), op[5], op[5]), self.P(color, a, stroke=sw))
        self.c.restore()

    def shape(self, d, x, y, size, color, a=255, vb=24):
        self.c.save()
        self.c.translate(x, y)
        self.c.scale(size / vb, size / vb)
        self.c.drawPath(svg_path(d), self.P(color, a))
        self.c.restore()

    def image(self, img, x=0, y=0):
        """Dessine une skia.Image pré-rendue à la même échelle."""
        self.c.save()
        self.c.resetMatrix()
        self.c.drawImage(img, x * self.s, y * self.s)
        self.c.restore()

    def encode(self, fmt="webp", quality=88):
        img = self.surface.makeImageSnapshot()
        kind = {"webp": skia.kWEBP, "png": skia.kPNG, "jpg": skia.kJPEG}[fmt]
        return bytes(img.encodeToData(kind, quality))


# ---------- Formatage ----------
def eur(cents, sign=False):
    cents = int(cents)
    neg = cents < 0
    v = abs(cents)
    s = f"{v // 100:,}".replace(",", " ") + f",{v % 100:02d} €"
    if neg:
        return "-" + s
    return ("+" + s) if sign and cents > 0 else s


def eur_short(cents):
    v = abs(int(cents)) / 100
    if v >= 1_000_000:
        s = f"{v / 1_000_000:.2f}".replace(".", ",") + " M€"
    elif v >= 10_000:
        s = f"{v / 1000:.1f}".replace(".", ",") + " k€"
    else:
        return eur(cents)
    return ("-" if cents < 0 else "") + s


def xfmt(m, dec=2):
    if m >= 1000:
        return "x" + f"{m:,.0f}".replace(",", " ")
    return "x" + f"{m:.{dec}f}".replace(".", ",")


def mfmt(m):
    """Multiplicateur compact : x0,3 · x2 · x1 000."""
    if m >= 1000:
        return f"{m:,.0f}".replace(",", " ")
    if float(m).is_integer():
        return f"{int(m)}"
    return f"{m:g}".replace(".", ",")


def now_paris():
    return datetime.now(TZ) if TZ else datetime.now()


JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


# ---------- Fonds d'écran (pré-rendus une seule fois) ----------
@functools.lru_cache(maxsize=8)
def wallpaper(kind="home"):
    cv = Cv(clip_radius=0)
    cv.fill(BG_DEEP)
    if kind == "home":
        cv.circ(80, 470, 230, "#2A1F5C", blur=75)
        cv.circ(360, 80, 200, "#5C3A0E", 200, blur=85)
        cv.circ(330, 760, 160, "#0E3A4A", 170, blur=80)
    elif kind == "lock":
        cv.circ(90, 330, 230, "#2A1F5C", blur=75)
        cv.circ(340, 620, 210, "#5C3A0E", 210, blur=85)
    elif kind == "win":
        cv.fill(BG)
        cv.circ(195, 330, 170, GREEN, 90, blur=90)
    elif kind == "lose":
        cv.fill(BG)
        cv.circ(195, 330, 170, RED, 70, blur=90)
    else:
        cv.fill(BG)
    return cv.surface.makeImageSnapshot()


# ---------- Éléments du téléphone ----------
def status_bar(cv, light=True):
    t = now_paris().strftime("%H:%M")
    cv.text(40, 25, t, 15, "s", TXT, anchor="l", valign="mid")
    cv.rr(139, 11, 112, 32, 16, "#000000")
    x = 300
    for i, h in enumerate((4, 6, 8.5, 11)):
        cv.rr(x + i * 4.5, 31 - h, 3, h, 1, TXT)
    cv.rr(322, 19.5, 22, 11, 3, TXT, 130, stroke=1)
    cv.rr(324, 21.5, 16, 7, 1.5, TXT)
    cv.rr(345.5, 23, 1.5, 4, 0.7, TXT, 130)


def home_indicator(cv, color=TXT):
    cv.rr(128, H - 14, 134, 5, 2.5, color, 170)


def frame_border(cv):
    cv.rr(1, 1, W - 2, H - 2, RADIUS - 1, "#2A2E38", stroke=2)


def phone(kind="plain"):
    cv = Cv()
    if kind in ("home", "lock", "win", "lose"):
        cv.image(wallpaper(kind))
    else:
        cv.fill(BG)
    status_bar(cv)
    return cv


def finish(cv, fmt="webp"):
    home_indicator(cv)
    frame_border(cv)
    return cv.encode(fmt)


def pill(cv, x, y, s, bg=SURF2, fg=TXT, size=12, w="s", h=None, anchor="l", px=10, a=255):
    tw = text_w(s, size, w)
    h = h or size + 12
    pw = tw + px * 2
    if anchor == "r":
        x -= pw
    elif anchor == "c":
        x -= pw / 2
    cv.rr(x, y, pw, h, h / 2, bg, a)
    cv.text(x + px, y + h / 2, s, size, w, fg, valign="mid")
    return pw


def card(cv, x, y, w, h, color=SURF, r=18, border=LINE, shadow=False):
    if shadow:
        cv.shadow(x, y, w, h, r)
    cv.rr(x, y, w, h, r, color)
    if border:
        cv.rr(x + 0.5, y + 0.5, w - 1, h - 1, r, border, stroke=1)


def app_header(cv, title, balance=None, back="Accueil", accent=None):
    """En-tête d'app : retour · titre · solde."""
    y = 66
    cv.icon("back", 14, y - 10, 20, BLUE, 2.6)
    cv.text(36, y, back, 15, "s", BLUE, valign="mid")
    cv.text(W / 2, y, title, 17, "x", accent or TXT, anchor="c", valign="mid", maxw=170)
    if balance is not None:
        s = balance if isinstance(balance, str) else eur(balance)
        tw = text_w(s, 13, "b")
        cv.rr(W - 18 - tw - 20, y - 15, tw + 20, 30, 10, SURF)
        cv.text(W - 28, y, s, 13, "b", TXT, anchor="r", valign="mid")


def big_title(cv, title, y=60, right=None):
    cv.text(20, y, title, 30, "x", TXT)
    if right:
        right(cv)


def stat_boxes(cv, y, items, x=18, w=W - 36, h=58, gap=8):
    n = len(items)
    bw = (w - gap * (n - 1)) / n
    for i, it in enumerate(items):
        label, value = it[0], it[1]
        color = it[2] if len(it) > 2 else TXT
        bx = x + i * (bw + gap)
        cv.rr(bx, y, bw, h, 14, SURF)
        cv.text(bx + 12, y + 10, label, 11, "m", MUT, maxw=bw - 20)
        cv.text(bx + 12, y + 27, value, 16, "b", color, maxw=bw - 20)


def footer_note(cv, s, y=H - 44):
    cv.text(W / 2, y, s, 10.5, "r", DIM, anchor="c")


def toast(cv, msg, kind="info"):
    """Bannière de notification en haut (feedback sans embed)."""
    colors = {"ok": (GREEN, "check"), "err": (RED, "x"), "info": (BLUE, "bell"), "gold": (GOLD, "gift")}
    c, ic = colors.get(kind, colors["info"])
    cv.shadow(14, 52, W - 28, 58, 20, 16, 160)
    cv.rr(14, 52, W - 28, 58, 20, "#1E2430", 250)
    cv.rr(14.5, 52.5, W - 29, 57, 20, "#FFFFFF", 18, stroke=1)
    cv.rr(26, 63, 36, 36, 10, c)
    cv.icon(ic, 34, 71, 20, BG, 2.6)
    cv.text(74, 81, msg, 13.5, "s", TXT, valign="mid", maxw=W - 110)


def result_card(cv, bet, payout, mult, label="", y=None):
    """Carte de résultat en bas de l'écran de jeu."""
    delta = payout - bet
    y = y if y is not None else H - 168
    if delta > 0:
        c, bgc, line, title = GREEN, GREEN_BG, GREEN_LINE, "GAGNÉ"
    elif delta == 0:
        c, bgc, line, title = MUT, SURF2, LINE, "REMBOURSÉ"
    else:
        c, bgc, line, title = RED_SOFT, RED_BG, "#5A2028", "PERDU"
    cv.shadow(14, y, W - 28, 116, 24, 18, 160)
    cv.rr(14, y, W - 28, 116, 24, bgc)
    cv.rr(14.5, y + 0.5, W - 29, 115, 24, line, stroke=1.2)
    cv.text(34, y + 18, title, 12, "x", c)
    cv.text(34, y + 36, eur(delta, sign=True) if delta else eur(payout), 34, "b", TXT, maxw=210)
    cv.text(W - 34, y + 20, xfmt(mult), 18, "b", c, anchor="r")
    if label:
        cv.text(W - 34, y + 48, label, 12, "m", MUT, anchor="r", maxw=130)
    cv.text(34, y + 86, f"Mise {eur(bet)}  ·  Versé {eur(payout)}", 12, "m", MUT, maxw=W - 70)


def avatar(cv, x, y, r, name, ring=GOLD, bg="#3A2F6B"):
    cv.circ(x, y, r + 4, ring)
    cv.circ(x, y, r + 1.5, BG)
    cv.circ(x, y, r, bg)
    cv.text(x, y, (name[:1] or "?").upper(), r * 0.8, "b", TXT, anchor="c", valign="mid")


def app_icon(cv, x, y, size, color, icon, label=None, label_color=TXT):
    r = size * 0.27
    cv.shadow(x, y, size, size, r, 8, 120, 5)
    cv.rr(x, y, size, size, r, color, shader=cv.lin(x, y, x, y + size, mix(color, "#FFFFFF", 0.12), mix(color, "#000000", 0.12)))
    cv.icon(icon, x + size * 0.25, y + size * 0.25, size * 0.5, "#FFFFFF", 2.1)
    if label:
        cv.text(x + size / 2, y + size + 7, label, 11.5, "m", label_color, anchor="c", maxw=size + 16)


def sparkline(cv, x, y, w, h, values, color, sw=2, fill=True):
    if not values or len(values) < 2:
        cv.line(x, y + h / 2, x + w, y + h / 2, color, sw, 120)
        return
    lo, hi = min(values), max(values)
    rng = (hi - lo) or 1
    pts = [(x + i * w / (len(values) - 1), y + h - (v - lo) / rng * h) for i, v in enumerate(values)]
    if fill:
        p = skia.Path()
        p.moveTo(pts[0][0], y + h)
        for q in pts:
            p.lineTo(*q)
        p.lineTo(pts[-1][0], y + h)
        p.close()
        cv.path(p, color, shader=cv.lin(0, y, 0, y + h, color, color, 70, 0))
    cv.poly(pts, color, sw)


def progress(cv, x, y, w, h, pct, color=GOLD, bg=LINE):
    cv.rr(x, y, w, h, h / 2, bg)
    if pct > 0:
        cv.rr(x, y, max(h, w * min(1, pct)), h, h / 2, color)


# ---------- Cartes à jouer ----------
RED_SUITS = ("H", "D")


def suit(cv, s, x, y, size, color):
    if s == "C":
        k = size / 24
        for cx, cy in ((12, 7.5), (7, 13), (17, 13)):
            cv.circ(x + cx * k, y + cy * k, 4.6 * k, color)
        cv.shape("M10.6 12L9 22H15L13.4 12Z", x, y, size, color)
    else:
        cv.shape(SUIT_PATHS[s], x, y, size, color)


def playing_card(cv, x, y, w, h, rank=None, s=None, hidden=False, dim=False, glow=None, rot=0):
    cv.c.save()
    if rot:
        cv.c.rotate(rot, x + w / 2, y + h / 2)
    cv.shadow(x, y, w, h, w * 0.12, 10, 140, 6)
    if glow:
        cv.rr(x - 3, y - 3, w + 6, h + 6, w * 0.14, glow)
    if hidden:
        cv.rr(x, y, w, h, w * 0.12, "#7C2430")
        cv.rr(x + 5, y + 5, w - 10, h - 10, w * 0.08, "#A8404E", stroke=1.5)
        cv.circ(x + w / 2, y + h / 2, w * 0.16, "#A8404E", stroke=1.5)
    else:
        cv.rr(x, y, w, h, w * 0.12, "#FAFAF7")
        color = "#C8202F" if s in RED_SUITS else "#111318"
        rs = w * 0.27
        cv.text(x + w * 0.11, y + h * 0.06, rank, rs, "b", color)
        suit(cv, s, x + w * 0.1, y + h * 0.06 + rs * 1.15, w * 0.2, color)
        suit(cv, s, x + w / 2 - w * 0.22, y + h / 2 - w * 0.12, w * 0.44, color)
        if dim:
            cv.rr(x, y, w, h, w * 0.12, "#000000", 140)
    cv.c.restore()
