"""Métricas de um resultado de backtest, além do `win_rate` que `analysis/performance.py` já
calcula (esse continua sendo a fonte da verdade pra wins/losses/expired — não duplica, só
soma expectância/profit factor/drawdown em cima, que fazem sentido pra decidir entre variantes
mas não fariam sentido dentro de `analysis/performance.py` que resume sinais reais já emitidos).
"""
from __future__ import annotations

from dataclasses import dataclass

from analysis.performance import summarize
from backtest.engine import BacktestResult
from storage.signals_store import SignalRecord


def r_multiple(signal: SignalRecord) -> float:
    """Quantos "R" (unidades de risco, = distância entrada-stop) o sinal rendeu — positivo se
    lucro, negativo se prejuízo. Não hardcoda RISK_REWARD_RATIO: calcula direto de
    entry/stop_loss/close_price, então funciona igual pra target_hit, stop_hit e expired
    (parcial) sem precisar de caso especial por status."""
    if signal.close_price is None:
        raise ValueError(f"sinal ainda aberto não tem R multiple: {signal.symbol}")

    risk = abs(signal.entry - signal.stop_loss)
    if risk == 0:
        return 0.0

    if signal.direction == "long":
        return (signal.close_price - signal.entry) / risk
    return (signal.entry - signal.close_price) / risk


def _max_drawdown_r(closed_in_order: list[SignalRecord]) -> float:
    """Maior queda (em R acumulado) de um pico até o vale seguinte, na ordem em que os sinais
    fecharam — não é P&L em dinheiro (não há dimensionamento de posição aqui), é só uma medida
    de "quantos R seguidos de prejuízo antes de melhorar" pra comparar o quão dolorida cada
    variante seria de operar."""
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for signal in closed_in_order:
        cumulative += r_multiple(signal)
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return max_dd


@dataclass
class VariantReport:
    name: str
    total_signals: int
    resolved: int
    wins: int
    losses: int
    expired: int
    still_open: int
    win_rate: float
    expectancy_r: float  # média de R por sinal fechado — >0 significa expectativa positiva
    profit_factor: float  # soma dos R positivos / |soma dos R negativos| — >1 é positivo
    max_drawdown_r: float


def build_report(result: BacktestResult) -> VariantReport:
    perf = summarize(result.closed)

    closed_in_order = sorted(result.closed, key=lambda s: s.closed_at or "")
    r_values = [r_multiple(s) for s in closed_in_order]
    positive = sum(r for r in r_values if r > 0)
    negative = sum(r for r in r_values if r < 0)

    return VariantReport(
        name=result.variant_name,
        total_signals=perf.total_signals + len(result.still_open),
        resolved=perf.resolved,
        wins=perf.wins,
        losses=perf.losses,
        expired=perf.expired,
        still_open=len(result.still_open),
        win_rate=perf.win_rate,
        expectancy_r=(sum(r_values) / len(r_values)) if r_values else 0.0,
        profit_factor=(positive / abs(negative)) if negative else float("inf") if positive else 0.0,
        max_drawdown_r=_max_drawdown_r(closed_in_order),
    )


def format_report_table(reports: list[VariantReport]) -> str:
    header = (
        f"{'variante':<28} {'sinais':>7} {'alvo':>5} {'stop':>5} {'exp':>5} {'aberto':>7} "
        f"{'win%':>6} {'exp(R)':>7} {'PF':>6} {'maxDD(R)':>9}"
    )
    lines = [header, "-" * len(header)]
    for r in reports:
        pf = "inf" if r.profit_factor == float("inf") else f"{r.profit_factor:.2f}"
        lines.append(
            f"{r.name:<28} {r.total_signals:>7} {r.wins:>5} {r.losses:>5} {r.expired:>5} "
            f"{r.still_open:>7} {r.win_rate * 100:>5.1f}% {r.expectancy_r:>7.2f} {pf:>6} "
            f"{r.max_drawdown_r:>9.2f}"
        )
    return "\n".join(lines)
