"""
games.py — logique des 19 jeux (sans Discord).

Chaque jeu = une classe avec :
  - OPTIONS  : réglages choisis avant de jouer (dict -> valeur par défaut)
  - idle(opts)            : état d'affichage avant la partie
  - INSTANT = True        : play(rng, opts) -> (état, multiplicateur, libellé)
  - INSTANT = False       : __init__(bet, rng, opts) puis méthodes d'action ; .st / .mult / .over
"""
import math

from core import (HOUSE_EDGE, crash_point_from, PLINKO, WHEEL, KENO, DIAMONDS, DIAMOND_TABLE, CASE_MULTS, CASE_W,
                  SLOT_WEIGHTS, SLOT_TRIPLE, SLOT_TWO_CHERRY, SLOT_PAYS, slot_mult)

GAMES = {  # clé : (nom, tag, couleur, catégorie)
    "mines": ("Mines", "Grille", "#1F8A50", "originals"), "crash": ("Crash", "Fusée", "#C43C30", "originals"),
    "dice": ("Dice", "Dé", "#2D6FD1", "originals"), "limbo": ("Limbo", "Cible", "#7A3FB8", "originals"),
    "plinko": ("Plinko", "Bille", "#B88A0C", "originals"), "wheel": ("Wheel", "Roue", "#138A74", "originals"),
    "keno": ("Keno", "Numéros", "#2B5FA8", "originals"), "diamonds": ("Diamonds", "Gemmes", "#8A3FA0", "originals"),
    "case": ("Cases", "Caisses", "#C2700E", "originals"), "coinflip": ("Coinflip", "Pile ou face", "#9E7A12", "originals"),
    "hilo": ("Hi-Lo", "Cartes", "#1E7A48", "originals"), "dragon": ("Dragon Tower", "Tour", "#B34A0A", "originals"),
    "chicken": ("Chicken", "Route", "#B87A10", "originals"), "pump": ("Pump", "Ballon", "#B8323F", "originals"),
    "slots": ("Slots", "Rouleaux", "#B8601A", "casino"), "blackjack": ("Blackjack", "21", "#8E2B22", "casino"),
    "roulette": ("Roulette", "Européenne", "#7E1F2A", "casino"), "baccarat": ("Baccarat", "Banque", "#5E2E84", "casino"),
    "videopoker": ("Video Poker", "Jacks+", "#24578A", "casino"),
}
ALIASES = {
    "mines": ["mine"], "dice": ["de"], "wheel": ["roue"], "diamonds": ["diamond", "gems"], "case": ["cases", "caisse"],
    "coinflip": ["cf", "flip", "pf"], "hilo": ["hl"], "dragon": ["tower", "dragontower"], "chicken": ["poulet"],
    "pump": ["ballon"], "slots": ["slot", "machine"], "blackjack": ["bj", "21"], "roulette": ["roul"],
    "baccarat": ["bacc"], "videopoker": ["vp", "poker"],
}

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["S", "H", "D", "C"]


def rand_card(rng):
    return RANKS[rng.randrange(13)], SUITS[rng.randrange(4)]


def shuffled_deck(rng):
    return rng.shuffle([(r, s) for s in SUITS for r in RANKS])


# ======================= JEUX INSTANTANÉS =======================
class Coinflip:
    INSTANT = True
    OPTIONS = {"choice": "pile"}

    @staticmethod
    def idle(o):
        return {"choice": o["choice"], "face": None}

    @staticmethod
    def play(rng, o):
        face = "pile" if rng.random() < 0.5 else "face"
        return {"choice": o["choice"], "face": face}, (1.98 if face == o["choice"] else 0), face.capitalize()


class Dice:
    INSTANT = True
    OPTIONS = {"target": 50.5, "dir": "over"}

    @staticmethod
    def clamp(o):
        lo, hi = (2.0, 98.99) if o["dir"] == "over" else (1.01, 98.0)
        o["target"] = round(min(hi, max(lo, o["target"])), 2)

    @staticmethod
    def idle(o):
        return {"target": o["target"], "dir": o["dir"], "roll": None}

    @staticmethod
    def play(rng, o):
        roll = rng.randrange(10001) / 100
        chance = (100 - o["target"]) if o["dir"] == "over" else o["target"]
        win = roll > o["target"] if o["dir"] == "over" else roll < o["target"]
        return {"target": o["target"], "dir": o["dir"], "roll": roll}, (round(99 / chance, 4) if win else 0), f"{roll:.2f}".replace(".", ",")


