"""
casino_gfx.py — moteur graphique "Stake-like" du bot casino (Pillow uniquement).

- Rendu en double résolution puis réduit (bords lisses, anti-aliasing)
- Ombres portées, halos lumineux, dégradés, sphères, textures (bruit, feutre)
- Palette navy façon Stake, tuiles en relief, cartes et jetons réalistes
Chaque jeu = une fonction render_<jeu>(c, ...) qui renvoie une image RGB 960x540.
"""

import os
import math
import random
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, SS = 960, 540, 2

# ---------- Palette ----------
BG1, BG2 = (20, 41, 56), (9, 20, 29)
PANEL = (19, 36, 49)
PANEL_LINE = (44, 68, 84)
TILE, TILE_TOP, TILE_EDGE = (47, 69, 83), (63, 90, 107), (30, 48, 60)
SUNK = (15, 29, 40)
MUTED = (150, 165, 190)
WHITE = (255, 255, 255)
GREEN, GREEN_D = (0, 231, 1), (0, 160, 20)
RED, RED_D = (255, 64, 92), (170, 25, 50)
GOLD, GOLD_D = (255, 200, 45), (190, 120, 10)
PURPLE, BLUE, ORANGE = (150, 80, 255), (40, 145, 255), (255, 140, 30)
CY = 275

FONT_DIRS = [os.environ.get("CASINO_FONTS", ""), os.path.join(os.environ.get("DATA_DIR", ""), "fonts")]
_FONTS = {}


def set_fonts_dir(path):
    FONT_DIRS.insert(0, path)
    _FONTS.clear()


def font(size, weight="Bold"):
    key = (size, weight)
    if key not in _FONTS:
        f = None
        for d in FONT_DIRS:
            p = os.path.join(d, f"Poppins-{weight}.ttf") if d else ""
            if p and os.path.exists(p):
                f = ImageFont.truetype(p, int(size * SS))
                break
        if f is None:
            try:
                f = ImageFont.load_default(size=int(size * SS))
            except TypeError:
                f = ImageFont.load_default()
        _FONTS[key] = f
    return _FONTS[key]


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def A(c, a):
    return (c[0], c[1], c[2], int(a))


def _blur(layer, radius):
    if radius <= 0:
        return layer
    f = 4 if radius >= 6 else 2
    w, h = max(1, layer.width // f), max(1, layer.height // f)
    small = layer.resize((w, h), Image.BILINEAR).filter(ImageFilter.GaussianBlur(radius * SS / f))
    return small.resize(layer.size, Image.BILINEAR)


@lru_cache(maxsize=64)
def _sphere_mask(d):
    g = Image.radial_gradient("L").resize((d * 2, d * 2), Image.BILINEAR)
    o = int(d * 0.65)
    return g.crop((o, o, o + d, o + d))


@lru_cache(maxsize=64)
def _circle_mask(d):
    m = Image.new("L", (d * 4, d * 4), 0)
    ImageDraw.Draw(m).ellipse([0, 0, d * 4 - 1, d * 4 - 1], fill=255)
    return m.resize((d, d), Image.LANCZOS)


class G:
    """Toile en coordonnées logiques (960x540), dessinée en x2."""

    def __init__(self, img, ox=0, oy=0):
        self.img, self.ox, self.oy = img, ox, oy
        self.d = ImageDraw.Draw(img, "RGBA")

    def X(self, x):
        return (x - self.ox) * SS

    def Y(self, y):
        return (y - self.oy) * SS

    def B(self, b):
        return [self.X(b[0]), self.Y(b[1]), self.X(b[2]), self.Y(b[3])]

    def P(self, pts):
        return [(self.X(x), self.Y(y)) for x, y in pts]

    # ----- primitives -----
    def rect(self, b, r=0, fill=None, outline=None, width=1):
        self.d.rounded_rectangle(self.B(b), radius=r * SS, fill=fill, outline=outline, width=int(width * SS) if outline else 0)

    def ellipse(self, b, fill=None, outline=None, width=1):
        self.d.ellipse(self.B(b), fill=fill, outline=outline, width=int(width * SS) if outline else 0)

    def circle(self, cx, cy, r, fill=None, outline=None, width=1):
        self.ellipse((cx - r, cy - r, cx + r, cy + r), fill, outline, width)

    def poly(self, pts, fill=None, outline=None):
        self.d.polygon(self.P(pts), fill=fill, outline=outline)

    def line(self, pts, fill, width=1, joint=None):
        self.d.line(self.P(pts), fill=fill, width=max(1, int(width * SS)), joint=joint)

    def pie(self, b, a0, a1, fill=None, outline=None, width=1):
        self.d.pieslice(self.B(b), a0, a1, fill=fill, outline=outline, width=int(width * SS) if outline else 0)

    def text(self, xy, s, size, weight="Bold", fill=WHITE, anchor="la", stroke=0, sfill=None):
        self.d.text((self.X(xy[0]), self.Y(xy[1])), str(s), font=font(size, weight), fill=fill, anchor=anchor,
                    stroke_width=int(stroke * SS), stroke_fill=sfill)

    def tlen(self, s, size, weight="Bold"):
        return self.d.textlength(str(s), font=font(size, weight)) / SS

    # ----- effets -----
    def effect(self, b, blur, fn, offset=(0, 0)):
        m = blur * 3 + 4
        x0, y0, x1, y1 = b[0] - m, b[1] - m, b[2] + m, b[3] + m
        layer = Image.new("RGBA", (max(1, int((x1 - x0) * SS)), max(1, int((y1 - y0) * SS))), (0, 0, 0, 0))
        fn(G(layer, x0, y0))
        layer = _blur(layer, blur)
        self.img.paste(layer, (int(self.X(x0 + offset[0])), int(self.Y(y0 + offset[1]))), layer)

    def shadow(self, b, r=12, blur=10, offset=(0, 8), alpha=150):
        self.effect(b, blur, lambda g: g.rect(b, r, fill=(0, 0, 0, alpha)), offset)

    def glow(self, b, color, blur=14, r=None, alpha=170, ellipse=False):
        def fn(g):
            if ellipse:
                g.ellipse(b, fill=A(color, alpha))
            else:
                g.rect(b, r if r is not None else 12, fill=A(color, alpha))
        self.effect(b, blur, fn)

    def glow_text(self, xy, s, size, color, weight="ExtraBold", anchor="mm", blur=12, alpha=200):
        w = self.tlen(s, size, weight)
        b = (xy[0] - w, xy[1] - size, xy[0] + w, xy[1] + size)
        self.effect(b, blur, lambda g: g.text(xy, s, size, weight, A(color, alpha), anchor))
        self.text(xy, s, size, weight, color, anchor)

    def grad(self, b, c1, c2, r=0, vertical=True):
        w, h = int((b[2] - b[0]) * SS), int((b[3] - b[1]) * SS)
        if w <= 0 or h <= 0:
            return
        base = Image.linear_gradient("L")
        if not vertical:
            base = base.rotate(90)
        mask_g = base.resize((w, h), Image.BILINEAR)
        im = Image.composite(Image.new("RGB", (w, h), c2[:3]), Image.new("RGB", (w, h), c1[:3]), mask_g)
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=r * SS, fill=255)
        self.img.paste(im, (int(self.X(b[0])), int(self.Y(b[1]))), mask)

    def sphere(self, cx, cy, r, light, dark):
        d = max(2, int(r * 2 * SS))
        im = Image.composite(Image.new("RGB", (d, d), dark), Image.new("RGB", (d, d), light), _sphere_mask(d))
        self.img.paste(im, (int(self.X(cx - r)), int(self.Y(cy - r))), _circle_mask(d))

    def vfade(self, b, color, a0, a1):
        """Bande dégradée en transparence (haut a0 -> bas a1)."""
        y0, y1 = self.Y(b[1]), self.Y(b[3])
        n = max(1, int(y1 - y0))
        for k in range(n):
            a = a0 + (a1 - a0) * k / n
            self.d.line([(self.X(b[0]), y0 + k), (self.X(b[2]), y0 + k)], fill=A(color, a))

    def hfade(self, b, color, a0, a1):
        x0, x1 = self.X(b[0]), self.X(b[2])
        n = max(1, int(x1 - x0))
        for k in range(n):
            a = a0 + (a1 - a0) * k / n
            self.d.line([(x0 + k, self.Y(b[1])), (x0 + k, self.Y(b[3]))], fill=A(color, a))

    def finish(self):
        return self.img.resize((W, H), Image.LANCZOS)


# ---------- Fonds ----------

