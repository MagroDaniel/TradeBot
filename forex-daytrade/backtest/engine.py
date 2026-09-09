"""Simulador walk-forward multi-símbolo: reproduz a lógica de `main.py` (mesmo
`generate_signal`, mesmo `check_outcome`, mesma regra de expiração) candle a candle, na ordem
cronológica real. Portado de `crypto-daytrade/backtest/engine.py` já na versão corrigida (sem
viés de look-ahead: entrada no candle seguinte ao que confirmou o sinal, nunca no mesmo candle
usado pra calcular os indicadores) — o cripto só recebeu essa correção depois de já estar em
produção (revisão de outra IA, ver `crypto-daytrade/CLAUDE.md`); aqui já nasce certo.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from analysis.outcomes import check_outcome
from analysis.signals import (
    ATR_STOP_MULTIPLIER,
    LONG_RSI_RANGE,
    SHORT_RSI_RANGE,
    STRATEGY_VERSION,
    generate_signal,
    reprice_signal_for_entry,
)
from backtest.filters import passes_adx_filter, passes_signal_candle_quality_filter
from data.twelvedata_client import Candle
from storage.signals_store import SignalRecord

WINDOW_SIZE = 100  # mesmo `outputsize=100` que `scan_for_new_signals` usa em produção
HTF_WINDOW_SIZE = 50


@dataclass(frozen=True)
class ExecutionCosts:
    """Hipóteses explícitas de execução usadas exclusivamente no backtest.

    Forex não tem taxa por lado como exchange de cripto — o custo real é majoritariamente o
    spread (bid/ask), que a Twelve Data não devolve no `time_series` (só um preço, tipo
    "last"/mid). `slippage_rate` aqui faz o papel de proxy do spread (aplicado nos dois lados
    da operação, entrada e saída); `taker_fee_rate` fica disponível pra quem usa conta ECN com
    comissão fixa além do spread (a maioria das corretoras de varejo não cobra à parte —
    default 0). Ajuste pros valores reais da sua corretora antes de confiar no resultado.
    """

    taker_fee_rate: float = 0.0
    slippage_rate: float = 0.0
    funding_rate_per_8h: float = 0.0  # swap overnight em conta com margem — 0 não assume direção

    def __post_init__(self) -> None:
        if any(value < 0 for value in (self.taker_fee_rate, self.slippage_rate, self.funding_rate_per_8h)):
            raise ValueError("Custos de execução não podem ser negativos")


@dataclass(frozen=True)
class Variant:
    """Uma combinação de filtros pra testar contra a mesma janela de histórico. `name` só
    identifica o resultado no relatório, não afeta a simulação."""

    name: str
    min_adx: float | None = None
    use_htf_trend_filter: bool = False
    max_concurrent_same_direction: int | None = None
    max_concurrent_positions: int | None = None
    min_signal_candle_close_position: float | None = None
    atr_stop_multiplier: float | None = None
    long_rsi_range: tuple[float, float] | None = None
    short_rsi_range: tuple[float, float] | None = None
    min_range_expansion: float | None = None


@dataclass
class BacktestResult:
    variant_name: str
    closed: list[SignalRecord]
    still_open: list[SignalRecord]


def apply_entry_slippage(price: float, direction: str, costs: ExecutionCosts) -> float:
    return price * (1 + costs.slippage_rate) if direction == "long" else price * (1 - costs.slippage_rate)


def apply_exit_slippage(price: float, direction: str, costs: ExecutionCosts) -> float:
    return price * (1 - costs.slippage_rate) if direction == "long" else price * (1 + costs.slippage_rate)


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def run_backtest(
    candles_by_symbol: dict[str, list[Candle]],
    variant: Variant,
    higher_tf_candles_by_symbol: dict[str, list[Candle]] | None = None,
    expiry_hours: float = 24.0,
    costs: ExecutionCosts | None = None,
    allowed_directions: frozenset[str] | None = None,
) -> BacktestResult:
    higher_tf_candles_by_symbol = higher_tf_candles_by_symbol or {}
    costs = costs or ExecutionCosts()

    htf_index: dict[str, list[int]] = {
        symbol: [c.open_time_ms for c in candles] for symbol, candles in higher_tf_candles_by_symbol.items()
    }

    all_timestamps = sorted({c.open_time_ms for candles in candles_by_symbol.values() for c in candles})
    time_to_index = {
        symbol: {c.open_time_ms: i for i, c in enumerate(candles)}
        for symbol, candles in candles_by_symbol.items()
    }

    open_positions: dict[str, SignalRecord] = {}
    closed: list[SignalRecord] = []

    def _count_open_same_direction(direction: str) -> int:
        return sum(1 for s in open_positions.values() if s.direction == direction)

    def _higher_tf_window(symbol: str, now_ms: int) -> list[Candle] | None:
        timestamps = htf_index.get(symbol)
        if not timestamps:
            return None
        candles = higher_tf_candles_by_symbol[symbol]
        idx = None
        for i, t in enumerate(timestamps):
            candle = candles[i]
            is_closed = (
                candle.close_time_ms <= now_ms
                if candle.close_time_ms is not None
                else i + 1 < len(candles) and timestamps[i + 1] <= now_ms
            )
            if is_closed:
                idx = i
            elif t > now_ms:
                break
        if idx is None:
            return None
        return candles[max(0, idx - HTF_WINDOW_SIZE + 1) : idx + 1]

    for now_ms in all_timestamps:
        now_dt = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
        occupied_at_signal_close = set(open_positions)

        # 1) Resolve posições abertas durante o candle que acabou de abrir.
        for symbol in list(open_positions.keys()):
            idx_map = time_to_index.get(symbol, {})
            idx = idx_map.get(now_ms)
            if idx is None:
                continue
            candle = candles_by_symbol[symbol][idx]
            signal = open_positions[symbol]

            outcome = check_outcome(signal, [candle])
            opened_at = datetime.fromisoformat(signal.opened_at)
            if outcome is None and now_dt - opened_at > timedelta(hours=expiry_hours):
                outcome = ("expired", candle.close)

            if outcome is None:
                continue

            status, close_price = outcome
            signal.status = status
            signal.closed_at = now_dt.isoformat()
            signal.close_price = apply_exit_slippage(close_price, signal.direction, costs)
            closed.append(signal)
            del open_positions[symbol]

        # 2) O candle anterior acabou de fechar. Avalia o sinal nele e abre no preço de
        # abertura DESTE candle, nunca no mesmo candle que forneceu EMA/RSI/ATR.
        opened_this_candle: list[SignalRecord] = []
        for symbol, candles in candles_by_symbol.items():
            if symbol in occupied_at_signal_close or symbol in open_positions:
                continue
            idx = time_to_index[symbol].get(now_ms)
            if idx is None or idx < WINDOW_SIZE:
                continue

            window = candles[idx - WINDOW_SIZE : idx]

            htf_window = None
            if variant.use_htf_trend_filter:
                htf_window = _higher_tf_window(symbol, now_ms)
                if htf_window is None:
                    continue

            signal = generate_signal(
                symbol,
                window,
                higher_tf_candles=htf_window,
                atr_stop_multiplier=variant.atr_stop_multiplier or ATR_STOP_MULTIPLIER,
                long_rsi_range=variant.long_rsi_range or LONG_RSI_RANGE,
                short_rsi_range=variant.short_rsi_range or SHORT_RSI_RANGE,
                min_range_expansion=variant.min_range_expansion,
            )
            if signal is None:
                continue
            if allowed_directions is not None and signal.direction not in allowed_directions:
                continue

            if variant.min_adx is not None and not passes_adx_filter(window, variant.min_adx):
                continue

            if variant.min_signal_candle_close_position is not None and not passes_signal_candle_quality_filter(
                window, signal.direction, variant.min_signal_candle_close_position
            ):
                continue

            if variant.max_concurrent_same_direction is not None:
                if _count_open_same_direction(signal.direction) >= variant.max_concurrent_same_direction:
                    continue
            if variant.max_concurrent_positions is not None:
                if len(open_positions) >= variant.max_concurrent_positions:
                    continue

            execution_signal = reprice_signal_for_entry(
                signal, apply_entry_slippage(candles[idx].open, signal.direction, costs)
            )
            record = SignalRecord(
                symbol=execution_signal.symbol,
                direction=execution_signal.direction,
                entry=execution_signal.entry,
                stop_loss=execution_signal.stop_loss,
                target=execution_signal.target,
                rsi_value=execution_signal.rsi_value,
                reason=execution_signal.reason,
                opened_at=_ms_to_iso(now_ms),
                strategy_version=STRATEGY_VERSION,
                timeframe="backtest",
                signal_candle_closed_at=_ms_to_iso(candles[idx - 1].close_time_ms)
                if candles[idx - 1].close_time_ms is not None
                else _ms_to_iso(now_ms),
                entry_mode="next_candle_open",
                market_mode="forex",
            )
            open_positions[symbol] = record
            opened_this_candle.append(record)

        for signal in opened_this_candle:
            candle = candles_by_symbol[signal.symbol][time_to_index[signal.symbol][now_ms]]
            outcome = check_outcome(signal, [candle])
            if outcome is None:
                continue
            status, close_price = outcome
            signal.status = status
            signal.closed_at = _ms_to_iso(candle.close_time_ms or now_ms)
            signal.close_price = apply_exit_slippage(close_price, signal.direction, costs)
            closed.append(signal)
            del open_positions[signal.symbol]

    return BacktestResult(
        variant_name=variant.name,
        closed=closed,
        still_open=list(open_positions.values()),
    )