class Limbo:
    INSTANT = True
    OPTIONS = {"target": 2.0}

    @staticmethod
    def idle(o):
        return {"target": o["target"], "result": None}

    @staticmethod
    def play(rng, o):
        res = min(1_000_000.0, crash_point_from(rng.random()))
        return {"target": o["target"], "result": res}, (o["target"] if res >= o["target"] else 0), f"Tirage x{res:.2f}".replace(".", ",")


class Plinko:
    INSTANT = True
    OPTIONS = {"risk": "medium", "rows": 12}

    @staticmethod
    def idle(o):
        return {"rows": o["rows"], "risk": o["risk"], "mults": PLINKO[o["rows"]][o["risk"]], "path": None}

    @staticmethod
    def play(rng, o):
        path = [rng.random() < 0.5 for _ in range(o["rows"])]
        m = PLINKO[o["rows"]][o["risk"]][sum(path)]
        st = Plinko.idle(o)
        st["path"] = path
        return st, m, f"Case {sum(path) + 1}"


class Wheel:
    INSTANT = True
    OPTIONS = {"risk": "medium"}

    @staticmethod
    def idle(o):
        return {"risk": o["risk"], "segments": WHEEL[o["risk"]], "landed": None}

    @staticmethod
    def play(rng, o):
        seg = WHEEL[o["risk"]]
        i = rng.randrange(len(seg))
        return {"risk": o["risk"], "segments": seg, "landed": i}, seg[i], f"Segment {i + 1}"


class Keno:
    INSTANT = True
    OPTIONS = {"picks": [3, 7, 12, 18, 25, 33, 38, 40]}

    @staticmethod
    def idle(o):
        return {"picks": o["picks"], "drawn": None, "table": KENO[len(o["picks"])]}

    @staticmethod
    def play(rng, o):
        drawn = set(rng.shuffle(range(1, 41))[:10])
        hits = len(set(o["picks"]) & drawn)
        return {"picks": o["picks"], "drawn": drawn, "table": KENO[len(o["picks"])]}, KENO[len(o["picks"])][hits], f"{hits}/{len(o['picks'])} trouvés"


class Diamonds:
    INSTANT = True
    OPTIONS = {}

    @staticmethod
    def idle(o):
        return {"gems": None, "label": None, "table": DIAMOND_TABLE}

    @staticmethod
    def play(rng, o):
        gems = [rng.randrange(7) for _ in range(5)]
        shape = tuple(sorted((gems.count(g) for g in set(gems)), reverse=True))
        label, m = DIAMONDS[shape]
        return {"gems": gems, "label": label, "table": DIAMOND_TABLE}, m, label


class Case:
    INSTANT = True
    OPTIONS = {}

    @staticmethod
    def idle(o):
        return {"mults": CASE_MULTS, "weights": CASE_W, "strip": None, "reward": None}

    @staticmethod
    def play(rng, o):
        reward = rng.weighted(CASE_MULTS, CASE_W)
        deco = [rng.weighted(CASE_MULTS, CASE_W) for _ in range(6)]
        return {"mults": CASE_MULTS, "weights": CASE_W, "strip": deco[:3] + [reward] + deco[3:], "reward": reward}, reward, "Caisse ouverte"


class Slots:
    INSTANT = True
    OPTIONS = {}

    @staticmethod
    def idle(o):
        return {"reels": None, "win": False, "pays": SLOT_PAYS}

    @staticmethod
    def play(rng, o):
        reels = [rng.weighted(list(range(7)), SLOT_WEIGHTS) for _ in range(3)]
        m = slot_mult(reels, SLOT_TRIPLE, SLOT_TWO_CHERRY)
        return {"reels": reels, "win": m > 0, "pays": SLOT_PAYS}, m, "Jackpot !" if reels == [6, 6, 6] else ""


RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
ROULETTE_BETS = {  # clé : (libellé, paiement, test)
    "red": ("Rouge", 2, lambda r: r in RED_NUMBERS), "black": ("Noir", 2, lambda r: r != 0 and r not in RED_NUMBERS),
    "even": ("Pair", 2, lambda r: r != 0 and r % 2 == 0), "odd": ("Impair", 2, lambda r: r % 2 == 1),
    "low": ("1 à 18", 2, lambda r: 1 <= r <= 18), "high": ("19 à 36", 2, lambda r: 19 <= r <= 36),
    "d1": ("1 à 12", 3, lambda r: 1 <= r <= 12), "d2": ("13 à 24", 3, lambda r: 13 <= r <= 24), "d3": ("25 à 36", 3, lambda r: 25 <= r <= 36),
}


