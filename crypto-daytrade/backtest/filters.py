"""Filtros de regime pra testar em cima do gatilho EMA9/EMA21+RSI já existente
(`analysis/signals.py`) — não substituem o gatilho, só decidem se vale a pena confiar nele
agora. Baseado em pesquisa sobre por que cruzamento de EMA cru perde na maioria das condições:
"the filters are the strategy; the crossover is just the trigger" (ver conversa que motivou
isso, 2026-09-09) — mercado de lado (ADX baixo) e contra a tendência maior são os dois motivos
mais citados pra whipsaw.

Cada filtro recebe só os candles/indicadores relevantes, não o estado do backtest inteiro —
função pura, testável isolada, mesmo espírito de `analysis/indicators.py`.
"""
from __future__ import annotations

from analysis.indicators import adx, ema
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


def passes_higher_timeframe_trend_filter(higher_tf_window: list[Candle], direction: str) -> bool:
    """True só se a tendência de timeframe maior (ex: 1h) concordar com a direção do sinal —
    long só se EMA9 > EMA21 no 1h, short só se EMA9 < EMA21. Evita brigar contra o "quadro
    geral" só porque o timeframe de entrada (15m) deu um cruzamento pontual."""
    closes = [c.close for c in higher_tf_window]
    fast = ema(closes, 9)
    slow = ema(closes, 21)
    if not fast or not slow:
        return False
    return fast[-1] > slow[-1] if direction == "long" else fast[-1] < slow[-1]
