"""Resume o histórico REAL de sinais já resolvidos — sem inventar taxa de acerto, só soma o
que está registrado em `storage/signals_store.py`. Espelha `backtest/backtester.py` do bot
de apostas: números vêm só do que já aconteceu de verdade, incluindo perdas.
"""
from __future__ import annotations

from dataclasses import dataclass

from storage.signals_store import SignalRecord


@dataclass
class PerformanceSummary:
    total_signals: int
    resolved: int
    wins: int  # target_hit
    losses: int  # stop_hit
    expired: int  # nem bateu alvo nem stop dentro do prazo — não conta pro win rate
    win_rate: float  # 0.0 se não houver sinais decisivos (wins + losses) ainda


def summarize(records: list[SignalRecord]) -> PerformanceSummary:
    resolved = [r for r in records if r.status != "open"]
    wins = sum(1 for r in resolved if r.status == "target_hit")
    losses = sum(1 for r in resolved if r.status == "stop_hit")
    expired = sum(1 for r in resolved if r.status == "expired")

    decisive = wins + losses
    win_rate = wins / decisive if decisive else 0.0

    return PerformanceSummary(
        total_signals=len(records),
        resolved=len(resolved),
        wins=wins,
        losses=losses,
        expired=expired,
        win_rate=win_rate,
    )
