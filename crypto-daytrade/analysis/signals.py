"""Gera sinais de entrada/stop/alvo a partir de indicadores técnicos — cruzamento de médias
móveis (EMA9/EMA21) filtrado por RSI, com stop e alvo dimensionados pelo ATR (volatilidade
recente do próprio par, não um valor fixo igual pra qualquer moeda).

Não existe estratégia de análise técnica com edge garantido — isso é tão especulativo quanto
qualquer outro palpite de mercado, só que baseado num método transparente e replicável (dá
pra conferir exatamente por que cada sinal saiu, ver `Signal.reason`). NUNCA sugere
alavancagem — decisão deliberada do usuário (ver CLAUDE.md), quem for operar decide o próprio
gerenciamento de risco fora do bot.
"""
from __future__ import annotations

from dataclasses import dataclass

from analysis.indicators import atr, ema, rsi
from data.binance_client import Candle

EMA_FAST_PERIOD = 9
EMA_SLOW_PERIOD = 21
RSI_PERIOD = 14
ATR_PERIOD = 14
ATR_STOP_MULTIPLIER = 1.5
RISK_REWARD_RATIO = 2.0

# Faixa de RSI que confirma o cruzamento em vez de brigar contra ele — evita comprar já
# sobrecomprado ou vender já sobrevendido, mesmo com o cruzamento de médias "a favor".
LONG_RSI_RANGE = (30.0, 65.0)
SHORT_RSI_RANGE = (35.0, 70.0)


@dataclass(frozen=True)
class Signal:
    symbol: str
    direction: str  # "long" ou "short"
    entry: float
    stop_loss: float
    target: float
    rsi_value: float
    reason: str


def generate_signal(symbol: str, candles: list[Candle]) -> Signal | None:
    """None quando não há sinal (a maioria dos candles — sinal é evento raro por design,
    não um palpite a cada execução) ou quando o histórico é curto demais pros indicadores."""
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    ema_fast = ema(closes, EMA_FAST_PERIOD)
    ema_slow = ema(closes, EMA_SLOW_PERIOD)
    rsi_values = rsi(closes, RSI_PERIOD)
    atr_values = atr(highs, lows, closes, ATR_PERIOD)

    # cada indicador tem um "aquecimento" de tamanho diferente, mas o último valor de cada
    # série sempre corresponde ao candle mais recente — [-1]/[-2] já ficam alinhados sem
    # precisar cortar as séries pelo mesmo tamanho
    if len(ema_fast) < 2 or len(ema_slow) < 2 or not rsi_values or not atr_values:
        return None

    fast_now, fast_prev = ema_fast[-1], ema_fast[-2]
    slow_now, slow_prev = ema_slow[-1], ema_slow[-2]
    rsi_now = rsi_values[-1]
    atr_now = atr_values[-1]
    entry = closes[-1]

    crossed_up = fast_prev <= slow_prev and fast_now > slow_now
    crossed_down = fast_prev >= slow_prev and fast_now < slow_now

    if crossed_up and LONG_RSI_RANGE[0] <= rsi_now <= LONG_RSI_RANGE[1]:
        stop_loss = entry - ATR_STOP_MULTIPLIER * atr_now
        risk = entry - stop_loss
        target = entry + RISK_REWARD_RATIO * risk
        reason = (
            f"EMA{EMA_FAST_PERIOD} cruzou acima da EMA{EMA_SLOW_PERIOD}, "
            f"RSI em {rsi_now:.0f} (não sobrecomprado)"
        )
        return Signal(symbol, "long", entry, stop_loss, target, rsi_now, reason)

    if crossed_down and SHORT_RSI_RANGE[0] <= rsi_now <= SHORT_RSI_RANGE[1]:
        stop_loss = entry + ATR_STOP_MULTIPLIER * atr_now
        risk = stop_loss - entry
        target = entry - RISK_REWARD_RATIO * risk
        reason = (
            f"EMA{EMA_FAST_PERIOD} cruzou abaixo da EMA{EMA_SLOW_PERIOD}, "
            f"RSI em {rsi_now:.0f} (não sobrevendido)"
        )
        return Signal(symbol, "short", entry, stop_loss, target, rsi_now, reason)

    return None