@lru_cache(maxsize=24)
def _bg(accent):
    im = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(im)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=mix(BG1, BG2, y / H))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([-260, -320, 520, 260], fill=A(accent, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    im.paste(glow, (0, 0), glow)
    noise = Image.effect_noise((W, H), 22).convert("RGB")
    im = Image.blend(im, noise, 0.035)
    return im


@lru_cache(maxsize=4)
def _felt(w, h, base):
    im = Image.new("RGB", (w, h), base)
    g = Image.radial_gradient("L").resize((w, h), Image.BILINEAR)
    dark = Image.new("RGB", (w, h), mix(base, (0, 0, 0), 0.55))
    im = Image.composite(dark, im, g)
    noise = Image.effect_noise((w, h), 40).convert("RGB")
    return Image.blend(im, noise, 0.06)


class C:
    """Contexte commun d'une image."""

    def __init__(self, title, accent, bet, balance, status=None, status_kind="info", subtitle="Monnaie virtuelle · provably fair"):
        self.title, self.accent, self.bet, self.balance = title, accent, bet, balance
        self.status, self.kind, self.subtitle = status, status_kind, subtitle


def fmt(n):
    return f"{int(n):,}".replace(",", " ")


def frame(c, felt=None):
    img = _bg(c.accent).resize((W * SS, H * SS), Image.BILINEAR)
    g = G(img)
    # badge + titre
    g.shadow((24, 18, 70, 64), r=12, blur=6, offset=(0, 4), alpha=120)
    g.grad((24, 18, 70, 64), mix(c.accent, WHITE, 0.25), mix(c.accent, (0, 0, 0), 0.25), r=12)
    g.text((47, 41), c.title[0], 26, "ExtraBold", WHITE, "mm")
    g.text((84, 17), c.title, 27, "ExtraBold", WHITE)
    g.text((85, 52), c.subtitle, 12, "Medium", MUTED)
    # statut
    if c.status:
        col = {"win": GREEN, "lose": RED, "push": MUTED, "info": c.accent}.get(c.kind, c.accent)
        tw = g.tlen(c.status, 15, "SemiBold")
        b = (936 - tw - 36, 22, 936, 58)
        if c.kind in ("win", "lose"):
            g.glow(b, col, blur=10, r=18, alpha=90)
        g.rect(b, 18, fill=A(col, 38), outline=A(col, 160), width=1.5)
        g.text(((b[0] + b[2]) / 2, 40), c.status, 15, "SemiBold", col if c.kind != "info" else WHITE, "mm")
    # panneau central
    pb = (24, 80, 936, 466)
    g.shadow(pb, r=20, blur=14, offset=(0, 10), alpha=120)
    if felt:
        fw, fh = int((pb[2] - pb[0]) * SS), int((pb[3] - pb[1]) * SS)
        f = _felt(fw, fh, felt)
        mask = Image.new("L", (fw, fh), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, fw - 1, fh - 1], radius=20 * SS, fill=255)
        img.paste(f, (int(g.X(pb[0])), int(g.Y(pb[1]))), mask)
        g.rect((34, 90, 926, 456), 16, outline=A(GOLD, 70), width=1.5)
    else:
        g.rect(pb, 20, fill=A(PANEL, 235), outline=A(PANEL_LINE, 255), width=1)
        g.vfade((26, 82, 934, 140), WHITE, 10, 0)
    # pied de page
    _field(g, (24, 478, 300, 528), "Mise", fmt(c.bet), chip=c.accent)
    _field(g, (660, 478, 936, 528), "Solde", fmt(c.balance), chip=None, right=True)
    return g


def _field(g, b, label, value, chip=None, right=False):
    g.rect(b, 10, fill=(13, 27, 38), outline=A(TILE, 255), width=1.5)
    g.text((b[0] + 14, b[1] + 8), label.upper(), 10, "SemiBold", MUTED)
    if chip:
        draw_chip(g, b[2] - 26, (b[1] + b[3]) / 2, 13, chip, shadow=False)
    g.text((b[0] + 14, b[1] + 21), value, 18, "Bold", WHITE)


def stat_box(g, b, label, value, color=WHITE, bar=None, bar_col=GREEN):
    g.rect(b, 10, fill=(13, 27, 38), outline=A(TILE, 255), width=1.5)
    g.text((b[0] + 14, b[1] + 9), label.upper(), 10, "SemiBold", MUTED)
    g.text((b[0] + 14, b[1] + 25), value, 20, "Bold", color)
    if bar is not None:
        x0, x1, y = b[0] + 14, b[2] - 14, b[3] - 9
        g.rect((x0, y - 3, x1, y + 3), 3, fill=(35, 52, 65))
        g.rect((x0, y - 3, x0 + (x1 - x0) * max(0.02, min(1, bar)), y + 3), 3, fill=bar_col)


def pill(g, cx, cy, text, color, size=15, fill_a=40, solid=False):
    w = g.tlen(text, size, "Bold") + 30
    b = (cx - w / 2, cy - size - 2, cx + w / 2, cy + size + 2)
    if solid:
        g.rect(b, size + 2, fill=color)
        g.text((cx, cy), text, size, "Bold", (10, 20, 28), "mm")
    else:
        g.rect(b, size + 2, fill=A(color, fill_a), outline=A(color, 150), width=1.5)
        g.text((cx, cy), text, size, "Bold", color, "mm")
    return b


# ---------- Éléments réutilisables ----------

def tile(g, b, face=TILE, top=TILE_TOP, edge=TILE_EDGE, r=10, lift=4, outline=None):
    g.rect((b[0], b[1] + lift, b[2], b[3] + lift), r, fill=edge)
    g.grad(b, top, face, r=r)
    g.rect(b, r, outline=outline or A(WHITE, 18), width=1)


def sunk(g, b, r=10, fill=SUNK, outline=None):
    g.rect((b[0], b[1] + 4, b[2], b[3] + 4), r, fill=fill, outline=outline or A(WHITE, 10), width=1)


def gem(g, cx, cy, s, col, glow=True, alpha=255):
    if glow:
        g.glow((cx - s, cy - s, cx + s, cy + s), col, blur=s * 0.5, alpha=110 * alpha / 255, ellipse=True)
    hi, mid, lo = mix(col, WHITE, 0.55), col, mix(col, (0, 0, 0), 0.35)
    dk = mix(col, (0, 0, 0), 0.55)
    top, ml, mr = cy - s * 0.62, cx - s, cx + s
    belt = cy - s * 0.12
    tl, tr = cx - s * 0.5, cx + s * 0.5
    bottom = cy + s
    a = int(alpha)
    g.poly([(tl, top), (tr, top), (mr, belt), (ml, belt)], fill=A(mid, a))
    g.poly([(tl, top), (cx, belt), (ml, belt)], fill=A(hi, a))
    g.poly([(tl, top), (tr, top), (cx, belt)], fill=A(mix(hi, mid, 0.4), a))
    g.poly([(tr, top), (mr, belt), (cx, belt)], fill=A(lo, a))
    g.poly([(ml, belt), (cx, belt), (cx, bottom)], fill=A(mix(mid, WHITE, 0.15), a))
    g.poly([(cx, belt), (mr, belt), (cx, bottom)], fill=A(dk, a))
    g.line([(ml, belt), (mr, belt)], A(WHITE, 70 * a / 255), 1)
    if alpha > 200:
        sparkle(g, tl + s * 0.12, top + s * 0.3, s * 0.22)


def sparkle(g, cx, cy, s):
    g.poly([(cx, cy - s), (cx + s * 0.22, cy - s * 0.22), (cx + s, cy), (cx + s * 0.22, cy + s * 0.22),
            (cx, cy + s), (cx - s * 0.22, cy + s * 0.22), (cx - s, cy), (cx - s * 0.22, cy - s * 0.22)], fill=A(WHITE, 230))


def bomb(g, cx, cy, s, lit=True, alpha=255):
    if lit:
        g.glow((cx - s * 1.3, cy - s * 1.3, cx + s * 1.3, cy + s * 1.3), RED, blur=s * 0.8, alpha=150, ellipse=True)
    g.sphere(cx, cy + s * 0.1, s, (110, 115, 130) if alpha > 200 else (70, 74, 84), (14, 16, 22))
    g.rect((cx + s * 0.25, cy - s * 0.95, cx + s * 0.75, cy - s * 0.55), 2, fill=(70, 74, 84))
    g.line([(cx + s * 0.5, cy - s * 0.9), (cx + s * 0.8, cy - s * 1.25), (cx + s * 1.05, cy - s * 1.15)], (210, 170, 110), 2.5)
    if lit:
        g.glow((cx + s * 0.85, cy - s * 1.45, cx + s * 1.25, cy - s * 1.05), ORANGE, blur=5, alpha=230, ellipse=True)
        sparkle(g, cx + s * 1.05, cy - s * 1.25, s * 0.35)


def draw_chip(g, cx, cy, r, col, shadow=True):
    if shadow:
        g.effect((cx - r, cy - r, cx + r, cy + r), 4, lambda l: l.circle(cx, cy + 3, r, fill=(0, 0, 0, 140)))
    g.circle(cx, cy, r, fill=col)
    for k in range(6):
        a = k * math.pi / 3
        p = [(cx + math.cos(a + da) * rr, cy + math.sin(a + da) * rr) for da, rr in ((-0.2, r), (0.2, r), (0.16, r * 0.72), (-0.16, r * 0.72))]
        g.poly(p, fill=A(WHITE, 235))
    g.circle(cx, cy, r * 0.62, fill=mix(col, (0, 0, 0), 0.15), outline=A(WHITE, 150), width=1)
    g.circle(cx, cy, r * 0.42, fill=mix(col, WHITE, 0.12))


def chip_stack(g, cx, cy, r, colors):
    for k, col in enumerate(colors):
        y = cy - k * r * 0.32
        g.ellipse((cx - r, y - r * 0.38 + r * 0.16, cx + r, y + r * 0.38 + r * 0.16), fill=mix(col, (0, 0, 0), 0.35))
        g.ellipse((cx - r, y - r * 0.38, cx + r, y + r * 0.38), fill=col)
        for j in range(6):
            a = j * math.pi / 3 + 0.3
            g.ellipse((cx + math.cos(a) * r * 0.86 - r * 0.09, y + math.sin(a) * r * 0.33 - r * 0.05,
                       cx + math.cos(a) * r * 0.86 + r * 0.09, y + math.sin(a) * r * 0.33 + r * 0.05), fill=A(WHITE, 220))
        g.ellipse((cx - r * 0.55, y - r * 0.2, cx + r * 0.55, y + r * 0.2), outline=A(WHITE, 120), width=1)


# ---------- Cartes ----------

def suit_shape(g, cx, cy, s, suit, col):
    if suit == "D":
        g.poly([(cx, cy - s), (cx + s * 0.72, cy), (cx, cy + s), (cx - s * 0.72, cy)], fill=col)
    elif suit == "H":
        r = s * 0.52
        g.circle(cx - r, cy - s * 0.65 + r, r, fill=col)
        g.circle(cx + r, cy - s * 0.65 + r, r, fill=col)
        g.poly([(cx - 2 * r + s * 0.02, cy - s * 0.05), (cx + 2 * r - s * 0.02, cy - s * 0.05), (cx, cy + s)], fill=col)
    elif suit == "S":
        r = s * 0.5
        g.circle(cx - r, cy - s * 0.35 + r, r, fill=col)
        g.circle(cx + r, cy - s * 0.35 + r, r, fill=col)
        g.poly([(cx - 2 * r + s * 0.02, cy + s * 0.1), (cx + 2 * r - s * 0.02, cy + s * 0.1), (cx, cy - s)], fill=col)
        g.poly([(cx, cy + s * 0.15), (cx - s * 0.35, cy + s), (cx + s * 0.35, cy + s)], fill=col)
    else:
        r = s * 0.4
        for ox, oy in ((0, -s * 0.46), (-s * 0.48, s * 0.12), (s * 0.48, s * 0.12)):
            g.circle(cx + ox, cy + oy, r, fill=col)
        g.poly([(cx, cy), (cx - s * 0.32, cy + s), (cx + s * 0.32, cy + s)], fill=col)


def card(g, x, y, w, h, crd=None, face_up=True, glow_col=None, dim=False):
    if glow_col:
        g.glow((x, y, x + w, y + h), glow_col, blur=12, r=12, alpha=200)
    g.shadow((x, y, x + w, y + h), r=10, blur=8, offset=(0, 7), alpha=150)
    if not face_up:
        g.grad((x, y, x + w, y + h), (34, 70, 120), (16, 34, 66), r=10)
        g.rect((x + 6, y + 6, x + w - 6, y + h - 6), 7, outline=A(WHITE, 120), width=1.5)
        step = 12
        for k in range(-int(h), int(w), step):
            g.line([(max(x + 8, x + 8 + k), y + 8 + max(0, -k)), (min(x + w - 8, x + 8 + k + h), y + 8 + min(h - 16, x + w - 16 - k))], A(WHITE, 22), 1)
        gem(g, x + w / 2, y + h / 2, min(w, h) * 0.16, (90, 200, 255), glow=False)
        return
    rank, suit = crd
    red = suit in ("H", "D")
    col = (205, 30, 45) if red else (22, 26, 34)
    g.grad((x, y, x + w, y + h), (255, 255, 255), (232, 235, 240), r=10)
    g.rect((x, y, x + w, y + h), 10, outline=(200, 205, 214), width=1)
    fs = h * 0.17
    g.text((x + w * 0.1, y + h * 0.04), rank, fs, "Bold", col)
    suit_shape(g, x + w * 0.1 + fs * 0.36, y + h * 0.32, fs * 0.36, suit, col)
    # coin inférieur (inversé)
    g.text((x + w * 0.9, y + h * 0.96), rank, fs, "Bold", col, "rb")
    suit_shape(g, x + w * 0.9 - fs * 0.36, y + h * 0.68, fs * 0.36, suit, col)
    if rank in ("J", "Q", "K"):
        fx0, fy0, fx1, fy1 = x + w * 0.24, y + h * 0.2, x + w * 0.76, y + h * 0.8
        g.grad((fx0, fy0, fx1, fy1), mix(col, WHITE, 0.82), mix(col, WHITE, 0.6), r=6)
        g.rect((fx0, fy0, fx1, fy1), 6, outline=A(col, 200), width=1.5)
        g.text(((fx0 + fx1) / 2, (fy0 + fy1) / 2 - h * 0.06), rank, h * 0.3, "ExtraBold", col, "mm")
        suit_shape(g, (fx0 + fx1) / 2, fy1 - h * 0.12, h * 0.07, suit, col)
        # couronne
        cxm, cyt = (fx0 + fx1) / 2, fy0 + h * 0.07
        g.poly([(cxm - w * 0.13, cyt + h * 0.04), (cxm - w * 0.13, cyt - h * 0.02), (cxm - w * 0.06, cyt + h * 0.01), (cxm, cyt - h * 0.04),
                (cxm + w * 0.06, cyt + h * 0.01), (cxm + w * 0.13, cyt - h * 0.02), (cxm + w * 0.13, cyt + h * 0.04)], fill=GOLD_D)
    elif rank == "A":
        suit_shape(g, x + w / 2, y + h / 2, h * 0.2, suit, col)
    else:
        suit_shape(g, x + w / 2, y + h / 2, h * 0.15, suit, col)
    if dim:
        g.rect((x, y, x + w, y + h), 10, fill=(10, 20, 30, 120))


# ---------- Symboles de slots ----------

def slot_symbol(g, sym, cx, cy, s, alpha=255):
    if sym == "cherry":
        g.line([(cx - s * 0.32, cy + s * 0.05), (cx + s * 0.05, cy - s * 0.75), (cx + s * 0.38, cy + s * 0.1)], (60, 140, 50), 4, joint="curve")
        g.poly([(cx + s * 0.05, cy - s * 0.75), (cx + s * 0.55, cy - s * 0.85), (cx + s * 0.3, cy - s * 0.5)], fill=(80, 180, 70))
        g.sphere(cx - s * 0.36, cy + s * 0.32, s * 0.36, (255, 120, 130), (150, 0, 25))
        g.sphere(cx + s * 0.38, cy + s * 0.38, s * 0.36, (255, 120, 130), (150, 0, 25))
    elif sym == "lemon":
        g.sphere(cx, cy, s * 0.72, (255, 248, 160), (215, 160, 0))
        g.poly([(cx + s * 0.62, cy - s * 0.1), (cx + s * 0.88, cy), (cx + s * 0.62, cy + s * 0.1)], fill=(215, 170, 10))
    elif sym == "grape":
        for ox, oy in ((-0.38, -0.35), (0, -0.4), (0.38, -0.35), (-0.2, 0.0), (0.2, 0.0), (-0.38, 0.32), (0.38, 0.32), (0, 0.36), (0, 0.72)):
            g.sphere(cx + ox * s, cy + oy * s, s * 0.24, (210, 150, 255), (80, 20, 140))
        g.poly([(cx - s * 0.05, cy - s * 0.62), (cx + s * 0.4, cy - s * 0.95), (cx + s * 0.2, cy - s * 0.55)], fill=(80, 170, 70))
    elif sym == "bell":
        g.poly([(cx - s * 0.7, cy + s * 0.5), (cx - s * 0.45, cy - s * 0.35), (cx - s * 0.2, cy - s * 0.68), (cx + s * 0.2, cy - s * 0.68),
                (cx + s * 0.45, cy - s * 0.35), (cx + s * 0.7, cy + s * 0.5)], fill=(235, 165, 20))
        g.poly([(cx - s * 0.45, cy + s * 0.45), (cx - s * 0.28, cy - s * 0.3), (cx - s * 0.1, cy - s * 0.55), (cx, cy - s * 0.55), (cx - s * 0.15, cy + s * 0.45)],
               fill=(255, 225, 120))
        g.rect((cx - s * 0.75, cy + s * 0.42, cx + s * 0.75, cy + s * 0.58), 4, fill=(190, 120, 10))
        g.sphere(cx, cy + s * 0.7, s * 0.16, (255, 220, 120), (150, 90, 0))
    elif sym == "star":
        pts, pts2 = [], []
        for k in range(10):
            a = -math.pi / 2 + k * math.pi / 5
            rr = s * 0.85 if k % 2 == 0 else s * 0.38
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
            pts2.append((cx + rr * 0.55 * math.cos(a), cy - s * 0.05 + rr * 0.55 * math.sin(a)))
        g.poly(pts, fill=(245, 175, 0))
        g.poly(pts2, fill=(255, 235, 120))
    elif sym == "diamond":
        gem(g, cx, cy, s * 0.8, (60, 170, 255), glow=False)
    elif sym == "seven":
        g.text((cx + 3, cy + 4), "7", s * 1.8, "ExtraBold", (90, 0, 10), "mm")
        g.text((cx, cy), "7", s * 1.8, "ExtraBold", (235, 30, 45), "mm", stroke=2.5, sfill=(255, 210, 90))
    else:
        g.text((cx, cy), "?", s * 1.3, "ExtraBold", (150, 155, 170), "mm")
    if alpha < 255:
        pass


# ======================================================================
#                               JEUX
# ======================================================================

def render_betsetup(c, game_desc):
    g = frame(c)
    chip_stack(g, 190, 330, 70, [(200, 40, 50), (30, 120, 220), (30, 160, 80), GOLD_D, (200, 40, 50), (120, 60, 200)])
    g.text((590, 140), "TA MISE", 15, "SemiBold", MUTED, "mm")
    g.glow_text((590, 212), fmt(c.bet), 72, c.accent)
    words, lines, cur = game_desc.split(), [], ""
    for w_ in words:
        if g.tlen(cur + " " + w_, 15, "Medium") > 520 and cur:
            lines.append(cur)
            cur = w_
        else:
            cur = (cur + " " + w_).strip()
    lines.append(cur)
    for k, ln in enumerate(lines[:2]):
        g.text((590, 280 + k * 22), ln, 15, "Medium", MUTED, "mm")
    for k, lab in enumerate(["½", "2×", "Max"]):
        pill(g, 500 + k * 90, 362, lab, MUTED, 14, fill_a=25)
    g.text((590, 414), "Ajuste ta mise puis appuie sur Jouer", 13, "Medium", A(MUTED, 200), "mm")
    return g.finish()


def render_coinflip(c, face=None, side=None):
    g = frame(c)
    cx, cy, r = 480, 262, 112
    gold = face != "face"
    rim = (190, 125, 15) if gold else (130, 140, 155)
    light, dark = ((255, 236, 140), (215, 150, 10)) if gold else ((245, 248, 255), (150, 160, 178))
    if face and c.kind in ("win", "lose"):
        g.glow((cx - r - 10, cy - r - 10, cx + r + 10, cy + r + 10), GREEN if c.kind == "win" else RED, blur=26, alpha=150, ellipse=True)
    g.effect((cx - r, cy, cx + r, cy + r + 40), 12, lambda l: l.ellipse((cx - r * 0.9, cy + r + 4, cx + r * 0.9, cy + r + 34), fill=(0, 0, 0, 170)))
    g.circle(cx, cy + 10, r, fill=rim)
    g.sphere(cx, cy, r, light, dark)
    g.circle(cx, cy, r * 0.8, outline=A(mix(dark, (0, 0, 0), 0.2), 200), width=3)
    for k in range(40):
        a = k * math.pi / 20
        g.line([(cx + math.cos(a) * r * 0.86, cy + math.sin(a) * r * 0.86), (cx + math.cos(a) * r * 0.94, cy + math.sin(a) * r * 0.94)],
               A(mix(dark, (0, 0, 0), 0.1), 160), 1.5)
    label = {"pile": "PILE", "face": "FACE"}.get(face, "?")
    size = 40 if face else 84
    g.text((cx + 2, cy + 3), label, size, "ExtraBold", A(mix(dark, (0, 0, 0), 0.4), 200), "mm")
    g.text((cx, cy), label, size, "ExtraBold", A(mix(light, WHITE, 0.4), 255), "mm")
    for k, (lab, key) in enumerate((("PILE", "pile"), ("FACE", "face"))):
        x = 200 if k == 0 else 760
        on = face == key
        b = (x - 90, 230, x + 90, 300)
        if on:
            g.glow(b, GREEN if c.kind == "win" else RED, blur=10, r=14, alpha=110)
        tile(g, b, r=14) if not on else g.rect(b, 14, fill=A(GREEN if c.kind == "win" else RED, 60), outline=GREEN if c.kind == "win" else RED, width=2)
        g.text((x, 252), lab, 20, "ExtraBold", WHITE, "mm")
        g.text((x, 280), "x1.98", 14, "SemiBold", MUTED, "mm")
    return g.finish()


def render_dice(c, target, direction, roll=None, mult=None, chance=None):
    g = frame(c)
    for k, (lab, val) in enumerate((("Multiplicateur", f"x{mult:.4f}"), ("Cible " + ("au-dessus" if direction == "over" else "en dessous"), f"{target:.2f}"),
                                    ("Chance de gain", f"{chance:.2f} %"))):
        x0 = 60 + k * 285
        stat_box(g, (x0, 104, x0 + 265, 160), lab, val)
    x0, x1, y = 90, 870, 330
    for v in (0, 25, 50, 75, 100):
        xx = x0 + (x1 - x0) * v / 100
        g.text((xx, 380), str(v), 13, "SemiBold", MUTED, "mm")
        g.line([(xx, y + 18), (xx, y + 26)], A(MUTED, 120), 1.5)
    g.rect((x0 - 14, y - 26, x1 + 14, y + 26), 26, fill=(13, 27, 38), outline=A(TILE, 255), width=1.5)
    tx = x0 + (x1 - x0) * target / 100
    lose_b, win_b = ((x0, y - 8, tx, y + 8), (tx, y - 8, x1, y + 8)) if direction == "over" else ((tx, y - 8, x1, y + 8), (x0, y - 8, tx, y + 8))
    g.grad(lose_b, (255, 90, 110), RED_D, r=8)
    g.grad(win_b, (60, 255, 80), GREEN_D, r=8)
    g.shadow((tx - 17, y - 22, tx + 17, y + 22), r=8, blur=5, offset=(0, 4), alpha=160)
    g.grad((tx - 17, y - 22, tx + 17, y + 22), (120, 190, 255), (30, 110, 230), r=8)
    for dx in (-6, 0, 6):
        g.line([(tx + dx, y - 9), (tx + dx, y + 9)], A(WHITE, 200), 2)
    if roll is not None:
        rx = x0 + (x1 - x0) * roll / 100
        win = (roll > target) if direction == "over" else (roll < target)
        col = GREEN if win else RED
        b = (rx - 52, 208, rx + 52, 262)
        g.glow(b, col, blur=14, r=12, alpha=150)
        g.grad(b, mix(col, WHITE, 0.25), mix(col, (0, 0, 0), 0.2), r=12)
        g.poly([(rx - 10, 261), (rx + 10, 261), (rx, 276)], fill=mix(col, (0, 0, 0), 0.2))
        g.text((rx, 235), f"{roll:.2f}", 26, "ExtraBold", (8, 18, 26), "mm")
    return g.finish()


@lru_cache(maxsize=1)
def _stars():
    rnd = random.Random(7)
    return [(rnd.uniform(40, 920), rnd.uniform(96, 450), rnd.uniform(0.6, 2.2), rnd.randint(60, 220)) for _ in range(140)]


def render_limbo(c, target, result=None):
    g = frame(c)
    for x, y, r, a in _stars():
        g.circle(x, y, r / 2, fill=A(WHITE, a))
    if result is None:
        g.text((480, 160), "MULTIPLICATEUR CIBLE", 14, "SemiBold", MUTED, "mm")
        g.glow_text((480, 248), f"{target:.2f}x", 92, c.accent, blur=18)
    else:
        col = GREEN if result >= target else RED
        g.glow_text((480, 238), f"{result:,.2f}x".replace(",", " "), 104, col, blur=22)
    pill(g, 370, 392, f"Cible x{target:.2f}", c.accent, 15)
    pill(g, 590, 392, f"Chance {99 / target:.2f} %", MUTED, 15)
    return g.finish()


WHEEL_PALETTE = {0: (52, 72, 88), 1.2: (50, 170, 230), 1.5: (0, 220, 90), 1.8: (255, 210, 40), 2: (255, 140, 30),
                 3: (175, 90, 255), 19.8: (255, 64, 92)}


def render_wheel(c, segments, landed=None, angle=0.0, risk="medium"):
    g = frame(c)
    cx, cy, r = 320, 274, 168
    n = len(segments)
    g.effect((cx - r, cy - r, cx + r, cy + r), 16, lambda l: l.circle(cx, cy + 12, r + 18, fill=(0, 0, 0, 170)))
    g.sphere(cx, cy, r + 18, (70, 90, 110), (16, 26, 36))
    for k in range(n):
        a0 = angle + k * 360 / n - 90
        col = WHEEL_PALETTE.get(segments[k], c.accent)
        if landed is not None and k != landed:
            col = mix(col, PANEL, 0.45)
        g.pie((cx - r, cy - r, cx + r, cy + r), a0, a0 + 360 / n, fill=col, outline=(14, 26, 36), width=2)
    g.circle(cx, cy, r * 0.74, fill=A((0, 0, 0), 60))
    for k in range(n):
        a = math.radians(angle + k * 360 / n - 90)
        g.circle(cx + math.cos(a) * (r + 9), cy + math.sin(a) * (r + 9), 3.2, fill=(255, 225, 140))
    g.sphere(cx, cy, r * 0.58, (40, 62, 78), (12, 24, 34))
    g.circle(cx, cy, r * 0.58, outline=A(WHITE, 30), width=2)
    if landed is not None:
        m = segments[landed]
        g.glow_text((cx, cy), f"{m:g}x", 44, WHEEL_PALETTE.get(m, c.accent), blur=10)
    else:
        g.text((cx, cy - 10), risk.upper(), 22, "ExtraBold", WHITE, "mm")
        g.text((cx, cy + 18), "RISQUE", 11, "SemiBold", MUTED, "mm")
    pts = [(cx, cy - r + 16), (cx - 18, cy - r - 22), (cx + 18, cy - r - 22)]
    g.effect((cx - 20, cy - r - 24, cx + 20, cy - r + 18), 4, lambda l: l.poly([(x, y + 4) for x, y in pts], fill=(0, 0, 0, 160)))
    g.poly(pts, fill=WHITE)
    g.circle(cx, cy - r - 18, 9, fill=WHITE)
    g.circle(cx, cy - r - 18, 4, fill=c.accent)
    vals = sorted(set(segments))
    g.text((610, 110), "SEGMENTS", 12, "SemiBold", MUTED)
    for k, m in enumerate(vals):
        y = 136 + k * 44
        cnt = segments.count(m)
        b = (610, y, 900, y + 36)
        on = landed is not None and segments[landed] == m
        g.rect(b, 10, fill=A(WHEEL_PALETTE.get(m, c.accent), 50 if on else 18), outline=A(WHEEL_PALETTE.get(m, c.accent), 200 if on else 60), width=1.5)
        g.circle(632, y + 18, 8, fill=WHEEL_PALETTE.get(m, c.accent))
        g.text((652, y + 18), f"{m:g}x", 17, "Bold", WHITE, "lm")
        g.text((888, y + 18), f"{cnt}/{len(segments)} · {cnt * 100 / len(segments):.0f} %", 13, "SemiBold", MUTED, "rm")
    return g.finish()


SLOT_NAMES = ["cherry", "lemon", "grape", "bell", "star", "diamond", "seven"]


def render_slots(c, reels=None, paytable=None, win=False):
    g = frame(c)
    cab = (150, 96, 810, 424)
    g.shadow(cab, r=26, blur=14, offset=(0, 10), alpha=170)
    g.grad(cab, (255, 220, 120), (170, 100, 10), r=26)
    g.grad((cab[0] + 10, cab[1] + 10, cab[2] - 10, cab[3] - 10), (40, 18, 18), (16, 8, 10), r=18)
    rw, gap = 182, 16
    x0 = 480 - (rw * 3 + gap * 2) / 2
    top, bot = 124, 396
    syms = reels if reels else [3, 6, 1]
    for k in range(3):
        x = x0 + k * (rw + gap)
        g.grad((x, top, x + rw, bot), (250, 250, 252), (222, 226, 234), r=10)
        mid = (top + bot) / 2
        cur = syms[k]
        for dy, idx in ((-96, (cur + 1) % 7), (0, cur), (96, (cur + 6) % 7)):
            slot_symbol(g, SLOT_NAMES[idx] if reels else (SLOT_NAMES[idx] if dy else None), x + rw / 2, mid + dy, 34)
        g.vfade((x, top, x + rw, top + 70), (0, 0, 0), 150, 0)
        g.vfade((x, bot - 70, x + rw, bot), (0, 0, 0), 0, 150)
        g.rect((x, top, x + rw, bot), 10, outline=A((0, 0, 0), 120), width=2)
    col = GREEN if win else (255, 60, 70)
    if win:
        g.glow((x0 - 6, 230, x0 + rw * 3 + gap * 2 + 6, 290), GREEN, blur=12, r=10, alpha=120)
    g.line([(x0 - 16, 260), (x0 + rw * 3 + gap * 2 + 16, 260)], A(col, 210), 3)
    g.poly([(x0 - 26, 250), (x0 - 12, 260), (x0 - 26, 270)], fill=col)
    g.poly([(x0 + rw * 3 + gap * 2 + 26, 250), (x0 + rw * 3 + gap * 2 + 12, 260), (x0 + rw * 3 + gap * 2 + 26, 270)], fill=col)
    for k in range(9):
        bx = 170 + k * 78
        g.circle(bx, 108, 4, fill=(255, 245, 200) if (k % 2 == 0) else (255, 170, 60))
    if paytable:
        g.text((480, 446), "3 identiques : " + "  ".join(paytable), 12, "SemiBold", MUTED, "mm")
    return g.finish()


def render_plinko(c, rows, table, path=None, risk="medium"):
    g = frame(c)
    n = len(table)
    top, bot = 112, 388
    bw = 820 / n
    x_left = 480 - bw * n / 2
    for row in range(rows):
        cnt = row + 3
        y = top + (bot - top) * row / rows
        span = bw * (cnt - 1)
        for k in range(cnt):
            x = 480 - span / 2 + k * bw
            g.circle(x, y, 4.2, fill=(235, 240, 250))
            g.circle(x - 1, y - 1, 1.6, fill=WHITE)
    if path is not None:
        pts = [(480, top - 22)]
        pos = 0.0
        for row, right in enumerate(path):
            pos += 0.5 if right else -0.5
            pts.append((480 + pos * bw, top + (bot - top) * (row + 0.5) / rows))
        landed = sum(path)
        pts.append((x_left + (landed + 0.5) * bw, bot + 24))
        for k in range(len(pts) - 1):
            g.line([pts[k], pts[k + 1]], A((255, 90, 140), 60 + 150 * k / len(pts)), 3)
        ex, ey = pts[-1]
        g.glow((ex - 14, ey - 14, ex + 14, ey + 14), (255, 70, 120), blur=8, alpha=200, ellipse=True)
        g.sphere(ex, ey, 10, (255, 170, 200), (200, 20, 80))
    for k in range(n):
        bx = x_left + k * bw
        m = table[k]
        t = abs(k - (n - 1) / 2) / ((n - 1) / 2)
        col = mix((255, 200, 0), (255, 30, 70), t ** 1.2)
        b = (bx + 2.5, bot + 36, bx + bw - 2.5, bot + 66)
        hit = path is not None and sum(path) == k
        if hit:
            g.glow(b, col, blur=10, r=6, alpha=200)
        g.rect((b[0], b[1] + 4, b[2], b[3] + 4), 6, fill=mix(col, (0, 0, 0), 0.4))
        g.grad((b[0], b[1] + (4 if hit else 0), b[2], b[3] + (4 if hit else 0)), mix(col, WHITE, 0.2), col, r=6)
        size = 11 if n > 13 else 13
        g.text(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2 + (4 if hit else 0)), f"{m:g}", size, "Bold", (25, 15, 10), "mm")
    pill(g, 120, 112, f"Risque {risk}", c.accent, 13)
    pill(g, 120, 152, f"{rows} lignes", MUTED, 13, fill_a=20)
    return g.finish()


