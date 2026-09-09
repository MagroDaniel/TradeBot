"""Gera sinais de entrada/stop/alvo a partir de indicadores técnicos — cruzamento de médias
móveis (EMA9/EMA21) filtrado por RSI, com stop e alvo dimensionados pelo ATR (volatilidade
recente do próprio par). Mesma lógica de `crypto-daytrade/analysis/signals.py` — o método é
agnóstico de mercado, só a fonte de candles muda (`data/twelvedata_client.py` em vez de
`data/binance_client.py`).

Não existe estratégia de análise técnica com edge garantido — isso é tão especulativo quanto
qualquer outro palpite de mercado, só que baseado num método transparente e replicável. NUNCA
sugere alavancagem — mesma decisão do bot de cripto (ver CLAUDE.md), quem for operar decide o
próprio gerenciamento de risco fora do bot.

**Diferença importante em relação ao bot de cripto**: lá, os filtros de tendência de 1h e de
range por estrutura de preço só entraram em produção depois de validados via backtest contra
histórico real de cripto (`crypto-daytrade/docs/estrategias_extraidas_livros.md`). Esses
limiares foram calibrados pra volatilidade/comportamento de cripto — **não têm validade
garantida pra forex**, mercado com volatilidade e sessões bem diferentes. Por isso os defaults
aqui começam DESLIGADOS (`min_range_expansion=None`, sem exigir `higher_tf_candles`) até
passarem pelo mesmo processo de backtest contra dado real de forex — mesma regra do projeto,
nenhuma mudança de estratégia vai pra produção sem validação primeiro.
"""
from __future__ import annotations

from dataclasses import dataclass

from analysis.indicators import atr, ema, rsi
from data.twelvedata_client import Candle

EMA_FAST_PERIOD = 9
EMA_SLOW_PERIOD = 21
RSI_PERIOD = 14
ATR_PERIOD = 14
ATR_STOP_MULTIPLIER = 1.5
RISK_REWARD_RATIO = 2.0
RANGE_LOOKBACK = 20
MIN_RANGE_EXPANSION = 6.0  # mesmo valor adotado em cripto — só referência pra comparar no backtest, não é default aqui

# Faixa de RSI que confirma o cruzamento em vez de brigar contra ele — mesmos valores do bot de
# cripto (é o mesmo indicador, mesma leitura de sobrecompra/sobrevenda); ainda não recalibrado
# especificamente pra forex.
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


STRATEGY_VERSION = "ema9-21-rsi-baseline-v1-closed-candle"


def reprice_signal_for_entry(signal: Signal, entry: float) -> Signal:
    """Mantém o risco calculado pelo ATR quando a entrada executável difere do fechamento —
    mesma lógica de `crypto-daytrade/analysis/signals.py::reprice_signal_for_entry`."""
    if entry <= 0:
        raise ValueError("Preço de entrada deve ser positivo")
    risk = abs(signal.entry - signal.stop_loss)
    if signal.direction == "long":
        return Signal(signal.symbol, signal.direction, entry, entry - risk, entry + RISK_REWARD_RATIO * risk,
                      signal.rsi_value, signal.reason)
    return Signal(signal.symbol, signal.direction, entry, entry + risk, entry - RISK_REWARD_RATIO * risk,
                  signal.rsi_value, signal.reason)


def confirms_higher_timeframe_trend(higher_tf_candles: list[Candle], direction: str) -> bool:
    """True só se a tendência do timeframe maior concordar com a direção do sinal. False
    (bloqueia) se não tiver histórico suficiente — não confirma na dúvida. Ainda não validado
    via backtest pra forex (ver docstring do módulo) — `generate_signal` só aplica esse filtro
    se `higher_tf_candles` for passado explicitamente."""
    closes = [c.close for c in higher_tf_candles]
    fast = ema(closes, EMA_FAST_PERIOD)
    slow = ema(closes, EMA_SLOW_PERIOD)
    if not fast or not slow:
        return False
    return fast[-1] > slow[-1] if direction == "long" else fast[-1] < slow[-1]


