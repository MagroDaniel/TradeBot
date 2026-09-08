"""Indicadores técnicos clássicos — funções puras, sem I/O, iguais em espírito a
`analysis/ev.py`/`analysis/kelly.py` do bot de apostas: dado um histórico de preços, calcula
um número. Nenhuma dessas funções decide se é hora de comprar ou vender — isso é
`analysis/signals.py`.
"""
from __future__ import annotations


def ema(values: list[float], period: int) -> list[float]:
    """Média móvel exponencial — mais peso pros valores recentes que uma média simples.
    Os primeiros `period - 1` valores usam uma SMA como semente (prática padrão)."""
    if len(values) < period:
        return []

    k = 2 / (period + 1)
    result = [sum(values[:period]) / period]  # semente: SMA dos primeiros `period` valores
    for price in values[period:]:
        result.append(price * k + result[-1] * (1 - k))
    return result


def rsi(values: list[float], period: int = 14) -> list[float]:
    """Relative Strength Index (Wilder) — 0-100, >70 costuma ser lido como sobrecomprado,
    <30 como sobrevendido. Precisa de pelo menos `period + 1` valores (calcula sobre
    variações entre candles consecutivos)."""
    if len(values) < period + 1:
        return []

    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result = [_rsi_from_averages(avg_gain, avg_loss)]

    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        result.append(_rsi_from_averages(avg_gain, avg_loss))

    return result


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """Average True Range (Wilder) — mede volatilidade recente, usado aqui pra dimensionar
    stop loss/alvo de forma proporcional ao quanto o par costuma se mexer (não um valor fixo
    igual pra qualquer moeda)."""
    n = len(closes)
    if n < period + 1:
        return []

    true_ranges = []
    for i in range(1, n):
        high_low = highs[i] - lows[i]
        high_prev_close = abs(highs[i] - closes[i - 1])
        low_prev_close = abs(lows[i] - closes[i - 1])
        true_ranges.append(max(high_low, high_prev_close, low_prev_close))

    avg = sum(true_ranges[:period]) / period
    result = [avg]
    for tr in true_ranges[period:]:
        avg = (avg * (period - 1) + tr) / period
        result.append(avg)
    return result
