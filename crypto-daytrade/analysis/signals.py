"""Gera sinais de entrada/stop/alvo a partir de indicadores técnicos — cruzamento de médias
móveis (EMA9/EMA21) filtrado por RSI, com stop e alvo dimensionados pelo ATR (volatilidade
recente do próprio par, não um valor fixo igual pra qualquer moeda).

Não existe estratégia de análise técnica com edge garantido — isso é tão especulativo quanto
qualquer outro palpite de mercado, só que baseado num método transparente e replicável (dá
pra conferir exatamente por que cada sinal saiu, ver `Signal.reason`). NUNCA sugere
alavancagem — decisão deliberada do usuário (ver CLAUDE.md), quem for operar decide o próprio
gerenciamento de risco fora do bot.

**Filtro de tendência de timeframe maior (adicionado 2026-09-09)**: cruzamento de EMA9/EMA21
sozinho no 15m tem expectância negativa (`backtest/` rodado contra 60 e 180 dias reais de
histórico confirmou isso nas duas janelas — ver CLAUDE.md, seção "Backtest walk-forward"). Só
a confirmação de tendência do 1h (mesmo par EMA9/EMA21, timeframe maior) reverteu isso pra
expectância positiva de forma consistente nas duas janelas testadas — por isso
`generate_signal` agora exige `higher_tf_candles` alinhado com a direção do sinal antes de
confirmar. ADX foi testado e descartado (piorou o resultado nos dois backtests, ao contrário
do que a literatura genérica sugeria) — fica só como filtro opcional dentro de `backtest/`,
nunca chegou a entrar aqui.

**Filtro de range por estrutura de preço (adicionado 2026-09-09, mesmo dia)**: segunda
tentativa no mesmo objetivo do ADX (bloquear sinal em mercado de lado), mas medindo estrutura
de preço (amplitude dos últimos 20 candles vs. amplitude média de 1 candle) em vez de fórmula
de suavização — ver `confirms_price_structure_range`. Testado em 3 janelas (60/180/365 dias
reais): ao contrário de todo o resto testado (candle de qualidade, RSI por regime, ATR maior —
todos descartados, ver `docs/estrategias_extraidas_livros.md`), esse **não inverteu** de
janela pra janela — expectância consistentemente maior (~3-5x a da produção anterior) e
drawdown consistentemente menor (~10-13x menor). Custo real: corta os sinais em ~97% (de
~37/dia pra ~1/dia, somando os 25 pares) — decisão consciente do usuário, sabendo da troca.
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
RANGE_LOOKBACK = 20
MIN_RANGE_EXPANSION = 6.0

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


def confirms_higher_timeframe_trend(higher_tf_candles: list[Candle], direction: str) -> bool:
    """True só se a tendência do timeframe maior (mesma EMA9/EMA21, mas calculada sobre
    candles de período maior — normalmente 1h enquanto `candles` é 15m) concordar com a
    direção do sinal. False (bloqueia) se não tiver histórico suficiente — não confirma na
    dúvida."""
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
    `RANGE_LOOKBACK` candles — mede estrutura de preço (amplitude total do período vs.
    amplitude média de um candle individual), não uma fórmula de suavização como o ADX
    (testado e descartado, ver `docs/estrategias_extraidas_livros.md`). Num trading range,
    candles se sobrepõem bastante (Al Brooks chama de "barbwire") e a amplitude total fica só
    um pouco maior que a de um candle; numa tendência real, os candles progressivamente se
    estendem numa direção e a amplitude total cresce bem mais rápido que a média por candle.

    False (bloqueia) se não tiver `RANGE_LOOKBACK` candles de histórico, ou se a amplitude
    média dos candles for zero (não dá pra medir expansão sem variação nenhuma de preço)."""
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
    min_range_expansion: float | None = MIN_RANGE_EXPANSION,
) -> Signal | None:
    """None quando não há sinal (a maioria dos candles — sinal é evento raro por design,
    não um palpite a cada execução), quando o histórico é curto demais pros indicadores, ou
    quando o cruzamento aconteceu mas a tendência de `higher_tf_candles` não confirma (ver
    `confirms_higher_timeframe_trend`) — passe `None` só em contexto que deliberadamente não
    quer esse filtro (ex: comparar variantes no backtest).

    `atr_stop_multiplier` tem default igual ao valor de produção (`ATR_STOP_MULTIPLIER`) — só
    existe como parâmetro pra comparar múltiplos maiores no backtest (ver
    `docs/estrategias_extraidas_livros.md`) sem duplicar a lógica de geração de sinal.
    Alvo continua `RISK_REWARD_RATIO` vezes o risco, então mudar o múltiplo também alarga o
    alvo proporcionalmente — mantém o R:R fixo, só muda a distância em preço.

    `long_rsi_range`/`short_rsi_range` têm default igual às constantes de produção
    (`LONG_RSI_RANGE`/`SHORT_RSI_RANGE`) — mesmo espírito, pra comparar faixas de RSI
    deslocadas por regime (ideia de Constance Brown citada no livro Análise Técnica: já que o
    sinal só confirma quando `higher_tf_candles` concorda com a direção, a faixa aceita já
    representa um regime confirmado, não precisa recalcular nada novo).

    `min_range_expansion` tem default igual ao valor de produção (`MIN_RANGE_EXPANSION`) — só
    passe `None` pra pular esse filtro (ex: reproduzir o comportamento anterior a 2026-09-09 no
    backtest, ver `confirms_price_structure_range`)."""
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
