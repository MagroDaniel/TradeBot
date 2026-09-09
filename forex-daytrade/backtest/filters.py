"""Filtros de regime extra pra testar em cima do gatilho EMA9/EMA21+RSI já existente
(`analysis/signals.py`) — não substituem o gatilho, só decidem se vale a pena confiar nele
agora. Portado de `crypto-daytrade/backtest/filters.py`, mesma lógica (é matemática pura sobre
candles, não depende de cripto).

Diferente do cripto, nenhum desses filtros (nem os que moram em `analysis/signals.py`:
tendência de 1h, range por estrutura de preço) foi validado ainda pra forex — todos começam
como candidatos a testar, não decisões já tomadas. Ver `crypto-daytrade/docs/
estrategias_extraidas_livros.md` pro histórico de como cada um se saiu em cripto (não
transferível sem re-testar).
"""
from __future__ import annotations

from analysis.indicators import adx, ema
from analysis.signals import EMA_SLOW_PERIOD
from data.twelvedata_client import Candle

DEFAULT_MIN_ADX = 25.0
DEFAULT_MIN_CLOSE_POSITION = 0.5


def passes_adx_filter(window: list[Candle], min_adx: float = DEFAULT_MIN_ADX) -> bool:
    """True só se o ADX(14) do candle mais recente indicar mercado em tendência (>= min_adx).
    ADX baixo = mercado de lado = cruzamento de EMA tende a ser ruído, não sinal real."""
    highs = [c.high for c in window]
    lows = [c.low for c in window]
    closes = [c.close for c in window]
    values = adx(highs, lows, closes, period=14)
    return bool(values) and values[-1] >= min_adx


def passes_signal_candle_quality_filter(
    window: list[Candle],
    direction: str,
    min_close_position: float = DEFAULT_MIN_CLOSE_POSITION,
) -> bool:
    """True só se o candle mais recente (o que disparou o cruzamento) tiver "qualidade"
    suficiente — corpo inteiro além da EMA21 e fechamento na metade do candle a favor da
    direção. Ver `crypto-daytrade/backtest/filters.py` pra descrição completa (mesma lógica)."""
    closes = [c.close for c in window]
    ema_slow_values = ema(closes, EMA_SLOW_PERIOD)
    if not ema_slow_values:
        return False
    ema_slow = ema_slow_values[-1]

    candle = window[-1]
    candle_range = candle.high - candle.low
    if candle_range <= 0:
        return False
    close_position = (candle.close - candle.low) / candle_range
    body_low = min(candle.open, candle.close)
    body_high = max(candle.open, candle.close)

    if direction == "long":
        return body_low > ema_slow and close_position >= min_close_position
    return body_high < ema_slow and close_position <= (1 - min_close_position)