def roulette_bet(choice):
    if isinstance(choice, int) or str(choice).isdigit():
        n = int(choice)
        return f"Numéro {n}", 36, (lambda r, n=n: r == n)
    return ROULETTE_BETS[choice]


class Roulette:
    INSTANT = True
    OPTIONS = {"choice": "red", "hist": []}

    @staticmethod
    def idle(o):
        label, pay, test = roulette_bet(o["choice"])
        return {"label": label, "pay": pay, "result": None, "wins": {n for n in range(37) if test(n)}, "hist": list(o["hist"])}

    @staticmethod
    def play(rng, o):
        label, pay, test = roulette_bet(o["choice"])
        r = rng.randrange(37)
        o["hist"] = (o["hist"] + [r])[-12:]
        return ({"label": label, "pay": pay, "result": r, "wins": {n for n in range(37) if test(n)}, "hist": list(o["hist"])},
                pay if test(r) else 0, f"Sorti : {r}")


def bacc_pip(card):
    r = card[0]
    return 0 if r in ("10", "J", "Q", "K") else (1 if r == "A" else int(r))


def bacc_value(cards):
    return sum(bacc_pip(c) for c in cards) % 10


class Baccarat:
    INSTANT = True
    OPTIONS = {"side": "player"}
    PAY = {"player": 2, "banker": 1.95, "tie": 9}

    @staticmethod
    def idle(o):
        return {"side": o["side"], "state": None}

    @staticmethod
    def play(rng, o):
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
        winner = "player" if pv > bv else "banker" if bv > pv else "tie"
        side = o["side"]
        m = Baccarat.PAY[side] if winner == side else (1 if winner == "tie" else 0)
        return {"side": side, "state": (player, banker, pv, bv, winner)}, m, {"player": "Joueur", "banker": "Banquier", "tie": "Égalité"}[winner]


# ======================= JEUX EN PLUSIEURS COUPS =======================
class Stepper:
    INSTANT = False
    OPTIONS = {}

    def __init__(self, bet, rng, o):
        self.bet, self.rng, self.o = bet, rng, dict(o)
        self.mult = 1.0
        self.over = False
        self.progress = False  # au moins un coup gagnant : encaissable

    def can_cash(self):
        return self.progress and not self.over


MINES_TILES = 20


def mines_mult(picks, mines):
    m = 1.0
    for i in range(picks):
        m *= (MINES_TILES - i) / (MINES_TILES - mines - i)
    return round(m * (1 - HOUSE_EDGE), 4)


class Mines(Stepper):
    OPTIONS = {"n": 3}

    @staticmethod
    def idle(o):
        return {"n": o["n"], "revealed": [], "mult": 1.0, "next": mines_mult(1, o["n"]), "active": False}

    def __init__(self, bet, rng, o):
        super().__init__(bet, rng, o)
        self.n = o["n"]
        self.mines = set(rng.shuffle(range(MINES_TILES))[:self.n])
        self.revealed, self.hit = [], None

    @property
    def st(self):
        left = MINES_TILES - self.n
        nxt = mines_mult(len(self.revealed) + 1, self.n) if len(self.revealed) < left else self.mult
        return {"n": self.n, "revealed": self.revealed, "mines": self.mines if self.over else None, "hit": self.hit,
                "mult": self.mult if not (self.over and self.hit is not None) else 0, "next": nxt, "active": not self.over,
                "reveal": self.over}

    def pick(self, i):
        """Retourne 'boom', 'win' (grille finie) ou 'ok'."""
        if self.over or i in self.revealed:
            return "ok"
        if i in self.mines:
            self.hit, self.over = i, True
            return "boom"
        self.revealed.append(i)
        self.mult = mines_mult(len(self.revealed), self.n)
        self.progress = True
        if len(self.revealed) >= MINES_TILES - self.n:
            self.over = True
            return "win"
        return "ok"


CRASH_SPEED = 0.07
CRASH_CAP = 1000.0


