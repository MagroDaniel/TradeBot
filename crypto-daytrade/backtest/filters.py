"""Filtros de regime extra pra testar em cima do gatilho EMA9/EMA21+RSI já existente
(`analysis/signals.py`) — não substituem o gatilho, só decidem se vale a pena confiar nele
agora. Baseado em pesquisa sobre por que cruzamento de EMA cru perde na maioria das condições:
"the filters are the strategy; the crossover is just the trigger" (2026-09-09).

O filtro de tendência de timeframe maior (1h) que a pesquisa também sugeria mora em
`analysis/signals.py::confirms_higher_timeframe_trend` — não aqui — porque os dois backtests
(60 e 180 dias) confirmaram consistentemente que ele melhora o resultado e **foi adotado em
produção** (`generate_signal` já aceita `higher_tf_candles`); `backtest/engine.py` chama a
mesma função de lá em vez de duplicar. ADX, ao contrário, **piorou o resultado nos dois
testes** — fica só aqui, como filtro opcional pra explorar no backtest, nunca chegou a entrar
em produção (ver CLAUDE.md, seção "Backtest walk-forward", pros números).

**Qualidade do candle de sinal (adicionado 2026-09-09)**: candidato extraído dos livros de
referência (`docs/estrategias_extraidas_livros.md`) — Filtro 1 do capítulo de médias móveis do
livro "Análise Técnica" (corpo inteiro do candle além da média, não só o fechamento) combinado
com o conceito de "barra de sinal" de Al Brooks (Trading Price Action Trends): um candle de
reversão/entrada confiável fecha perto do extremo a favor da direção do sinal, não no meio ou
contra. Testado nos dois backtests — resultado misto (inverteu ranking entre janelas),
descartado (ver `docs/estrategias_extraidas_livros.md`).

O filtro de range por estrutura de preço (segunda tentativa no mesmo objetivo do ADX, testado
em 3 janelas — 60/180/365 dias) também mora em
`analysis/signals.py::confirms_price_structure_range` pelo mesmo motivo do filtro de 1h: **foi
adotado em produção** (ao contrário do candle de qualidade acima, que ficou misto e foi
descartado) — `backtest/engine.py` passa `min_range_expansion` direto pro `generate_signal` em
vez de duplicar aqui.
"""
from __future__ import annotations

from analysis.indicators import adx, ema
from analysis.signals import EMA_SLOW_PERIOD
from data.binance_client import Candle

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
    suficiente pra confiar no sinal:

    1. Corpo inteiro (mínimo entre abertura/fechamento pra long, máximo pra short) além da
       EMA21 — não só o fechamento tocando de leve.
    2. Fechamento na metade do candle a favor da direção do sinal (perto da máxima pra long,
       da mínima pra short) — `min_close_position` é a fração mínima da amplitude do candle
       (0 = mínima, 1 = máxima) exigida na direção certa.

    Candle com amplitude zero (high == low) nunca passa — não dá pra avaliar força de
    fechamento sem faixa de preço."""
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