GEM_COLORS = [(255, 70, 90), (255, 145, 30), (255, 215, 40), (40, 230, 90), (40, 150, 255), (170, 80, 255), (235, 245, 255)]


def render_diamonds(c, gems=None, label=None, mult=None, legend=None):
    g = frame(c)
    pw, gap = 138, 22
    x0 = 480 - (pw * 5 + gap * 4) / 2
    counts = {}
    if gems:
        for v in gems:
            counts[v] = counts.get(v, 0) + 1
    for k in range(5):
        x = x0 + k * (pw + gap)
        b = (x, 130, x + pw, 330)
        tile(g, b, r=16)
        g.vfade((x, 300, x + pw, 330), (0, 0, 0), 0, 80)
        if gems:
            matched = counts[gems[k]] > 1
            gem(g, x + pw / 2, 222, 46, GEM_COLORS[gems[k]], glow=matched, alpha=255 if matched or not mult else 170)
        else:
            gem(g, x + pw / 2, 222, 40, (70, 92, 110), glow=False)
    if label:
        col = GREEN if mult and mult >= 1 else (MUTED if mult else RED)
        pill(g, 480, 386, f"{label} · x{mult:g}", col, 18)
    elif legend:
        g.text((480, 386), legend, 13, "SemiBold", MUTED, "mm")
    return g.finish()