class Crash(Stepper):
    OPTIONS = {"auto": 0}

    @staticmethod
    def idle(o, recent=()):
        return {"recent": list(recent), "history": [1.0], "mult": 1.0, "auto": o["auto"], "active": False}

    def __init__(self, bet, rng, o):
        super().__init__(bet, rng, o)
        self.crash = min(CRASH_CAP, crash_point_from(rng.random()))
        self.auto = o["auto"]
        self.history = [1.0]
        self.crashed = self.cashed = False
        self.progress = True
        self.recent = []

    @staticmethod
    def growth(t):
        return math.floor(math.exp(CRASH_SPEED * t) * 100) / 100

    @property
    def st(self):
        return {"recent": self.recent, "history": self.history, "mult": self.mult, "crash": self.crash, "crashed": self.crashed,
                "cashed": self.cashed, "auto": self.auto, "active": not self.over}


class Hilo(Stepper):
    @staticmethod
    def idle(o):
        return {"card": ("7", "H"), "last": None, "hist": [], "mh": 1.98, "ph": 0.538, "ml": 1.98, "pl": 0.538, "mult": 1.0, "streak": 0, "active": False}

    def __init__(self, bet, rng, o):
        super().__init__(bet, rng, o)
        self.card = rand_card(rng)
        self.last, self.hist, self.streak, self.skips, self.lost = None, [self.card], 0, 0, False

    def idx(self, c=None):
        return RANKS.index((c or self.card)[0])

    def ph(self):
        return (13 - self.idx()) / 13

    def pl(self):
        return (self.idx() + 1) / 13

    def mh(self):
        return (1 - HOUSE_EDGE) / self.ph()

    def ml(self):
        return (1 - HOUSE_EDGE) / self.pl()

    @property
    def st(self):
        return {"card": self.card, "last": self.last, "hist": self.hist, "mh": self.mh(), "ph": self.ph(), "ml": self.ml(),
                "pl": self.pl(), "mult": 0 if self.lost else self.mult, "streak": self.streak, "active": not self.over, "lost": self.lost}

    def guess(self, high):
        m = self.mh() if high else self.ml()
        new = rand_card(self.rng)
        ok = self.idx(new) >= self.idx() if high else self.idx(new) <= self.idx()
        self.last, self.card = self.card, new
        self.hist.append(new)
        if not ok:
            self.lost, self.over = True, True
            return False
        self.mult = round(self.mult * m, 4)
        self.streak += 1
        self.progress = True
        return True

    def skip(self):
        if self.skips >= 52:
            return False
        self.skips += 1
        self.last, self.card = self.card, rand_card(self.rng)
        self.hist.append(self.card)
        return True


DRAGON_DIFF = {"easy": (4, 3), "medium": (3, 2), "hard": (2, 1), "expert": (3, 1), "master": (4, 1)}
DRAGON_ROWS = 9


class Dragon(Stepper):
    OPTIONS = {"diff": "medium"}

    @staticmethod
    def step_of(diff):
        t, s = DRAGON_DIFF[diff]
        return (t / s) * (1 - HOUSE_EDGE)

    @staticmethod
    def idle(o):
        t, _s = DRAGON_DIFF[o["diff"]]
        return {"tiles": t, "safe": [set()] * DRAGON_ROWS, "level": 0, "path": [], "step": Dragon.step_of(o["diff"]), "mult": 1.0, "active": False}

    def __init__(self, bet, rng, o):
        super().__init__(bet, rng, o)
        self.tiles, self.safe_n = DRAGON_DIFF[o["diff"]]
        self.step = self.step_of(o["diff"])
        self.safe = [set(rng.shuffle(range(self.tiles))[:self.safe_n]) for _ in range(DRAGON_ROWS)]
        self.level, self.path, self.dead = 0, [], None

    @property
    def st(self):
        return {"tiles": self.tiles, "safe": self.safe, "level": self.level, "path": self.path, "dead": self.dead, "reveal": self.over,
                "step": self.step, "mult": 0 if self.dead else self.mult, "active": not self.over}

    def climb(self, col):
        if col not in self.safe[self.level]:
            self.dead, self.over = (self.level, col), True
            return "dead"
        self.path.append((self.level, col))
        self.level += 1
        self.mult = round(self.step ** self.level, 4)
        self.progress = True
        if self.level >= DRAGON_ROWS:
            self.over = True
            return "top"
        return "ok"


LADDER_DIFF = {"easy": 0.95, "medium": 0.84, "hard": 0.68, "hardcore": 0.50}
LADDER_MAX = 25


