"""
crypto_feed.py — cours crypto en temps réel, convertis en euros.

Source principale : flux WebSocket public de Binance (données de marché, sans clé)
    wss://data-stream.binance.vision  (domaine "market data only", accessible depuis la plupart des hébergeurs)
Historique 24 h (sparklines) : REST https://data-api.binance.vision/api/v3/klines (1 point par heure)
Secours : CoinGecko /simple/price (sans clé) si Binance ne répond plus.
"""
import json
import time
import asyncio
import logging

import aiohttp

log = logging.getLogger("casino.crypto")

COINS = [  # symbole, nom, couleur, id CoinGecko
    ("BTC", "Bitcoin", "#F7931A", "bitcoin"), ("ETH", "Ethereum", "#627EEA", "ethereum"),
    ("SOL", "Solana", "#7B3FE4", "solana"), ("BNB", "BNB", "#C9A10E", "binancecoin"),
    ("XRP", "XRP", "#2A2F36", "ripple"), ("ADA", "Cardano", "#0033AD", "cardano"),
    ("DOGE", "Dogecoin", "#B8962E", "dogecoin"), ("TON", "Toncoin", "#0098EA", "the-open-network"),
    ("TRX", "Tron", "#D3242C", "tron"), ("AVAX", "Avalanche", "#E84142", "avalanche-2"),
    ("DOT", "Polkadot", "#E6007A", "polkadot"), ("LINK", "Chainlink", "#2A5ADA", "chainlink"),
    ("LTC", "Litecoin", "#345D9D", "litecoin"), ("SHIB", "Shiba Inu", "#E5531A", "shiba-inu"),
    ("USDT", "Tether", "#26A17B", "tether"),
]
META = {c[0]: c for c in COINS}
WS_URL = "wss://data-stream.binance.vision/stream?streams="
REST = "https://data-api.binance.vision/api/v3"
GECKO = "https://api.coingecko.com/api/v3/simple/price"


class CryptoFeed:
    def __init__(self):
        # prix en USDT (Binance) ; EURUSDT = combien d'USDT pour 1 €
        self.usdt = {}
        self.open_usdt = {}
        self.eurusdt = None
        self.eur_open = None
        self.spark = {c[0]: [] for c in COINS}   # en euros
        self.eur_direct = {}                      # secours CoinGecko : prix € / variation %
        self.last_tick = 0
        self.session = None
        self._tasks = []

    # ---------- lecture ----------
    @property
    def live(self):
        return time.time() - self.last_tick < 90

    def price(self, sym):
        """Prix en euros (float) ou None."""
        if sym == "USDT":
            if self.eurusdt:
                return 1 / self.eurusdt
        elif sym in self.usdt and self.eurusdt:
            return self.usdt[sym] / self.eurusdt
        d = self.eur_direct.get(sym)
        if d:
            return d[0]
        sp = self.spark.get(sym)
        return sp[-1] if sp else None

    def change(self, sym):
        if sym == "USDT" and self.eurusdt and self.eur_open:
            return ((1 / self.eurusdt) / (1 / self.eur_open) - 1) * 100
        if sym in self.usdt and self.open_usdt.get(sym) and self.eurusdt and self.eur_open:
            now_eur = self.usdt[sym] / self.eurusdt
            open_eur = self.open_usdt[sym] / self.eur_open
            return (now_eur / open_eur - 1) * 100
        d = self.eur_direct.get(sym)
        if d:
            return d[1]
        sp = self.spark.get(sym)
        return (sp[-1] / sp[0] - 1) * 100 if sp and sp[0] else 0.0

    def coin(self, sym):
        s, name, color, _ = META[sym]
        p = self.price(sym)
        sp = list(self.spark.get(sym) or [])
        if p is not None:
            sp = (sp + [p])[-25:]
        return {"sym": s, "name": name, "color": color, "price": p or 0.0, "change": self.change(sym), "spark": sp}

    def all(self):
        return [self.coin(c[0]) for c in COINS]

    # ---------- démarrage ----------
    def start(self):
        if self._tasks:
            return
        self._tasks = [asyncio.create_task(self._ws_loop()), asyncio.create_task(self._history_loop()),
                       asyncio.create_task(self._fallback_loop())]

    async def _sess(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20), headers={"User-Agent": "casino-bot/1.0"})
        return self.session

    async def _ws_loop(self):
        pairs = [f"{c[0].lower()}usdt@miniTicker" for c in COINS if c[0] != "USDT"] + ["eurusdt@miniTicker"]
        url = WS_URL + "/".join(pairs)
        delay = 2
        while True:
            try:
                s = await self._sess()
                async with s.ws_connect(url, heartbeat=30) as ws:
                    log.info("Crypto : flux Binance connecté.")
                    delay = 2
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        d = json.loads(msg.data).get("data", {})
                        sym = d.get("s", "")
                        if not sym.endswith("USDT"):
                            continue
                        c, o = float(d["c"]), float(d["o"])
                        if sym == "EURUSDT":
                            self.eurusdt, self.eur_open = c, o
                        else:
                            base = sym[:-4]
                            self.usdt[base], self.open_usdt[base] = c, o
                        self.last_tick = time.time()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning(f"Crypto : flux coupé ({e}), reconnexion dans {delay}s.")
            await asyncio.sleep(delay)
            delay = min(60, delay * 2)

    async def _history_loop(self):
        while True:
            try:
                s = await self._sess()
                eur_hist = None
                async with s.get(f"{REST}/klines", params={"symbol": "EURUSDT", "interval": "1h", "limit": 24}) as r:
                    if r.status == 200:
                        eur_hist = [float(k[4]) for k in await r.json()]
                for sym, *_ in COINS:
                    if sym == "USDT":
                        if eur_hist:
                            self.spark["USDT"] = [1 / x for x in eur_hist]
                        continue
                    async with s.get(f"{REST}/klines", params={"symbol": f"{sym}USDT", "interval": "1h", "limit": 24}) as r:
                        if r.status != 200:
                            continue
                        closes = [float(k[4]) for k in await r.json()]
                    if eur_hist and len(eur_hist) == len(closes):
                        self.spark[sym] = [c / e for c, e in zip(closes, eur_hist)]
                    elif self.eurusdt:
                        self.spark[sym] = [c / self.eurusdt for c in closes]
                    await asyncio.sleep(0.15)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning(f"Crypto : historique indisponible ({e}).")
            await asyncio.sleep(3600)

    async def _fallback_loop(self):
        """Si Binance est muet, CoinGecko toutes les 2 minutes."""
        await asyncio.sleep(20)
        while True:
            if not self.live:
                try:
                    s = await self._sess()
                    ids = ",".join(c[3] for c in COINS)
                    async with s.get(GECKO, params={"ids": ids, "vs_currencies": "eur", "include_24hr_change": "true"}) as r:
                        if r.status == 200:
                            data = await r.json()
                            for sym, _n, _c, gid in COINS:
                                if gid in data:
                                    self.eur_direct[sym] = (float(data[gid]["eur"]), float(data[gid].get("eur_24h_change") or 0))
                            log.info("Crypto : prix CoinGecko utilisés (secours).")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning(f"Crypto : CoinGecko indisponible ({e}).")
            await asyncio.sleep(120)
