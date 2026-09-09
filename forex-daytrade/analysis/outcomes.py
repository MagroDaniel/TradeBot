"""Decide se um sinal aberto bateu stop ou alvo, dado um histórico de candles desde a
abertura. Mesmo módulo (mesma lógica) de `crypto-daytrade/analysis/outcomes.py` — compartilhado
entre execução ao vivo e `backtest/engine.py`, pra garantir que os dois usam exatamente a
mesma regra.
"""
from __future__ import annotations

from data.twelvedata_client import Candle
from storage.signals_store import SignalRecord


def check_outcome(signal: SignalRecord, candles: list[Candle]) -> tuple[str, float] | None:
    """Retorna (status, preço de fechamento) se o alvo ou o stop foi tocado em algum candle —
    checa o stop primeiro em cada candle (padrão conservador de backtest: evita superestimar
    acerto quando os dois seriam tocados no mesmo candle)."""
    for c in candles:
        if signal.direction == "long":
            if c.low <= signal.stop_loss:
                return "stop_hit", signal.stop_loss
            if c.high >= signal.target:
                return "target_hit", signal.target
        else:
            if c.high >= signal.stop_loss:
                return "stop_hit", signal.stop_loss
            if c.low <= signal.target:
                return "target_hit", signal.target
    return None
