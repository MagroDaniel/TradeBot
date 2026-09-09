"""Estratégia de reversão à média (Bollinger Bands + RSI) — candidato alternativo ao
cruzamento de EMA (`analysis/signals.py`), pesquisado depois da estratégia de tendência não
cruzar pra expectância positiva em forex mesmo recalibrada (ver `README.md`). Pesquisa
(2026-09-09): forex passa 70-80% do tempo em consolidação/range, onde reversão à média costuma
superar trend-following — ataca a causa raiz do "chop" em vez de filtrar mais em cima de um
gatilho de tendência que estruturalmente soma dois indicadores atrasados.

**Sinal**: fechamento na/além da banda inferior de Bollinger com RSI sobrevendido (<=30) ->
long (aposta que volta pra média); fechamento na/além da banda superior com RSI sobrecomprado
(>=70) -> short.

**Alvo**: a banda central (SMA) NO MOMENTO DO SINAL, congelada como preço fixo — simplificação
deliberada. A banda central real se move a cada candle; travar no valor do sinal deixa o motor
de backtest e a resolução de stop/alvo idênticos aos de `analysis/signals.py` (preço fixo,
mesmo `check_outcome`), sem precisar de lógica de alvo dinâmico. Trade-off consciente: em uma
reversão forte, o alvo real (banda central de agora) pode ficar mais longe que o congelado,
deixando lucro na mesa; aceito pela simplicidade de reaproveitar a infraestrutura já testada.

**Stop**: ATR, mesmo raciocínio do cruzamento de EMA (volatilidade recente do próprio par, não
valor fixo igual pra qualquer par/regime).

NUNCA sugere alavancagem — mesma regra do resto do projeto (ver CLAUDE.md do crypto-daytrade).
"""
from __future__ import annotations

from dataclasses import dataclass

from analysis.indicators import atr, bollinger_bands, rsi
from data.twelvedata_client import Candle

BB_PERIOD = 20
BB_NUM_STD = 2.0
RSI_PERIOD = 14
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0
ATR_PERIOD = 14
ATR_STOP_MULTIPLIER = 1.5

STRATEGY_VERSION = "mean-reversion-bb-rsi-v1-closed-candle"


@dataclass(frozen=True)
class Signal:
    symbol: str
    direction: str  # "long" ou "short"
    entry: float
    stop_loss: float
    target: float
    rsi_value: float
    reason: str


def reprice_signal_for_entry(signal: Signal, entry: float) -> Signal:
    """Mesma lógica de `analysis/signals.py::reprice_signal_for_entry` — preserva a distância
    de risco (ATR) e a distância até o alvo (banda central congelada no momento do sinal) em
    torno do preço executável real, não do fechamento que gerou o sinal."""
    if entry <= 0:
        raise ValueError("Preço de entrada deve ser positivo")
    risk = abs(signal.entry - signal.stop_loss)
    target_distance = abs(signal.target - signal.entry)
    if signal.direction == "long":
        return Signal(
            signal.symbol, signal.direction, entry, entry - risk, entry + target_distance,
            signal.rsi_value, signal.reason,
        )
    return Signal(
        signal.symbol, signal.direction, entry, entry + risk, entry - target_distance,
        signal.rsi_value, signal.reason,
    )


def generate_signal(
    symbol: str,
    candles: list[Candle],
    bb_period: int = BB_PERIOD,
    bb_num_std: float = BB_NUM_STD,
    rsi_oversold: float = RSI_OVERSOLD,
    rsi_overbought: float = RSI_OVERBOUGHT,
    atr_stop_multiplier: float = ATR_STOP_MULTIPLIER,
) -> Signal | None:
    """None quando não há sinal (a maioria dos candles), quando o histórico é curto demais pra
    calcular Bollinger/RSI/ATR, ou quando a banda central congelada ficaria do lado errado da
    entrada (reversão tão fraca que o "alvo" nem seria lucro — não abre posição sem alvo
    válido)."""
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    upper, middle, lower = bollinger_bands(closes, bb_period, bb_num_std)
    rsi_values = rsi(closes, RSI_PERIOD)
    atr_values = atr(highs, lows, closes, ATR_PERIOD)

    if not upper or not rsi_values or not atr_values:
        return None

    close_now = closes[-1]
    rsi_now = rsi_values[-1]
    atr_now = atr_values[-1]
    upper_now, middle_now, lower_now = upper[-1], middle[-1], lower[-1]

    if close_now <= lower_now and rsi_now <= rsi_oversold:
        entry = close_now
        stop_loss = entry - atr_stop_multiplier * atr_now
        target = middle_now
        if target <= entry:
            return None
        reason = (
            f"Fechamento na/abaixo da banda inferior de Bollinger, "
            f"RSI em {rsi_now:.0f} (sobrevendido)"
        )
        return Signal(symbol, "long", entry, stop_loss, target, rsi_now, reason)

    if close_now >= upper_now and rsi_now >= rsi_overbought:
        entry = close_now
        stop_loss = entry + atr_stop_multiplier * atr_now
        target = middle_now
        if target >= entry:
            return None
        reason = (
            f"Fechamento na/acima da banda superior de Bollinger, "
            f"RSI em {rsi_now:.0f} (sobrecomprado)"
        )
        return Signal(symbol, "short", entry, stop_loss, target, rsi_now, reason)

    return None