def confirms_price_structure_range(
    candles: list[Candle], min_range_expansion: float = MIN_RANGE_EXPANSION
) -> bool:
    """True só se o mercado não estiver "emparedado" num range apertado nos últimos
    `RANGE_LOOKBACK` candles — mesma lógica de `crypto-daytrade` (ver docstring lá pra
    detalhe). Ainda não validado via backtest pra forex."""
    if len(candles) < RANGE_LOOKBACK:
        return False
    recent = candles[-RANGE_LOOKBACK:]
    highest = max(c.high for c in recent)
    lowest = min(c.low for c in recent)
    avg_bar_range = sum(c.high - c.low for c in recent) / len(recent)
    if avg_bar_range <= 0:
        return False
    return (highest - lowest) / avg_bar_range >= min_range_expansion


def generate_signal(
    symbol: str,
    candles: list[Candle],
    higher_tf_candles: list[Candle] | None = None,
    atr_stop_multiplier: float = ATR_STOP_MULTIPLIER,
    long_rsi_range: tuple[float, float] = LONG_RSI_RANGE,
    short_rsi_range: tuple[float, float] = SHORT_RSI_RANGE,
    min_range_expansion: float | None = None,
) -> Signal | None:
    """None quando não há sinal, quando o histórico é curto demais pros indicadores, ou quando
    o cruzamento aconteceu mas algum filtro passado explicitamente não confirma.

    Ao contrário de `crypto-daytrade`, `min_range_expansion` aqui tem default `None` (filtro
    desligado) — esse limiar (6.0) foi calibrado contra dado de cripto, ainda não validado pra
    forex. Mesmo raciocínio pra `higher_tf_candles=None`: só filtra por tendência de timeframe
    maior se for passado explicitamente. Ver docstring do módulo."""
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    ema_fast = ema(closes, EMA_FAST_PERIOD)
    ema_slow = ema(closes, EMA_SLOW_PERIOD)
    rsi_values = rsi(closes, RSI_PERIOD)
    atr_values = atr(highs, lows, closes, ATR_PERIOD)

    if len(ema_fast) < 2 or len(ema_slow) < 2 or not rsi_values or not atr_values:
        return None

    fast_now, fast_prev = ema_fast[-1], ema_fast[-2]
    slow_now, slow_prev = ema_slow[-1], ema_slow[-2]
    rsi_now = rsi_values[-1]
    atr_now = atr_values[-1]
    entry = closes[-1]

    crossed_up = fast_prev <= slow_prev and fast_now > slow_now
    crossed_down = fast_prev >= slow_prev and fast_now < slow_now

    if crossed_up and long_rsi_range[0] <= rsi_now <= long_rsi_range[1]:
        if higher_tf_candles is not None and not confirms_higher_timeframe_trend(
            higher_tf_candles, "long"
        ):
            return None
        if min_range_expansion is not None and not confirms_price_structure_range(
            candles, min_range_expansion
        ):
            return None
        stop_loss = entry - atr_stop_multiplier * atr_now
        risk = entry - stop_loss
        target = entry + RISK_REWARD_RATIO * risk
        reason = (
            f"EMA{EMA_FAST_PERIOD} cruzou acima da EMA{EMA_SLOW_PERIOD}, "
            f"RSI em {rsi_now:.0f} (não sobrecomprado)"
        )
        return Signal(symbol, "long", entry, stop_loss, target, rsi_now, reason)

    if crossed_down and short_rsi_range[0] <= rsi_now <= short_rsi_range[1]:
        if higher_tf_candles is not None and not confirms_higher_timeframe_trend(
            higher_tf_candles, "short"
        ):
            return None
        if min_range_expansion is not None and not confirms_price_structure_range(
            candles, min_range_expansion
        ):
            return None
        stop_loss = entry + atr_stop_multiplier * atr_now
        risk = stop_loss - entry
        target = entry - RISK_REWARD_RATIO * risk
        reason = (
            f"EMA{EMA_FAST_PERIOD} cruzou abaixo da EMA{EMA_SLOW_PERIOD}, "
            f"RSI em {rsi_now:.0f} (não sobrevendido)"
        )
        return Signal(symbol, "short", entry, stop_loss, target, rsi_now, reason)

    return None
