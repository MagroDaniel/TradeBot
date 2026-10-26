"""Backtest walk-forward de qualquer estratégia registrada, com as MESMAS regras de saída do
motor ao vivo (`position.evaluate_bar`) e os mesmos cuidados anti-viés que o
crypto-daytrade aprendeu na marra (commit b7272f6 daquele projeto):

- o sinal só enxerga candles já FECHADOS antes do candle de entrada;
- a entrada é na ABERTURA do candle seguinte ao sinal (não no fechamento do candle de sinal);
- candle do timeframe maior só conta depois de fechado;
- custos explícitos: taxa por lado + slippage por lado (R bruto vs. R líquido);
- dentro de um candle, stop é checado antes do alvo (conservador);
- todos os pares andam no mesmo relógio, pra os limites de posições simultâneas valerem
  (vários alts long ao mesmo tempo ≈ uma aposta só).

O resultado é em R (múltiplos do risco inicial). `simulate_equity` converte em patrimônio
assumindo risco fixo de X% por trade — é só ilustração, não promessa.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

from tradebot.models import LONG, SPOT, Candle, Position, reprice_exit_plan
from tradebot.position import evaluate_bar
from tradebot.strategies.base import Strategy

HTF_WINDOW = 60


@dataclass(frozen=True)
class Costs:
    fee_rate: float = 0.0005  # por lado (futuros VIP0 taker = 0,05%; spot = 0,10%)
    slippage_rate: float = 0.0002  # por lado


@dataclass(frozen=True)
class Limits:
    max_open_positions: int = 3
    max_open_per_direction: int = 2
    cooldown_minutes: int = 60
    long_only: bool = False


@dataclass
class Trade:
    symbol: str
    direction: str
    entry_time_ms: int
    exit_time_ms: int
    entry_price: float
    exit_price: float
    initial_stop: float
    exit_reason: str
    r_gross: float  # só slippage
    r_net: float  # slippage + taxas


@dataclass
class Summary:
    trades: int
    wins: int
    win_rate: float
    avg_r_net: float
    total_r_net: float
    avg_r_gross: float
    profit_factor: float
    max_drawdown_r: float
    longs: int
    shorts: int
    exit_reasons: dict[str, int] = field(default_factory=dict)


def _with_slippage(price: float, buy: bool, costs: Costs) -> float:
    return price * (1 + costs.slippage_rate) if buy else price * (1 - costs.slippage_rate)


def run_backtest(
    strategy: Strategy,
    params: dict,
    candles_by_symbol: dict[str, list[Candle]],
    htf_by_symbol: dict[str, list[Candle]] | None = None,
    costs: Costs = Costs(),
    limits: Limits = Limits(),
) -> tuple[list[Trade], list[Position]]:
    """Retorna (trades fechados, posições ainda abertas no fim)."""
    htf_by_symbol = htf_by_symbol or {}
    warmup = strategy.warmup(params)
    index = {s: {c.open_time_ms: i for i, c in enumerate(cs)} for s, cs in candles_by_symbol.items()}
    timeline = sorted({c.open_time_ms for cs in candles_by_symbol.values() for c in cs})
    htf_ptr = {s: 0 for s in htf_by_symbol}

    open_pos: dict[str, Position] = {}
    pending_exit: set[str] = set()
    last_close: dict[str, int] = {}
    trades: list[Trade] = []

    def htf_window(symbol: str, now_ms: int) -> list[Candle] | None:
        candles = htf_by_symbol.get(symbol)
        if candles is None:
            return None
        i = htf_ptr[symbol]
        while i < len(candles) and candles[i].close_time_ms < now_ms:
            i += 1
        htf_ptr[symbol] = i
        return candles[max(0, i - HTF_WINDOW): i]

    def close(symbol: str, price: float, reason: str, t_ms: int) -> None:
        p = open_pos.pop(symbol)
        exit_price = _with_slippage(price, buy=p.direction != LONG, costs=costs)
        sign = 1 if p.direction == LONG else -1
        risk = abs(p.entry_price - p.initial_stop)
        gross = sign * (exit_price - p.entry_price)
        fees = (p.entry_price + exit_price) * costs.fee_rate
        trades.append(Trade(symbol, p.direction, p.opened_at_ms, t_ms, p.entry_price, exit_price, p.initial_stop,
                            reason, gross / risk if risk else 0.0, (gross - fees) / risk if risk else 0.0))
        last_close[symbol] = t_ms

    for t in timeline:
        # 1) saídas: pendentes da estratégia (na abertura) e barreiras dentro deste candle
        for symbol in list(open_pos):
            i = index[symbol].get(t)
            if i is None:
                continue
            c = candles_by_symbol[symbol][i]
            if symbol in pending_exit:
                pending_exit.discard(symbol)
                close(symbol, c.open, "strategy_exit", t)
                continue
            decision = evaluate_bar(open_pos[symbol], c.open, c.high, c.low, c.close, c.close_time_ms)
            if decision:
                close(symbol, decision.price, decision.reason, c.close_time_ms)

        # 2) entradas: sinal com candles fechados até o anterior, executa na abertura deste
        for symbol, candles in candles_by_symbol.items():
            i = index[symbol].get(t)
            if i is None or i < warmup or symbol in open_pos:
                continue
            if t - last_close.get(symbol, -10**15) < limits.cooldown_minutes * 60_000:
                continue
            if len(open_pos) >= limits.max_open_positions:
                break
            window = candles[i - warmup: i]
            htf = htf_window(symbol, t) if strategy.higher_timeframe(params) else None
            signal = strategy.generate(symbol, window, htf, params)
            if signal is None or (limits.long_only and signal.direction != LONG):
                continue
            if sum(1 for p in open_pos.values() if p.direction == signal.direction) >= limits.max_open_per_direction:
                continue
            entry = _with_slippage(candles[i].open, buy=signal.direction == LONG, costs=costs)
            plan = reprice_exit_plan(signal, entry)
            open_pos[symbol] = Position(
                market="backtest", symbol=symbol, direction=signal.direction, qty=1.0, entry_price=entry,
                stop_loss=plan.stop_loss, initial_stop=plan.stop_loss, take_profit=plan.take_profit,
                time_limit_minutes=plan.time_limit_minutes, trailing_activation=plan.trailing_activation,
                trailing_distance=plan.trailing_distance, opened_at_ms=t, strategy=signal.strategy,
                reason=signal.reason, best_price=entry,
            )
            # o próprio candle de entrada já pode bater stop/alvo
            c = candles[i]
            decision = evaluate_bar(open_pos[symbol], c.open, c.high, c.low, c.close, c.close_time_ms)
            if decision:
                close(symbol, decision.price, decision.reason, c.close_time_ms)

        # 3) saída decidida pela estratégia no fechamento → executa na próxima abertura
        for symbol, p in open_pos.items():
            i = index[symbol].get(t)
            if i is None or i + 1 < warmup:
                continue
            window = candles_by_symbol[symbol][i + 1 - warmup: i + 1]
            if strategy.should_exit(p, window, params):
                pending_exit.add(symbol)

    return trades, list(open_pos.values())


def summarize(trades: list[Trade]) -> Summary:
    n = len(trades)
    wins = sum(1 for t in trades if t.r_net > 0)
    gains = sum(t.r_net for t in trades if t.r_net > 0)
    losses = -sum(t.r_net for t in trades if t.r_net < 0)
    equity = peak = max_dd = 0.0
    for t in sorted(trades, key=lambda t: t.exit_time_ms):
        equity += t.r_net
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
    return Summary(
        trades=n, wins=wins, win_rate=wins / n if n else 0.0,
        avg_r_net=sum(t.r_net for t in trades) / n if n else 0.0,
        total_r_net=sum(t.r_net for t in trades),
        avg_r_gross=sum(t.r_gross for t in trades) / n if n else 0.0,
        profit_factor=gains / losses if losses else (float("inf") if gains else 0.0),
        max_drawdown_r=max_dd,
        longs=sum(1 for t in trades if t.direction == LONG), shorts=sum(1 for t in trades if t.direction != LONG),
        exit_reasons=reasons,
    )


def split_by_period(trades: list[Trade], start_ms: int, end_ms: int, parts: int) -> list[list[Trade]]:
    """Fatia os trades em `parts` períodos consecutivos de mesma duração (pela entrada).
    Critério do projeto: uma variante só é candidata se ficar positiva em TODOS os períodos —
    resultado bom no total que vem de um período só é o padrão que enganou no forex."""
    size = (end_ms - start_ms) / parts
    buckets: list[list[Trade]] = [[] for _ in range(parts)]
    for t in trades:
        k = min(parts - 1, max(0, int((t.entry_time_ms - start_ms) // size)))
        buckets[k].append(t)
    return buckets


def bootstrap_p_value(trades: list[Trade], n_sims: int = 5000, block: int = 5, seed: int = 7) -> float:
    """Probabilidade (aprox.) de a expectância real ser ≤ 0, dado o que foi observado.

    Bootstrap em blocos (ideia do `rule_significance_testing` do Jesse): reamostra blocos de
    trades consecutivos — preserva sequências de perdas/ganhos em vez de supor que os trades
    são independentes. Centraliza a série em zero (hipótese nula: sem edge) e mede quão
    frequente é uma média tão boa quanto a observada só por sorte.
    """
    values = [t.r_net for t in sorted(trades, key=lambda t: t.entry_time_ms)]
    n = len(values)
    if n < 10:
        return 1.0
    observed = sum(values) / n
    centered = [v - observed for v in values]
    rng = random.Random(seed)
    hits = 0
    for _ in range(n_sims):
        sample: list[float] = []
        while len(sample) < n:
            start = rng.randrange(n)
            sample.extend(centered[(start + k) % n] for k in range(block))
        if sum(sample[:n]) / n >= observed:
            hits += 1
    return hits / n_sims


def simulate_equity(trades: list[Trade], start: float = 1000.0, risk_pct: float = 1.0) -> float:
    equity = start
    for t in sorted(trades, key=lambda t: t.exit_time_ms):
        equity += equity * risk_pct / 100 * t.r_net
    return equity


def fmt_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def default_costs(market: str) -> Costs:
    return Costs(fee_rate=0.001 if market == SPOT else 0.0005, slippage_rate=0.0002)
