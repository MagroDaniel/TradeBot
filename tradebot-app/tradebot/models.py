"""Tipos compartilhados entre estratégia, motor, broker, backtest e painel.

Ficam aqui (e não espalhados) porque o mesmo `Signal`/`Position` precisa significar
exatamente a mesma coisa no backtest e na execução ao vivo — é isso que garante que o
backtest testa o que roda de verdade (ideia do Nautilus Trader: mesma lógica nos dois modos).
"""
from __future__ import annotations

from dataclasses import dataclass, field

SPOT = "spot"
FUTURES = "futures"
MARKETS = (SPOT, FUTURES)

LONG = "long"
SHORT = "short"


@dataclass(frozen=True)
class Candle:
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time_ms: int


@dataclass(frozen=True)
class ExitPlan:
    """Como a posição vai ser encerrada — o "triple barrier" do Hummingbot, mais trailing.

    Distâncias são em preço absoluto (não %), calculadas pela estratégia no momento do sinal
    (normalmente múltiplos de ATR). `None` desliga a barreira correspondente.
    """

    stop_loss: float
    take_profit: float | None = None
    time_limit_minutes: int | None = None
    # Trailing: quando o lucro atinge `trailing_activation` (em preço, a partir da entrada),
    # o stop passa a seguir o preço a `trailing_distance` de distância — nunca recua.
    trailing_activation: float | None = None
    trailing_distance: float | None = None


@dataclass(frozen=True)
class Signal:
    symbol: str
    direction: str  # LONG ou SHORT
    entry: float  # preço de referência (fechamento do candle de sinal)
    exit_plan: ExitPlan
    reason: str
    strategy: str

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.exit_plan.stop_loss)


def reprice_exit_plan(signal: Signal, entry: float) -> ExitPlan:
    """Reancora stop/alvo no preço realmente executado, mantendo as distâncias planejadas.

    O sinal é calculado no fechamento do candle, mas a ordem só executa depois — se o preço
    andou, manter o stop no preço antigo mudaria o risco silenciosamente (mesmo raciocínio de
    `reprice_signal_for_entry` do crypto-daytrade).
    """
    plan = signal.exit_plan
    stop_dist = abs(signal.entry - plan.stop_loss)
    tp_dist = abs(plan.take_profit - signal.entry) if plan.take_profit is not None else None
    sign = 1 if signal.direction == LONG else -1
    return ExitPlan(
        stop_loss=entry - sign * stop_dist,
        take_profit=entry + sign * tp_dist if tp_dist is not None else None,
        time_limit_minutes=plan.time_limit_minutes,
        trailing_activation=plan.trailing_activation,
        trailing_distance=plan.trailing_distance,
    )


@dataclass
class Position:
    """Posição aberta (ou já fechada) — persistida no SQLite pelo `Store`."""

    market: str
    symbol: str
    direction: str
    qty: float
    entry_price: float
    stop_loss: float
    initial_stop: float
    take_profit: float | None
    time_limit_minutes: int | None
    trailing_activation: float | None
    trailing_distance: float | None
    opened_at_ms: int
    strategy: str
    reason: str
    entry_fee: float = 0.0
    best_price: float | None = None  # melhor preço desde a entrada (pro trailing)
    id: int | None = None
    status: str = "open"  # open | closed
    exit_price: float | None = None
    exit_fee: float = 0.0
    exit_reason: str | None = None  # stop_loss | take_profit | time_limit | trailing_stop | strategy_exit | manual | emergency
    closed_at_ms: int | None = None
    extra: dict = field(default_factory=dict)

    @property
    def initial_risk(self) -> float:
        return abs(self.entry_price - self.initial_stop) * self.qty

    def gross_pnl(self, price: float) -> float:
        sign = 1 if self.direction == LONG else -1
        return sign * (price - self.entry_price) * self.qty

    def net_pnl(self) -> float:
        """P&L realizado já descontando taxa de entrada e saída. Só faz sentido fechada."""
        if self.exit_price is None:
            raise ValueError("Posição ainda aberta")
        return self.gross_pnl(self.exit_price) - self.entry_fee - self.exit_fee

    def r_multiple(self) -> float:
        """Resultado em unidades de risco inicial (1R = perda se bater o stop original)."""
        risk = self.initial_risk
        return self.net_pnl() / risk if risk > 0 else 0.0