def rarity_color(m):
    if m >= 20:
        return GOLD
    if m >= 5:
        return (255, 80, 160)
    if m >= 2:
        return PURPLE
    if m >= 1:
        return BLUE
    return (110, 125, 140)


def render_case(c, reward=None, strip=None, mults=None):
    g = frame(c)
    if reward is None:
        cx, cy = 480, 268
        g.effect((cx - 160, cy + 80, cx + 160, cy + 120), 14, lambda l: l.ellipse((cx - 150, cy + 84, cx + 150, cy + 116), fill=(0, 0, 0, 170)))
        body = (cx - 150, cy - 30, cx + 150, cy + 100)
        lid = (cx - 160, cy - 100, cx + 160, cy - 26)
        g.grad(body, mix(c.accent, (60, 30, 0), 0.4), mix(c.accent, (0, 0, 0), 0.6), r=10)
        g.grad(lid, mix(c.accent, WHITE, 0.25), mix(c.accent, (40, 20, 0), 0.3), r=14)
        for bx in (cx - 105, cx + 75):
            g.grad((bx, lid[1], bx + 30, body[3]), (255, 235, 150), (180, 120, 20), r=4)
        g.grad((cx - 26, cy - 50, cx + 26, cy + 4), (255, 235, 150), (170, 110, 10), r=8)
        g.circle(cx, cy - 26, 7, fill=(60, 35, 0))
        g.rect((cx - 3, cy - 24, cx + 3, cy - 10), 2, fill=(60, 35, 0))
        g.vfade((lid[0], lid[1], lid[2], lid[1] + 20), WHITE, 70, 0)
        if mults:
            g.text((480, 438), "Gains possibles : " + "  ".join(f"{m:g}x" for m in mults), 12, "SemiBold", MUTED, "mm")
        return g.finish()
    iw, gap = 118, 12
    cy = 262
    centre = len(strip) // 2
    for k, m in enumerate(strip):
        x = 480 + (k - centre) * (iw + gap) - iw / 2
        if x > 940 or x + iw < 20:
            continue
        b = (x, cy - 70, x + iw, cy + 70)
        col = rarity_color(m)
        win = k == centre
        if win:
            g.glow(b, col, blur=16, r=12, alpha=210)
        g.grad(b, mix(col, (18, 30, 40), 0.55), (18, 30, 40), r=12)
        g.rect((b[0], b[3] - 6, b[2], b[3]), 3, fill=col)
        gem(g, x + iw / 2, cy - 14, 26, col, glow=False)
        g.text((x + iw / 2, cy + 40), f"{m:g}x", 20, "ExtraBold", WHITE, "mm")
        if win:
            g.rect(b, 12, outline=WHITE, width=2.5)
    g.hfade((26, cy - 80, 210, cy + 80), PANEL, 255, 0)
    g.hfade((750, cy - 80, 934, cy + 80), PANEL, 0, 255)
    g.poly([(468, cy - 98), (492, cy - 98), (480, cy - 80)], fill=GOLD)
    g.poly([(468, cy + 98), (492, cy + 98), (480, cy + 80)], fill=GOLD)
    g.line([(480, cy - 80), (480, cy - 72)], GOLD, 2)
    col = GREEN if reward >= 1 else RED
    pill(g, 480, 410, f"x{reward:g}", col, 20, solid=True)
    return g.finish()


