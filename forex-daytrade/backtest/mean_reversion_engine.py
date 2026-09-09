"""Simulador walk-forward pra estratégia de reversão à média (Bollinger+RSI,
`analysis/mean_reversion_signals.py`) — mesmo raciocínio de não-viés de look-ahead do
`backtest/engine.py` (entrada no candle seguinte ao que confirmou o sinal, nunca no mesmo
candle usado pros indicadores), mas como motor separado em vez de generalizar o `Variant`/
`run_backtest` do cruzamento de EMA: as duas estratégias têm parâmetros e formas de sinal
diferentes o bastante (alvo dinâmico vs. R:R fixo) pra um motor genérico compartilhado valer
menos que dois motores simples e testáveis isoladamente. `SignalRecord`, `check_outcome`,
`ExecutionCosts` e a lógica de slippage são as mesmas (reaproveitadas de `backtest/engine.py`,
não duplicadas).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from analysis.mean_reversion_signals import (
    ATR_STOP_MULTIPLIER,
    BB_NUM_STD,
    BB_PERIOD,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    STRATEGY_VERSION,
    generate_signal,
    reprice_signal_for_entry,
)
from backtest.engine import BacktestResult, ExecutionCosts, apply_entry_slippage, apply_exit_slippage
from analysis.outcomes import check_outcome
from data.twelvedata_client import Candle
from storage.signals_store import SignalRecord

WINDOW_SIZE = 100  # generoso o bastante pra BB(20)/RSI(14)/ATR(14) aquecerem com folga


@dataclass(frozen=True)
class MeanReversionVariant:
    """Uma combinação de parâmetros pra testar contra a mesma janela de histórico. `name` só
    identifica o resultado no relatório, não afeta a simulação."""

    name: str
    bb_period: int = BB_PERIOD
    bb_num_std: float = BB_NUM_STD
    rsi_oversold: float = RSI_OVERSOLD
    rsi_overbought: float = RSI_OVERBOUGHT
    atr_stop_multiplier: float = ATR_STOP_MULTIPLIER
    session_hours_utc: tuple[int, int] | None = None
    max_concurrent_positions: int | None = None


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def run_backtest(
    candles_by_symbol: dict[str, list[Candle]],
    variant: MeanReversionVariant,
    expiry_hours: float = 24.0,
    costs: ExecutionCosts | None = None,
) -> BacktestResult:
    costs = costs or ExecutionCosts()

    all_timestamps = sorted({c.open_time_ms for candles in candles_by_symbol.values() for c in candles})
    time_to_index = {
        symbol: {c.open_time_ms: i for i, c in enumerate(candles)}
        for symbol, candles in candles_by_symbol.items()
    }

    open_positions: dict[str, SignalRecord] = {}
    closed: list[SignalRecord] = []

    for now_ms in all_timestamps:
        now_dt = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
        occupied_at_signal_close = set(open_positions)

        # 1) Resolve posições abertas durante o candle que acabou de abrir.
        for symbol in list(open_positions.keys()):
            idx = time_to_index.get(symbol, {}).get(now_ms)
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
        # abertura DESTE candle.
        opened_this_candle: list[SignalRecord] = []
        for symbol, candles in candles_by_symbol.items():
            if symbol in occupied_at_signal_close or symbol in open_positions:
                continue
            idx = time_to_index[symbol].get(now_ms)
            if idx is None or idx < WINDOW_SIZE:
                continue

            window = candles[idx - WINDOW_SIZE : idx]

            signal = generate_signal(
                symbol,
                window,
                bb_period=variant.bb_period,
                bb_num_std=variant.bb_num_std,
                rsi_oversold=variant.rsi_oversold,
                rsi_overbought=variant.rsi_overbought,
                atr_stop_multiplier=variant.atr_stop_multiplier,
            )
            if signal is None:
                continue

            if variant.session_hours_utc is not None:
                start_hour, end_hour = variant.session_hours_utc
                if not (start_hour <= now_dt.hour < end_hour):
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
