"""Estratégia de rompimento do range da sessão asiática (Asian Range Breakout / London
Breakout) — terceiro candidato depois de tendência (EMA) e reversão à média (Bollinger+RSI),
nenhuma das duas mostrou expectância positiva consistente (ver README.md).

Pesquisa (2026-09-09): evidência real, ainda que modesta ("mild statistical edge" — resultado
misto, mas média ligeiramente positiva), de que o range de negociação formado durante a sessão
asiática (baixa liquidez, tende a ficar "preso" num range apertado) tende a ser rompido de
forma direcional quando a sessão de Londres abre e a liquidez/volume aumentam. GBP/USD e
EUR/USD são citados especificamente como os pares mais indicados — os dois que já estamos
testando nas outras duas estratégias.

**Sinal**: fechamento do candle, dentro da janela de horário de rompimento (07h-11h UTC —
começo da sessão de Londres), que rompe acima da máxima ou abaixo da mínima formada durante a
sessão asiática (00h-07h UTC) do MESMO dia calendário. Um sinal por dia por par — não persegue
o mesmo rompimento duas vezes nem troca de direção no mesmo dia.

**Stop**: do lado oposto do range (long: mínima da sessão asiática; short: máxima) — mais
tolerante que um stop de ATR fixo, deixa o range "respirar" sem ser stopado por ruído normal
dentro dele; é o stop clássico dessa estratégia na literatura. **Alvo**: RISK_REWARD_RATIO fixo
(mesmo padrão das outras duas estratégias), não movimento medido (measured move) —
simplificação deliberada pra reaproveitar a mesma infraestrutura de resolução de stop/alvo.

NUNCA sugere alavancagem — mesma regra do resto do projeto.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from data.twelvedata_client import Candle

ASIAN_START_HOUR = 0
ASIAN_END_HOUR = 7  # exclusive — sessão asiática, 00h-07h UTC
BREAKOUT_START_HOUR = 7
BREAKOUT_END_HOUR = 11  # exclusive — janela em que um rompimento é aceito, início de Londres
RISK_REWARD_RATIO = 2.0

STRATEGY_VERSION = "asian-range-breakout-v1-closed-candle"


@dataclass(frozen=True)
class Signal:
    symbol: str
    direction: str  # "long" ou "short"
    entry: float
    stop_loss: float
    target: float
    rsi_value: float  # não usado por esta estratégia — sempre 0.0, mantido só por
    # compatibilidade com SignalRecord/relatório (que espera esse campo das outras estratégias)
    reason: str


def reprice_signal_for_entry(signal: Signal, entry: float) -> Signal:
    """Mesma lógica das outras duas estratégias — preserva a distância de risco (largura do
    range oposto) e a distância até o alvo em torno do preço executável real."""
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


def asian_session_range(candles: list[Candle], today: date) -> tuple[float, float] | None:
    """Máxima/mínima dos candles cujo horário de abertura (UTC) cai em
    [ASIAN_START_HOUR, ASIAN_END_HOUR) do dia calendário `today`. None se não tiver candle
    nenhum nessa janela (histórico não cobre a sessão asiática de hoje ainda)."""
    session_candles = [
        c for c in candles
        if (dt := datetime.fromtimestamp(c.open_time_ms / 1000, tz=timezone.utc)).date() == today
        and ASIAN_START_HOUR <= dt.hour < ASIAN_END_HOUR
    ]
    if not session_candles:
        return None
    return max(c.high for c in session_candles), min(c.low for c in session_candles)


def generate_signal(symbol: str, candles: list[Candle]) -> Signal | None:
    """None quando o candle mais recente está fora da janela de rompimento, quando a sessão
    asiática de hoje ainda não tem candle nenhum no histórico passado, ou quando o preço não
    rompeu o range. `candles` precisa cobrir pelo menos desde a meia-noite UTC de hoje (o
    motor de backtest garante isso via `WINDOW_SIZE`, ver `backtest/breakout_engine.py`)."""
    if not candles:
        return None
    last = candles[-1]
    now_dt = datetime.fromtimestamp(last.open_time_ms / 1000, tz=timezone.utc)
    if not (BREAKOUT_START_HOUR <= now_dt.hour < BREAKOUT_END_HOUR):
        return None

    session_range = asian_session_range(candles, now_dt.date())
    if session_range is None:
        return None
    asian_high, asian_low = session_range
    if asian_high <= asian_low:
        return None

    close_now = last.close

    if close_now > asian_high:
        entry = close_now
        stop_loss = asian_low
        risk = entry - stop_loss
        if risk <= 0:
            return None
        target = entry + RISK_REWARD_RATIO * risk
        reason = f"Rompimento acima da máxima da sessão asiática ({asian_high:.5f})"
        return Signal(symbol, "long", entry, stop_loss, target, 0.0, reason)

    if close_now < asian_low:
        entry = close_now
        stop_loss = asian_high
        risk = stop_loss - entry
        if risk <= 0:
            return None
        target = entry - RISK_REWARD_RATIO * risk
        reason = f"Rompimento abaixo da mínima da sessão asiática ({asian_low:.5f})"
        return Signal(symbol, "short", entry, stop_loss, target, 0.0, reason)

    return None