def render_keno(c, picks, drawn=None, table=None):
    g = frame(c)
    cw, ch, gap = 62, 54, 8
    x0, y0 = 48, 104
    picks = set(picks)
    hits = len(picks & set(drawn)) if drawn else 0
    for n in range(1, 41):
        r, k = (n - 1) // 8, (n - 1) % 8
        x, y = x0 + k * (cw + gap), y0 + r * (ch + gap + 8)
        b = (x, y, x + cw, y + ch)
        picked, hit = n in picks, drawn is not None and n in drawn
        if hit and picked:
            g.glow(b, GREEN, blur=8, r=10, alpha=140)
            tile(g, b, face=(0, 170, 30), top=(70, 255, 90), edge=(0, 100, 20))
            gem(g, x + cw / 2, y + ch / 2 - 2, 15, (210, 255, 220), glow=False)
            g.text((x + cw - 8, y + ch - 6), str(n), 11, "Bold", (5, 40, 10), "rb")
        elif picked:
            tile(g, b, face=(110, 40, 230), top=(170, 110, 255), edge=(60, 20, 140))
            g.text((x + cw / 2, y + ch / 2), str(n), 18, "Bold", WHITE, "mm")
        elif hit:
            sunk(g, b)
            g.text((x + cw / 2, y + ch / 2 + 4), str(n), 18, "Bold", RED, "mm")
        else:
            tile(g, b)
            g.text((x + cw / 2, y + ch / 2), str(n), 18, "Bold", A(WHITE, 200), "mm")
    px = 640
    g.rect((px, 104, 912, 440), 14, fill=(13, 27, 38), outline=A(TILE, 255), width=1.5)
    g.text((px + 18, 120), f"GAINS · {len(picks)} NUMÉROS", 11, "SemiBold", MUTED)
    rows = [(h, m) for h, m in enumerate(table) if m > 0]
    for k, (h, m) in enumerate(rows):
        y = 148 + k * 28
        on = drawn is not None and h == hits
        if on:
            g.rect((px + 10, y - 2, 902, y + 24), 8, fill=A(GREEN, 50), outline=A(GREEN, 180), width=1.5)
        g.text((px + 22, y + 11), f"{h} trouvés", 14, "SemiBold", WHITE if on else MUTED, "lm")
        g.text((890, y + 11), f"x{m:g}", 15, "Bold", GREEN if on else WHITE, "rm")
    if drawn is not None:
        pill(g, 776, 410, f"{hits}/{len(picks)} trouvés", GREEN if any(h == hits for h, _ in rows) else RED, 14)
    return g.finish()