class Ladder(Stepper):
    """Chicken et Pump : même mécanique, rendu différent."""
    OPTIONS = {"diff": "medium"}

    @staticmethod
    def idle(o):
        p = LADDER_DIFF[o["diff"]]
        return {"steps": 0, "mult": 1.0, "next": (1 - HOUSE_EDGE) / p, "step_m": (1 - HOUSE_EDGE) / p, "diff": o["diff"], "p": p, "active": False}

    def __init__(self, bet, rng, o):
        super().__init__(bet, rng, o)
        self.diff, self.p = o["diff"], LADDER_DIFF[o["diff"]]
        self.steps, self.dead = 0, False

    def next_mult(self):
        return round(self.mult * (1 - HOUSE_EDGE) / self.p, 4)

    @property
    def st(self):
        return {"steps": self.steps, "mult": 0 if self.dead else self.mult, "next": self.next_mult(), "step_m": (1 - HOUSE_EDGE) / self.p,
                "diff": self.diff, "p": self.p, "dead": self.dead, "active": not self.over}

    def advance(self):
        if self.rng.random() < self.p:
            self.steps += 1
            self.mult = self.next_mult()
            self.progress = True
            if self.steps >= LADDER_MAX:
                self.over = True
                return "max"
            return "ok"
        self.dead, self.over = True, True
        return "dead"


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


class Blackjack(Stepper):
    @staticmethod
    def idle(o):
        return {"dealer": [], "player": [], "hide": True, "active": False}

    def __init__(self, bet, rng, o):
        super().__init__(bet, rng, o)
        self.player = [rand_card(rng), rand_card(rng)]
        self.dealer = [rand_card(rng), rand_card(rng)]
        self.doubled, self.revealed, self.res = False, False, None

    @property
    def st(self):
        hide = not self.revealed
        dv = f"{bj_value(self.dealer[1:])} + ?" if hide else bj_value(self.dealer)
        return {"dealer": self.dealer, "player": self.player, "dv": dv, "pv": bj_value(self.player), "hide": hide,
                "doubled": self.doubled, "res": self.res, "active": not self.over}

    def opening(self):
        """Blackjack naturel ? Retourne (mult, libellé) ou None."""
        pbj, dbj = bj_value(self.player) == 21, bj_value(self.dealer) == 21
        if not (pbj or dbj):
            return None
        self.revealed, self.over = True, True
        if pbj and dbj:
            return 1, "Égalité de Blackjacks"
        self.res = "win" if pbj else "lose"
        return (2.5, "BLACKJACK !") if pbj else (0, "Blackjack du croupier")

    def hit(self):
        self.player.append(rand_card(self.rng))
        return bj_value(self.player)

    def resolve(self):
        self.revealed, self.over = True, True
        while bj_value(self.dealer) < 17:
            self.dealer.append(rand_card(self.rng))
        pv, dv = bj_value(self.player), bj_value(self.dealer)
        if pv > 21:
            self.res = "lose"
            return 0, f"Bust ({pv})"
        if dv > 21 or pv > dv:
            self.res = "win"
            return 2, f"Gagné ({pv} contre {dv})"
        if pv < dv:
            self.res = "lose"
            return 0, f"Perdu ({pv} contre {dv})"
        return 1, f"Égalité ({pv})"

    def bust(self):
        self.revealed, self.over, self.res = True, True, "lose"
        return 0, f"Bust ({bj_value(self.player)})"


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


class VideoPoker(Stepper):
    @staticmethod
    def idle(o):
        return {"hand": None, "held": set(), "pays": POKER_PAYS, "label": None, "active": False}

    def __init__(self, bet, rng, o):
        super().__init__(bet, rng, o)
        self.deck = shuffled_deck(rng)
        self.hand = [self.deck.pop() for _ in range(5)]
        self.held = set()

    @property
    def st(self):
        label = poker_eval(self.hand)[0]
        return {"hand": self.hand, "held": self.held, "pays": POKER_PAYS, "label": label if label != "Rien" else None, "active": not self.over}

    def toggle(self, i):
        self.held ^= {i}

    def draw(self):
        for k in range(5):
            if k not in self.held:
                self.hand[k] = self.deck.pop()
        self.over = True
        label, m = poker_eval(self.hand)
        return m, label


ENGINES = {
    "coinflip": Coinflip, "dice": Dice, "limbo": Limbo, "plinko": Plinko, "wheel": Wheel, "keno": Keno, "diamonds": Diamonds,
    "case": Case, "slots": Slots, "roulette": Roulette, "baccarat": Baccarat,
    "mines": Mines, "crash": Crash, "hilo": Hilo, "dragon": Dragon, "chicken": Ladder, "pump": Ladder,
    "blackjack": Blackjack, "videopoker": VideoPoker,
}
