"""Dados públicos de mercado da Binance — spot (`/api/v3`) e futuros USDⓈ-M (`/fapi/v1`).

Só leitura, sem chave de API. Os dois mercados têm endpoints com o mesmo formato (klines,
ticker/24hr, bookTicker, depth, exchangeInfo), então uma classe atende os dois mudando a URL
base. Rodando do Brasil não precisa de proxy (o bloqueio 451 da Binance é pra IP dos EUA —
ver crypto-daytrade/CLAUDE.md); as URLs podem ser trocadas por variável de ambiente.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

import requests

from tradebot.models import FUTURES, SPOT, Candle

BASE_URLS = {
    SPOT: os.getenv("TRADEBOT_SPOT_API_URL", "https://api.binance.com/api/v3"),
    FUTURES: os.getenv("TRADEBOT_FUTURES_API_URL", "https://fapi.binance.com/fapi/v1"),
}

# Volume alto mas preço travado em ~1.00: nunca dão sinal, só gastam requisição.
STABLECOIN_BASES = {"USDC", "USD1", "FDUSD", "TUSD", "DAI", "RLUSD", "BUSD", "USDP", "GUSD", "USDE", "PYUSD", "EUR", "EURI"}


@dataclass(frozen=True)
class SymbolRules:
    step_size: float  # incremento mínimo de quantidade
    min_qty: float
    min_notional: float  # valor mínimo da ordem em USDT
    tick_size: float

    def round_qty(self, qty: float) -> float:
        """Arredonda PRA BAIXO no múltiplo de `step_size` (nunca compra mais que o calculado)."""
        if self.step_size <= 0:
            return qty
        steps = int(qty / self.step_size + 1e-9)
        return round(steps * self.step_size, 12)


@dataclass(frozen=True)
class OrderBook:
    bids: list[tuple[float, float]]  # (preço, quantidade), melhor primeiro
    asks: list[tuple[float, float]]


def _parse_kline(raw: list) -> Candle:
    return Candle(
        open_time_ms=int(raw[0]),
        open=float(raw[1]),
        high=float(raw[2]),
        low=float(raw[3]),
        close=float(raw[4]),
        volume=float(raw[5]),
        close_time_ms=int(raw[6]),
    )


def closed_only(candles: list[Candle], now_ms: int) -> list[Candle]:
    """Descarta o candle em formação — usar ele repintaria o sinal."""
    return [c for c in candles if c.close_time_ms < now_ms]


class BinanceMarketData:
    def __init__(self, market: str, base_url: str | None = None, timeout: int = 15,
                 session: requests.Session | None = None) -> None:
        if market not in (SPOT, FUTURES):
            raise ValueError(f"Mercado inválido: {market}")
        self.market = market
        self.base_url = (base_url or BASE_URLS[market]).rstrip("/")
        self.timeout = timeout
        self.http = session or requests.Session()
        self._rules: dict[str, SymbolRules] = {}
        self._rules_loaded_at = 0.0
        self._lock = threading.Lock()

    def _get(self, path: str, **params):
        response = self.http.get(f"{self.base_url}/{path}", params=params or None, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def klines(self, symbol: str, interval: str, limit: int = 200) -> list[Candle]:
        return [_parse_kline(k) for k in self._get("klines", symbol=symbol, interval=interval, limit=limit)]

    def historical_klines(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> list[Candle]:
        """Pagina em blocos de 1000 (máximo por chamada)."""
        out: list[Candle] = []
        cursor = start_ms
        limit = 1000 if self.market == SPOT else 1500
        while cursor < end_ms:
            raw = self._get("klines", symbol=symbol, interval=interval, startTime=cursor, endTime=end_ms, limit=limit)
            if not raw:
                break
            out.extend(_parse_kline(k) for k in raw)
            if len(raw) < limit:
                break
            cursor = int(raw[-1][0]) + 1
        return out

    def top_symbols(self, limit: int = 25, quote: str = "USDT") -> list[str]:
        tickers = self._get("ticker/24hr")
        candidates = [
            t for t in tickers
            if t["symbol"].endswith(quote)
            and "_" not in t["symbol"]  # futuros com vencimento (ex: BTCUSDT_251226)
            and t["symbol"][: -len(quote)] not in STABLECOIN_BASES
            and t["symbol"].isascii()  # pares com nome em chinês etc. — ver teste de 50 pares no crypto-daytrade
        ]
        candidates.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)
        return [t["symbol"] for t in candidates[:limit]]

    def last_prices(self) -> dict[str, float]:
        """Último preço de TODOS os pares numa chamada só (o motor chama isso a cada ciclo)."""
        return {t["symbol"]: float(t["price"]) for t in self._get("ticker/price")}

    def order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        raw = self._get("depth", symbol=symbol, limit=depth)
        return OrderBook(
            bids=[(float(p), float(q)) for p, q in raw["bids"]],
            asks=[(float(p), float(q)) for p, q in raw["asks"]],
        )

    def symbol_rules(self, symbol: str) -> SymbolRules:
        with self._lock:
            if not self._rules or time.time() - self._rules_loaded_at > 6 * 3600:
                self._rules = self._load_rules()
                self._rules_loaded_at = time.time()
            rules = self._rules.get(symbol)
        if rules is None:
            raise ValueError(f"{symbol} não existe/não está negociando no mercado {self.market}")
        return rules

    def _load_rules(self) -> dict[str, SymbolRules]:
        info = self._get("exchangeInfo")
        rules = {}
        for s in info["symbols"]:
            if s.get("status") != "TRADING":
                continue
            if self.market == FUTURES and s.get("contractType") not in (None, "PERPETUAL"):
                continue
            filters = {f["filterType"]: f for f in s.get("filters", [])}
            lot = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE") or {}
            if float(lot.get("stepSize", 0) or 0) == 0:
                lot = filters.get("LOT_SIZE", {})
            notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
            rules[s["symbol"]] = SymbolRules(
                step_size=float(lot.get("stepSize", 0) or 0),
                min_qty=float(lot.get("minQty", 0) or 0),
                min_notional=float(notional.get("minNotional", notional.get("notional", 0)) or 0),
                tick_size=float(filters.get("PRICE_FILTER", {}).get("tickSize", 0) or 0),
            )
        return rules
