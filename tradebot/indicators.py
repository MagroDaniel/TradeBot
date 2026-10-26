"""Indicadores técnicos — funções puras, sem I/O.

`ema`, `rsi`, `atr` e `adx` são cópia fiel de `crypto-daytrade/analysis/indicators.py` (mesmos
números que o bot de alertas validou em backtest). Os demais (`sma`, `bollinger`, `donchian`,
`supertrend`) foram adicionados pras estratégias novas.

Convenção (igual ao crypto-daytrade): toda série retornada é **alinhada ao fim** — o último
elemento sempre corresponde ao último candle do input, mesmo que as séries tenham tamanhos
diferentes por causa do aquecimento de cada indicador.
"""
from __future__ import annotations

import math


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


def adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """Average Directional Index (Wilder) — mede FORÇA de tendência (0-100), não direção.
    Abaixo de ~20 costuma indicar mercado de lado, onde cruzamento de EMA tende a ser ruído
    (whipsaw); usado em `backtest/filters.py` como filtro de regime, não em `signals.py` — não
    decide long/short, só se vale a pena confiar no cruzamento agora.

    Precisa de ~2x `period` valores (suaviza +DM/-DM/TR por `period`, depois suaviza o DX
    resultante por mais `period`), por isso o aquecimento é maior que EMA/RSI/ATR sozinhos.
    """
    n = len(closes)
    if n < period * 2:
        return []

    plus_dm = []
    minus_dm = []
    true_ranges = []
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
        high_low = highs[i] - lows[i]
        high_prev_close = abs(highs[i] - closes[i - 1])
        low_prev_close = abs(lows[i] - closes[i - 1])
        true_ranges.append(max(high_low, high_prev_close, low_prev_close))

    def _wilder_smooth(values: list[float]) -> list[float]:
        avg = sum(values[:period]) / period
        smoothed = [avg]
        for v in values[period:]:
            avg = (avg * (period - 1) + v) / period
            smoothed.append(avg)
        return smoothed

    smoothed_tr = _wilder_smooth(true_ranges)
    smoothed_plus_dm = _wilder_smooth(plus_dm)
    smoothed_minus_dm = _wilder_smooth(minus_dm)

    dx_values = []
    for tr, p_dm, m_dm in zip(smoothed_tr, smoothed_plus_dm, smoothed_minus_dm):
        if tr == 0:
            dx_values.append(0.0)
            continue
        plus_di = 100 * p_dm / tr
        minus_di = 100 * m_dm / tr
        di_sum = plus_di + minus_di
        dx_values.append(100 * abs(plus_di - minus_di) / di_sum if di_sum else 0.0)

    if len(dx_values) < period:
        return []

    return _wilder_smooth(dx_values)


def sma(values: list[float], period: int) -> list[float]:
    if period < 1 or len(values) < period:
        return []
    window = sum(values[:period])
    result = [window / period]
    for i in range(period, len(values)):
        window += values[i] - values[i - period]
        result.append(window / period)
    return result


def bollinger(values: list[float], period: int = 20, num_std: float = 2.0) -> tuple[list[float], list[float], list[float]]:
    """(inferior, média, superior). Desvio padrão populacional, como a maioria das plataformas."""
    if len(values) < period:
        return [], [], []
    lower, middle, upper = [], [], []
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        mean = sum(window) / period
        std = math.sqrt(sum((v - mean) ** 2 for v in window) / period)
        lower.append(mean - num_std * std)
        middle.append(mean)
        upper.append(mean + num_std * std)
    return lower, middle, upper


def donchian(highs: list[float], lows: list[float], period: int) -> tuple[list[float], list[float]]:
    """(máxima, mínima) dos últimos `period` candles, INCLUINDO o candle atual.

    Pra testar rompimento use o canal do candle anterior (`[-2]`) contra o fechamento atual —
    senão o próprio candle de rompimento entra no canal e o rompimento nunca acontece.
    """
    if len(highs) < period:
        return [], []
    upper = [max(highs[i - period + 1 : i + 1]) for i in range(period - 1, len(highs))]
    lower = [min(lows[i - period + 1 : i + 1]) for i in range(period - 1, len(lows))]
    return upper, lower


def supertrend(
    highs: list[float], lows: list[float], closes: list[float], period: int = 10, multiplier: float = 3.0
) -> tuple[list[float], list[int]]:
    """(linha, direção) — direção 1 = alta, -1 = baixa. Implementação clássica (bandas finais
    que só apertam, nunca afrouxam, enquanto a tendência continua)."""
    atr_values = atr(highs, lows, closes, period)
    if not atr_values:
        return [], []
    offset = len(closes) - len(atr_values)
    line: list[float] = []
    direction: list[int] = []
    final_upper = final_lower = 0.0
    for j, atr_now in enumerate(atr_values):
        i = j + offset
        hl2 = (highs[i] + lows[i]) / 2
        basic_upper = hl2 + multiplier * atr_now
        basic_lower = hl2 - multiplier * atr_now
        if j == 0:
            final_upper, final_lower = basic_upper, basic_lower
            trend = 1 if closes[i] >= hl2 else -1
        else:
            prev_close = closes[i - 1]
            final_upper = basic_upper if (basic_upper < final_upper or prev_close > final_upper) else final_upper
            final_lower = basic_lower if (basic_lower > final_lower or prev_close < final_lower) else final_lower
            trend = direction[-1]
            if trend == -1 and closes[i] > final_upper:
                trend = 1
            elif trend == 1 and closes[i] < final_lower:
                trend = -1
        direction.append(trend)
        line.append(final_lower if trend == 1 else final_upper)
    return line, direction