EURO_ORDER = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
RED_NUMS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


@lru_cache(maxsize=1)
def _roulette_wheel():
    R = 175
    size = int(R * 2 * SS + 8)
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    g = G(im, -R - 2, -R - 2)
    g.sphere(0, 0, R, (150, 90, 45), (60, 30, 10))
    g.circle(0, 0, R * 0.9, fill=(30, 20, 12))
    n = 37
    for k, num in enumerate(EURO_ORDER):
        a0 = k * 360 / n - 90 - 360 / n / 2
        col = (0, 150, 70) if num == 0 else ((205, 30, 45) if num in RED_NUMS else (24, 26, 32))
        g.pie((-R * 0.88, -R * 0.88, R * 0.88, R * 0.88), a0, a0 + 360 / n, fill=col, outline=(200, 170, 90), width=1)
    g.circle(0, 0, R * 0.66, fill=(40, 26, 14))
    g.sphere(0, 0, R * 0.6, (200, 140, 70), (70, 40, 15))
    g.circle(0, 0, R * 0.6, outline=(220, 180, 100), width=2)
    for k in range(4):
        a = k * math.pi / 2 + math.pi / 4
        g.line([(0, 0), (math.cos(a) * R * 0.34, math.sin(a) * R * 0.34)], (230, 200, 120), 6)
    g.sphere(0, 0, R * 0.09, (255, 240, 180), (170, 120, 40))
    fnt = font(10.5, "Bold")
    for k, num in enumerate(EURO_ORDER):
        a = k * 360 / n - 90
        t = Image.new("RGBA", (int(26 * SS), int(16 * SS)), (0, 0, 0, 0))
        ImageDraw.Draw(t).text((t.width / 2, t.height / 2), str(num), font=fnt, fill=WHITE, anchor="mm")
        t = t.rotate(-a - 90, expand=True, resample=Image.BICUBIC)
        rr = R * 0.79
        px = g.X(math.cos(math.radians(a)) * rr) - t.width / 2
        py = g.Y(math.sin(math.radians(a)) * rr) - t.height / 2
        im.alpha_composite(t, (int(px), int(py)))
    return im


def render_roulette(c, bet_label, payout_mult, result=None):
    g = frame(c, felt=(18, 110, 66))
    cx, cy, R = 300, 272, 175
    wheel = _roulette_wheel()
    if result is not None:
        idx = EURO_ORDER.index(result)
        wheel = wheel.rotate(idx * 360 / 37, resample=Image.BICUBIC)
    g.effect((cx - R, cy - R, cx + R, cy + R), 16, lambda l: l.circle(cx, cy + 14, R, fill=(0, 0, 0, 170)))
    g.img.paste(wheel, (int(g.X(cx - R - 2)), int(g.Y(cy - R - 2))), wheel)
    if result is not None:
        g.sphere(cx, cy - R * 0.79, 8, WHITE, (150, 155, 165))
    else:
        g.sphere(cx + R * 0.3, cy - R * 0.84, 8, WHITE, (150, 155, 165))
    rx = 700
    if result is None:
        g.text((rx, 160), "TON PARI", 13, "SemiBold", A(WHITE, 190), "mm")
        g.glow_text((rx, 222), bet_label, 44, GOLD, blur=10)
        pill(g, rx, 300, f"Paie x{payout_mult}", WHITE, 15, fill_a=30)
    else:
        col = (0, 150, 70) if result == 0 else ((205, 30, 45) if result in RED_NUMS else (24, 26, 32))
        g.effect((rx - 70, 150, rx + 70, 290), 10, lambda l: l.circle(rx, 228, 66, fill=(0, 0, 0, 160)))
        g.circle(rx, 220, 66, fill=col, outline=WHITE, width=4)
        g.circle(rx, 220, 52, outline=A(WHITE, 90), width=2)
        g.text((rx, 220), str(result), 56, "ExtraBold", WHITE, "mm")
        pill(g, rx, 330, f"Pari : {bet_label}", WHITE, 14, fill_a=30)
    return g.finish()


def value_bubble(g, x, y, val, col=None):
    w = max(40, g.tlen(str(val), 16, "Bold") + 22)
    g.rect((x, y - 15, x + w, y + 15), 15, fill=col or (13, 27, 38), outline=A(WHITE, 60), width=1.5)
    g.text((x + w / 2, y), str(val), 16, "Bold", WHITE if not col else (8, 18, 26), "mm")


def render_baccarat(c, state=None):
    g = frame(c, felt=(20, 100, 70))
    g.text((480, 442), "BANQUIER PAIE 0.95 POUR 1 · ÉGALITÉ PAIE 8 POUR 1", 12, "SemiBold", A(GOLD, 140), "mm")
    if state is None:
        for x, lab in ((250, "JOUEUR"), (710, "BANQUIER")):
            g.rect((x - 150, 120, x + 150, 410), 20, outline=A(GOLD, 120), width=2)
            g.text((x, 150), lab, 22, "ExtraBold", A(WHITE, 220), "mm")
            card(g, x - 80, 190, 72, 104, face_up=False)
            card(g, x + 8, 190, 72, 104, face_up=False)
        return g.finish()
    player, banker, pv, bv, winner = state
    for x, lab, cards, val, key in ((250, "JOUEUR", player, pv, "player"), (710, "BANQUIER", banker, bv, "banker")):
        win = winner == key
        b = (x - 170, 106, x + 170, 420)
        if win:
            g.glow(b, GREEN, blur=12, r=20, alpha=90)
        g.rect(b, 20, outline=A(GREEN if win else GOLD, 220 if win else 110), width=2.5 if win else 2)
        g.text((x - 20, 140), lab, 22, "ExtraBold", WHITE, "rm")
        value_bubble(g, x + 2, 140, val, GREEN if win else None)
        n = len(cards)
        cw, chh, step = 92, 132, 78
        sx = x - (cw + step * (n - 1)) / 2
        for k, cr in enumerate(cards):
            card(g, sx + k * step, 190 + (k == 2) * 16, cw, chh, cr)
    if winner == "tie":
        pill(g, 480, 400, "ÉGALITÉ", GOLD, 18, solid=True)
    return g.finish()


def render_blackjack(c, dealer, player, dealer_val, player_val, hide_hole=True, doubled=False, result=None):
    g = frame(c, felt=(16, 104, 64))
    g.text((480, 270), "LE BLACKJACK PAIE 3 POUR 2  ·  LE CROUPIER TIRE JUSQU'À 17", 12, "SemiBold", A(GOLD, 130), "mm")
    cw, chh, step = 94, 134, 64

    def hand(cards, y, hide):
        n = len(cards)
        sx = 480 - (cw + step * (n - 1)) / 2
        for k, cr in enumerate(cards):
            card(g, sx + k * step, y, cw, chh, cr, face_up=not (hide and k == 0))
        return sx + cw + step * (n - 1)

    end = hand(dealer, 98, hide_hole)
    g.text((480 - (cw + step * (len(dealer) - 1)) / 2 - 18, 160), "CROUPIER", 13, "Bold", A(WHITE, 200), "rm")
    value_bubble(g, end + 14, 165, dealer_val)
    col = None
    if result == "win":
        col = GREEN
    elif result == "lose":
        col = RED
    end = hand(player, 296, False)
    g.text((480 - (cw + step * (len(player) - 1)) / 2 - 18, 360), "TOI", 13, "Bold", A(WHITE, 200), "rm")
    value_bubble(g, end + 14, 365, player_val, col)
    chip_stack(g, 830, 400, 34, [(200, 40, 50), (30, 120, 220)] + ([(30, 160, 80), GOLD_D] if doubled else []))
    if doubled:
        pill(g, 830, 318, "DOUBLÉ", GOLD, 12, solid=True)
    return g.finish()


def render_videopoker(c, hand, held, paytable, current=None):
    g = frame(c)
    g.grad((40, 96, 920, 236), (18, 44, 90), (10, 24, 52), r=14)
    g.rect((40, 96, 920, 236), 14, outline=A(GOLD, 120), width=1.5)
    half = (len(paytable) + 1) // 2
    for k, (lab, m) in enumerate(paytable):
        col_x = 60 if k < half else 500
        y = 112 + (k % half) * 24
        on = lab == current
        if on:
            g.rect((col_x - 8, y - 3, col_x + 410, y + 20), 6, fill=A(GOLD, 70), outline=A(GOLD, 200), width=1)
        g.text((col_x, y + 8), lab.upper(), 13, "Bold", GOLD if on else (220, 225, 240), "lm")
        g.text((col_x + 400, y + 8), f"{m}x", 13, "Bold", GOLD if on else (220, 225, 240), "rm")
    cw, chh, gap = 136, 186, 22
    x0 = 480 - (cw * 5 + gap * 4) / 2
    for k in range(5):
        x = x0 + k * (cw + gap)
        on = k in held
        card(g, x, 254 - (8 if on else 0), cw, chh, hand[k], glow_col=GOLD if on else None)
        if on:
            pill(g, x + cw / 2, 452, "GARDÉE", GOLD, 11, solid=True)
    return g.finish()


