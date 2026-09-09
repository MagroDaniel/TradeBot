"""Decide se um sinal aberto bateu stop ou alvo, dado um histórico de candles desde a
abertura. Extraído de `main.py` (2026-09-09) pra ser compartilhado com `backtest/engine.py` —
ao vivo e no backtest usam exatamente a mesma regra, sem risco de uma lógica divergir da outra
com o tempo.

Não decide expiração (`SIGNAL_EXPIRY_HOURS`) — isso depende de "agora", que significa coisas
diferentes pra cada chamador (`datetime.now()` ao vivo, o timestamp do candle simulado no
backtest), então cada um trata isso por conta própria depois de chamar `check_outcome`.
"""
from __future__ import annotations

from data.binance_client import Candle
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
