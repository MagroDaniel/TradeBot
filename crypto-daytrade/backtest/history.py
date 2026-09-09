"""Busca candles históricos da Binance com cache local em disco.

O backtest roda a mesma janela de tempo várias vezes — uma por variante de filtro testada —
então buscar tudo de novo a cada execução seria lento e gastaria peso de API à toa. Cache em
JSON simples, um arquivo por (symbol, interval, start, end); `backtest/.cache/` está no
.gitignore, é só um cache local, não faz sentido versionar.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from data.binance_client import BinanceClient, Candle

CACHE_DIR = Path(__file__).parent / ".cache"


def _cache_path(symbol: str, interval: str, start_ms: int, end_ms: int) -> Path:
    return CACHE_DIR / f"{symbol}_{interval}_{start_ms}_{end_ms}.json"


def fetch_candles(
    client: BinanceClient, symbol: str, interval: str, start_ms: int, end_ms: int
) -> list[Candle]:
    """Candles de `symbol` entre `start_ms` e `end_ms` (timestamps UTC em ms) — usa o cache em
    disco se já existir, senão busca na Binance (com paginação, ver
    `BinanceClient.get_historical_klines`) e salva pra próxima vez."""
    path = _cache_path(symbol, interval, start_ms, end_ms)
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [Candle(**c) for c in raw]

    candles = client.get_historical_klines(symbol, interval, start_ms, end_ms)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(c) for c in candles]), encoding="utf-8")
    return candles
