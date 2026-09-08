"""Backtest simples sobre o histórico de picks já registrados (storage/picks.json).

Calcula ROI e taxa de acerto a partir dos picks reais que o bot já enviou.
Próximo passo natural: incorporar Closing Line Value (CLV) — comparar a odd
que pegamos com a odd de fechamento do mercado é o jeito mais confiável de
saber se o modelo bate o mercado de forma consistente (independente de
variância de curto prazo).
"""
from __future__ import annotations

from dataclasses import dataclass

from storage.picks_store import Pick


@dataclass
class BacktestSummary:
    total_picks: int
    resolved_picks: int
    wins: int
    losses: int
    roi: float
    total_profit_units: float


def summarize(all_picks: list[Pick]) -> BacktestSummary:
    resolved = [p for p in all_picks if p.result in ("green", "red")]
    wins = sum(1 for p in resolved if p.result == "green")
    losses = sum(1 for p in resolved if p.result == "red")
    total_profit = sum(p.profit_units or 0 for p in resolved)
    total_staked = sum(p.suggested_stake_fraction for p in resolved) or 1e-9

    return BacktestSummary(
        total_picks=len(all_picks),
        resolved_picks=len(resolved),
        wins=wins,
        losses=losses,
        roi=total_profit / total_staked,
        total_profit_units=total_profit,
    )
