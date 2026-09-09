"""Filtro de regime extra (ADX) pra testar em cima do gatilho EMA9/EMA21+RSI já existente
(`analysis/signals.py`) — não substitui o gatilho, só decide se vale a pena confiar nele agora.
Baseado em pesquisa sobre por que cruzamento de EMA cru perde na maioria das condições: "the
filters are the strategy; the crossover is just the trigger" (2026-09-09).

O filtro de tendência de timeframe maior (1h) que a pesquisa também sugeria mora em
`analysis/signals.py::confirms_higher_timeframe_trend` — não aqui — porque os dois backtests
(60 e 180 dias) confirmaram consistentemente que ele melhora o resultado e **foi adotado em
produção** (`generate_signal` já aceita `higher_tf_candles`); `backtest/engine.py` chama a
mesma função de lá em vez de duplicar. ADX, ao contrário, **piorou o resultado nos dois
testes** — fica só aqui, como filtro opcional pra explorar no backtest, nunca chegou a entrar
em produção (ver CLAUDE.md, seção "Backtest walk-forward", pros números).
"""
from __future__ import annotations

from analysis.indicators import adx
from data.binance_client import Candle

DEFAULT_MIN_ADX = 25.0


def passes_adx_filter(window: list[Candle], min_adx: float = DEFAULT_MIN_ADX) -> bool:
    """True só se o ADX(14) do candle mais recente indicar mercado em tendência (>= min_adx).
    ADX baixo = mercado de lado = cruzamento de EMA tende a ser ruído, não sinal real."""
    highs = [c.high for c in window]
    lows = [c.low for c in window]
    closes = [c.close for c in window]
    values = adx(highs, lows, closes, period=14)
    return bool(values) and values[-1] >= min_adx