def render_mines(c, n_mines, revealed, mines, hit=None, reveal=False, mult=1.0, nxt=1.0, gain=0):
    g = frame(c)
    for k, (lab, val, col) in enumerate((("Mines", str(n_mines), RED), ("Gemmes trouvées", str(len(revealed)), GREEN),
                                         ("Multiplicateur", f"x{mult:.2f}", WHITE), ("Prochain", f"x{nxt:.2f}", MUTED),
                                         ("Gain actuel", fmt(gain), GOLD))):
        stat_box(g, (44, 98 + k * 72, 300, 158 + k * 72), lab, val, col)
    ts, gap = 70, 10
    gx = 330 + (606 - (ts * 5 + gap * 4)) / 2
    gy = 102
    for i in range(20):
        x, y = gx + (i % 5) * (ts + gap), gy + (i // 5) * (ts + gap + 14)
        b = (x, y, x + ts, y + ts)
        if i in revealed:
            sunk(g, b, outline=A(GREEN, 90))
            gem(g, x + ts / 2, y + ts / 2 + 4, 21, (40, 235, 90))
        elif reveal and i in mines:
            if i == hit:
                g.glow(b, RED, blur=10, r=10, alpha=170)
                sunk(g, b, fill=(90, 18, 30), outline=A(RED, 220))
                bomb(g, x + ts / 2, y + ts / 2 + 6, 17)
            else:
                sunk(g, b, fill=(38, 22, 30))
                bomb(g, x + ts / 2, y + ts / 2 + 6, 14, lit=False, alpha=150)
        elif reveal:
            sunk(g, b)
            gem(g, x + ts / 2, y + ts / 2 + 4, 15, (60, 130, 90), glow=False, alpha=150)
        else:
            tile(g, b)
    return g.finish()


def _rocket(g, x, y, ang, s=1.0):
    def rot(px, py):
        ca, sa = math.cos(ang), math.sin(ang)
        return (x + px * ca - py * sa, y + px * sa + py * ca)
    g.glow((x - 30 * s, y - 30 * s, x + 30 * s, y + 30 * s), ORANGE, blur=10, alpha=120, ellipse=True)
    g.poly([rot(-34 * s, -6 * s), rot(-52 * s, 0), rot(-34 * s, 6 * s)], fill=(255, 190, 40))
    g.poly([rot(-30 * s, -4 * s), rot(-42 * s, 0), rot(-30 * s, 4 * s)], fill=(255, 245, 200))
    g.poly([rot(-28 * s, -9 * s), rot(14 * s, -9 * s), rot(30 * s, 0), rot(14 * s, 9 * s), rot(-28 * s, 9 * s)], fill=(235, 240, 250))
    g.poly([rot(14 * s, -9 * s), rot(30 * s, 0), rot(14 * s, 9 * s)], fill=(255, 64, 92))
    g.poly([rot(-28 * s, -9 * s), rot(-36 * s, -18 * s), rot(-16 * s, -9 * s)], fill=(255, 64, 92))
    g.poly([rot(-28 * s, 9 * s), rot(-36 * s, 18 * s), rot(-16 * s, 9 * s)], fill=(255, 64, 92))
    cx_, cy_ = rot(2 * s, 0)
    g.circle(cx_, cy_, 4.5 * s, fill=(60, 150, 255), outline=WHITE, width=1.5)


def render_crash(c, history, mult, crashed=False, cashed=False, auto=None):
    g = frame(c)
    px0, py0, px1, py1 = 76, 112, 900, 430
    top = max(2.0, max(history) * 1.1)
    for k in range(5):
        v = 1 + (top - 1) * k / 4
        y = py1 - (py1 - py0) * (v - 1) / (top - 1)
        g.line([(px0, y), (px1, y)], A(WHITE, 16), 1)
        g.text((px0 - 10, y), f"{v:.1f}x", 11, "SemiBold", MUTED, "rm")
    col = RED if crashed else (GREEN if cashed else c.accent)
    if len(history) >= 2:
        coords = [(px0 + (px1 - px0) * k / (len(history) - 1) * min(1, len(history) / 18),
                   py1 - (py1 - py0) * (m - 1) / (top - 1)) for k, m in enumerate(history)]
        poly = coords + [(coords[-1][0], py1), (px0, py1)]
        g.poly(poly, fill=A(col, 45))
        g.effect((px0, py0, px1, py1), 6, lambda l: l.line(coords, A(col, 220), 8, joint="curve"))
        g.line(coords, col, 4.5, joint="curve")
        ex, ey = coords[-1]
        ang = math.atan2(coords[-1][1] - coords[-2][1], coords[-1][0] - coords[-2][0])
        if crashed:
            for k in range(14):
                a = k * math.pi / 7
                rr = 46 if k % 2 == 0 else 22
                g.glow((ex - 50, ey - 50, ex + 50, ey + 50), ORANGE, blur=18, alpha=40, ellipse=True) if k == 0 else None
            star = []
            for k in range(16):
                a = k * math.pi / 8
                rr = 44 if k % 2 == 0 else 20
                star.append((ex + math.cos(a) * rr, ey + math.sin(a) * rr))
            g.poly(star, fill=(255, 140, 30))
            g.poly([(ex + (x - ex) * 0.55, ey + (y - ey) * 0.55) for x, y in star], fill=(255, 230, 120))
        else:
            _rocket(g, ex, ey, ang, 1.0)
    shown = f"{mult:.2f}x"
    g.glow_text((488, 196), shown, 82, col, blur=18)
    if crashed:
        pill(g, 488, 262, "CRASH", RED, 16, solid=True)
    elif cashed:
        pill(g, 488, 262, "ENCAISSÉ", GREEN, 16, solid=True)
    if auto:
        pill(g, 820, 132, f"Auto x{auto:g}", MUTED, 12, fill_a=25)
    return g.finish()


def render_hilo(c, cur, last=None, m_high=1.0, p_high=0.5, m_low=1.0, p_low=0.5, mult=1.0, gain=0, lost=False):
    g = frame(c)
    for k in range(3):
        card(g, 96 + k * 5, 128 + k * 4, 150, 214, face_up=False)
    card(g, 120, 116, 160, 228, cur, glow_col=RED if lost else None)
    g.text((200, 360), "CARTE ACTUELLE", 11, "SemiBold", MUTED, "mm")
    if last is not None:
        card(g, 318, 168, 104, 148, last, dim=True)
        g.text((370, 332), "PRÉCÉDENTE", 11, "SemiBold", MUTED, "mm")
    bx = 470
    stat_box(g, (bx, 100, 910, 170), f"Plus haut ou égal · {p_high * 100:.1f} %", f"x{m_high:.2f}", GREEN, bar=p_high, bar_col=GREEN)
    stat_box(g, (bx, 182, 910, 252), f"Plus bas ou égal · {p_low * 100:.1f} %", f"x{m_low:.2f}", BLUE, bar=p_low, bar_col=BLUE)
    stat_box(g, (bx, 264, 686, 324), "Multiplicateur total", f"x{mult:.2f}", WHITE)
    stat_box(g, (698, 264, 910, 324), "Gain actuel", fmt(gain), GOLD)
    g.text((690, 380), "⬆ plus haut  ·  ⬇ plus bas  ·  ⏭ passer  ·  💰 encaisser"[0:0] + "Plus haut · Plus bas · Passer · Encaisser", 12, "SemiBold", A(MUTED, 180), "mm")
    return g.finish()


def _egg(g, cx, cy, s, alpha=255):
    g.sphere(cx, cy, s, (255, 245, 200), (215, 150, 30)) if alpha > 200 else g.sphere(cx, cy, s, (150, 140, 110), (90, 75, 40))
    g.circle(cx - s * 0.3, cy + s * 0.2, s * 0.14, fill=A((180, 110, 20), alpha))
    g.circle(cx + s * 0.25, cy - s * 0.25, s * 0.1, fill=A((180, 110, 20), alpha))


def _flame(g, cx, cy, s):
    g.glow((cx - s, cy - s, cx + s, cy + s), ORANGE, blur=8, alpha=170, ellipse=True)
    g.poly([(cx, cy - s), (cx + s * 0.6, cy + s * 0.1), (cx + s * 0.4, cy + s * 0.7), (cx - s * 0.4, cy + s * 0.7), (cx - s * 0.6, cy + s * 0.1)], fill=(255, 90, 30))
    g.poly([(cx, cy - s * 0.45), (cx + s * 0.32, cy + s * 0.25), (cx, cy + s * 0.65), (cx - s * 0.32, cy + s * 0.25)], fill=(255, 220, 80))


def render_dragon(c, tiles, safe_cols, level, path, dead=None, reveal=False, diff="medium", step_mult=1.0, mult=1.0, gain=0):
    g = frame(c)
    rows = len(safe_cols)
    tw, th, gap = 96, 30, 8
    tower_w = tiles * tw + (tiles - 1) * gap
    x0 = 620 - tower_w / 2
    top = 100
    g.grad((x0 - 20, top - 10, x0 + tower_w + 20, 458), (40, 52, 62), (22, 30, 38), r=14)
    g.rect((x0 - 20, top - 10, x0 + tower_w + 20, 458), 14, outline=A(WHITE, 25), width=1.5)
    for r in range(rows):
        lvl = rows - 1 - r
        y = top + r * (th + gap + 1.6)
        mm = step_mult ** (lvl + 1)
        g.text((x0 - 32, y + th / 2), f"x{mm:,.2f}".replace(",", " "), 12, "Bold", GOLD if lvl == level and not reveal else MUTED, "rm")
        if lvl == level and not reveal:
            g.glow((x0 - 6, y - 4, x0 + tower_w + 6, y + th + 4), c.accent, blur=8, r=8, alpha=90)
        for k in range(tiles):
            x = x0 + k * (tw + gap)
            b = (x, y, x + tw, y + th)
            if (lvl, k) in path:
                sunk(g, b, r=8, outline=A(GOLD, 120))
                _egg(g, x + tw / 2, y + th / 2 + 3, 11)
            elif dead == (lvl, k):
                g.glow(b, RED, blur=8, r=8, alpha=170)
                sunk(g, b, r=8, fill=(90, 18, 25), outline=A(RED, 230))
                _flame(g, x + tw / 2, y + th / 2 + 2, 12)
            elif reveal:
                safe = k in safe_cols[lvl]
                sunk(g, b, r=8, fill=(26, 40, 34) if safe else (48, 22, 26))
                if safe:
                    _egg(g, x + tw / 2, y + th / 2 + 3, 9, alpha=140)
            else:
                if lvl == level:
                    tile(g, b, r=8, lift=3, face=(70, 98, 118), top=(95, 128, 150))
                else:
                    tile(g, b, r=8, lift=3)
    stat_box(g, (44, 102, 300, 162), "Difficulté", diff.capitalize(), c.accent)
    stat_box(g, (44, 174, 300, 234), "Multiplicateur", f"x{mult:.2f}", WHITE)
    stat_box(g, (44, 246, 300, 306), "Gain actuel", fmt(gain), GOLD)
    stat_box(g, (44, 318, 300, 378), "Niveau", f"{level} / {rows}", MUTED)
    return g.finish()


def _chicken(g, cx, cy, s=1.0, dead=False):
    g.effect((cx - 24 * s, cy + 14 * s, cx + 24 * s, cy + 28 * s), 4, lambda l: l.ellipse((cx - 20 * s, cy + 16 * s, cx + 20 * s, cy + 26 * s), fill=(0, 0, 0, 120)))
    g.sphere(cx, cy, 20 * s, (255, 255, 255), (200, 205, 215))
    g.sphere(cx + 12 * s, cy - 16 * s, 12 * s, (255, 255, 255), (205, 210, 220))
    g.poly([(cx + 8 * s, cy - 30 * s), (cx + 12 * s, cy - 38 * s), (cx + 16 * s, cy - 30 * s), (cx + 20 * s, cy - 36 * s), (cx + 22 * s, cy - 27 * s)], fill=(235, 40, 50))
    g.poly([(cx + 22 * s, cy - 18 * s), (cx + 33 * s, cy - 14 * s), (cx + 22 * s, cy - 10 * s)], fill=(255, 170, 20))
    if dead:
        g.line([(cx + 12 * s, cy - 22 * s), (cx + 18 * s, cy - 16 * s)], (20, 20, 20), 2)
        g.line([(cx + 18 * s, cy - 22 * s), (cx + 12 * s, cy - 16 * s)], (20, 20, 20), 2)
    else:
        g.circle(cx + 15 * s, cy - 19 * s, 2.6 * s, fill=(20, 20, 25))
    g.poly([(cx - 18 * s, cy - 2 * s), (cx - 30 * s, cy - 12 * s), (cx - 22 * s, cy + 6 * s)], fill=(235, 238, 245))


def _car(g, cx, cy):
    g.effect((cx - 30, cy - 48, cx + 30, cy + 48), 6, lambda l: l.rect((cx - 28, cy - 44, cx + 28, cy + 50), 12, fill=(0, 0, 0, 150)))
    g.grad((cx - 26, cy - 46, cx + 26, cy + 46), (255, 90, 90), (170, 20, 35), r=12)
    g.rect((cx - 20, cy - 28, cx + 20, cy - 10), 5, fill=(40, 60, 80))
    g.rect((cx - 20, cy + 16, cx + 20, cy + 30), 5, fill=(40, 60, 80))
    for dx, dy in ((-28, -30), (24, -30), (-28, 20), (24, 20)):
        g.rect((cx + dx, cy + dy, cx + dx + 4, cy + dy + 16), 2, fill=(15, 15, 18))
    g.circle(cx - 14, cy - 44, 4, fill=(255, 250, 200))
    g.circle(cx + 14, cy - 44, 4, fill=(255, 250, 200))


def render_chicken(c, steps, base_mult, mult, nxt, gain, dead=False, diff="medium", p=0.84):
    g = frame(c)
    lanes = 8
    lw = 96
    x_start = 120
    off = max(0, steps - lanes + 2)
    road_top, road_bot = 172, 424
    g.grad((40, road_top - 30, x_start, road_bot + 30), (90, 100, 110), (60, 68, 78), r=10)
    g.grad((x_start, road_top - 30, 920, road_top), (110, 120, 130), (80, 88, 98))
    g.grad((x_start, road_bot, 920, road_bot + 30), (80, 88, 98), (60, 66, 76))
    g.grad((x_start, road_top, 920, road_bot), (48, 52, 60), (36, 40, 46))
    for i in range(lanes):
        x = x_start + i * lw
        lane_n = i + off
        if i > 0:
            for yy in range(road_top + 8, road_bot - 8, 26):
                g.rect((x - 2, yy, x + 2, yy + 13), 2, fill=A(WHITE, 170))
        m = base_mult ** (lane_n + 1)
        passed = lane_n < steps
        mx, my = x + lw / 2, (road_top + road_bot) / 2 + 40
        if passed:
            g.circle(mx, my, 30, fill=A(GOLD, 40), outline=A(GOLD, 200), width=2.5)
            g.text((mx, my), f"x{m:.2f}", 13, "Bold", GOLD, "mm")
        else:
            g.sphere(mx, my, 30, (100, 108, 120), (40, 44, 52))
            g.circle(mx, my, 22, outline=A((20, 22, 28), 160), width=2)
            g.text((mx, my), f"x{m:.2f}", 13, "Bold", (235, 240, 248), "mm")
    if steps == 0:
        cx = 80
    else:
        cx = x_start + (steps - off - 0.5) * lw
    cy = (road_top + road_bot) / 2 - 30
    if dead:
        _chicken(g, cx, cy + 6, 1.0, dead=True)
        _car(g, cx, cy - 4)
        g.glow((cx - 60, cy - 60, cx + 60, cy + 60), RED, blur=20, alpha=60, ellipse=True)
    else:
        _chicken(g, cx, cy, 1.15)
    g.glow_text((480, 113), f"x{mult:.2f}", 30, RED if dead else c.accent, blur=8)
    pill(g, 150, 113, f"{diff.capitalize()} · {int(p * 100)} %", MUTED, 12, fill_a=25)
    pill(g, 800, 113, f"prochain x{nxt:.2f} · gain {fmt(gain)}", MUTED, 12, fill_a=25)
    return g.finish()


def render_pump(c, steps, mult, nxt, gain, dead=False, diff="medium", p=0.84):
    g = frame(c)
    cx, base_y = 480, 430
    r = 52 + min(96, steps * 8)
    cy = 300 - r * 0.55
    g.rect((cx - 60, base_y - 8, cx + 60, base_y + 22), 8, fill=(50, 60, 72))
    g.grad((cx - 22, base_y - 70, cx + 22, base_y), (150, 160, 175), (80, 88, 100), r=6)
    g.rect((cx - 40, base_y - 82, cx + 40, base_y - 70), 5, fill=(200, 205, 215))
    g.rect((cx - 4, base_y - 120, cx + 4, base_y - 82), 3, fill=(170, 175, 185))
    if dead:
        rnd = random.Random(3)
        for k in range(26):
            a = rnd.uniform(0, math.tau)
            d = rnd.uniform(40, 170)
            col = rnd.choice([c.accent, GOLD, (255, 255, 255), (120, 200, 255)])
            x, y = cx + math.cos(a) * d, 230 + math.sin(a) * d * 0.7
            g.poly([(x, y), (x + 9, y + 3), (x + 6, y + 12), (x - 3, y + 8)], fill=col)
        star = []
        for k in range(18):
            a = k * math.pi / 9
            rr = 120 if k % 2 == 0 else 60
            star.append((cx + math.cos(a) * rr, 230 + math.sin(a) * rr * 0.8))
        g.glow((cx - 120, 130, cx + 120, 330), RED, blur=26, alpha=120, ellipse=True)
        g.poly(star, fill=A(c.accent, 200))
        g.glow_text((cx, 230), "POP !", 56, WHITE, blur=10)
    else:
        g.line([(cx, cy + r * 1.12), (cx - 10, cy + r * 1.12 + 30), (cx, base_y - 120)], A(WHITE, 160), 2, joint="curve")
        g.glow((cx - r, cy - r * 1.1, cx + r, cy + r * 1.1), c.accent, blur=20, alpha=70, ellipse=True)
        bw = int(r * 2 * SS)
        bh = int(r * 2.24 * SS)
        ball = Image.composite(Image.new("RGB", (bw, bh), mix(c.accent, (0, 0, 0), 0.45)),
                               Image.new("RGB", (bw, bh), mix(c.accent, WHITE, 0.45)),
                               Image.radial_gradient("L").resize((bw * 2, bh * 2)).crop((int(bw * 0.68), int(bh * 0.62), int(bw * 1.68), int(bh * 1.62))))
        mask = Image.new("L", (bw, bh), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, bw - 1, bh - 1], fill=255)
        g.img.paste(ball, (int(g.X(cx - r)), int(g.Y(cy - r * 1.12))), mask)
        g.ellipse((cx - r * 0.55, cy - r * 0.85, cx - r * 0.2, cy - r * 0.35), fill=A(WHITE, 110))
        g.poly([(cx - 9, cy + r * 1.12 + 10), (cx + 9, cy + r * 1.12 + 10), (cx, cy + r * 1.12 - 4)], fill=mix(c.accent, (0, 0, 0), 0.3))
        g.text((cx, cy), f"x{mult:.2f}", 30 if r < 90 else 40, "ExtraBold", WHITE, "mm", stroke=2, sfill=A(mix(c.accent, (0, 0, 0), 0.5), 200))
    stat_box(g, (44, 110, 270, 170), "Difficulté", f"{diff.capitalize()} · {int(p * 100)} %", c.accent)
    stat_box(g, (44, 182, 270, 242), "Prochain", f"x{nxt:.2f}", MUTED)
    stat_box(g, (690, 110, 916, 170), "Multiplicateur", f"x{mult:.2f}", RED if dead else WHITE)
    stat_box(g, (690, 182, 916, 242), "Gain actuel", fmt(gain), GOLD)
    return g.finish()


def render_choice(c, question, hint, options):
    g = frame(c)
    g.text((480, 160), question, 26, "ExtraBold", WHITE, "mm")
    g.text((480, 196), hint, 14, "Medium", MUTED, "mm")
    n = len(options)
    bw, gap = 140, 18
    x0 = 480 - (bw * n + gap * (n - 1)) / 2
    for k, (lab, sub) in enumerate(options):
        x = x0 + k * (bw + gap)
        tile(g, (x, 250, x + bw, 340), r=14)
        g.text((x + bw / 2, 284), lab, 22, "ExtraBold", WHITE, "mm")
        g.text((x + bw / 2, 316), sub, 12, "SemiBold", MUTED, "mm")
    return g.finish()
