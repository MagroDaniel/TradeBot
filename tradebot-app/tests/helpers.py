"""Fábricas de dados sintéticos e um MarketData falso (sem rede)."""
from __future__ import annotations

import random

from tradebot.market_data import OrderBook, SymbolRules
from tradebot.models import Candle, Position

MIN = 60_000


def make_candles(closes: list[float], start_ms: int = 1_700_000_000_000 - 1_700_000_000_000 % (15 * MIN),
                 minutes: int = 15, spread: float = 0.002) -> list[Candle]:
    out = []
    prev = closes[0]
    for i, close in enumerate(closes):
        t = start_ms + i * minutes * MIN
        high = max(prev, close) * (1 + spread)
        low = min(prev, close) * (1 - spread)
        out.append(Candle(t, prev, high, low, close, 1000.0, t + minutes * MIN - 1))
        prev = close
    return out


def random_walk(n: int, seed: int = 1, start: float = 100.0, vol: float = 0.006) -> list[float]:
    rng = random.Random(seed)
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + rng.gauss(0, vol)))
    return prices


def make_position(**overrides) -> Position:
    base = dict(
        market="futures", symbol="BTCUSDT", direction="long", qty=1.0, entry_price=100.0, stop_loss=95.0,
        initial_stop=95.0, take_profit=110.0, time_limit_minutes=None, trailing_activation=None,
        trailing_distance=None, opened_at_ms=0, strategy="test", reason="teste", best_price=100.0,
    )
    base.update(overrides)
    return Position(**base)


def flat_book(price: float, qty: float = 1_000_000.0) -> OrderBook:
    return OrderBook(bids=[(price, qty)], asks=[(price, qty)])


class FakeMarketData:
    """Imita BinanceMarketData: candles e preços controlados pelo teste."""

    def __init__(self, market: str = "futures") -> None:
        self.market = market
        self.candles: dict[tuple[str, str], list[Candle]] = {}
        self.prices: dict[str, float] = {}
        self.symbols: list[str] = []
        self.rules = SymbolRules(step_size=0.0001, min_qty=0.0001, min_notional=5.0, tick_size=0.01)

    def klines(self, symbol, interval, limit=200):
        return self.candles.get((symbol, interval), [])[-limit:]

    def top_symbols(self, limit=25, quote="USDT"):
        return self.symbols[:limit]

    def last_prices(self):
        return dict(self.prices)

    def order_book(self, symbol, depth=20):
        return flat_book(self.prices[symbol])

    def symbol_rules(self, symbol):
        return self.rules
