"""Simulador walk-forward pra estratégia de rompimento do range asiático
(`analysis/breakout_signals.py`) — mesmo raciocínio de não-viés de look-ahead dos outros dois
motores (entrada no candle seguinte ao que confirmou o sinal). Motor separado pelo mesmo
motivo do `mean_reversion_engine.py`: forma de sinal (estado por dia calendário: "já rompeu
hoje?") diferente o bastante das outras duas estratégias pra um motor genérico compartilhado
valer menos que motores simples e testáveis isoladamente. Reaproveita `SignalRecord`,
`check_outcome`, `ExecutionCosts` e a lógica de slippage do `engine.py` de tendência, não
duplica.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from analysis.breakout_signals import (
    BREAKOUT_END_HOUR,
    BREAKOUT_START_HOUR,
    STRATEGY_VERSION,
    generate_signal,
    reprice_signal_for_entry,
)
from backtest.engine import BacktestResult, ExecutionCosts, apply_entry_slippage, apply_exit_slippage
from analysis.outcomes import check_outcome
from data.twelvedata_client import Candle
from storage.signals_store import SignalRecord

WINDOW_SIZE = 30  # candles de 1h — cobre >24h, dá folga pra sessão asiática de hoje + ontem


@dataclass(frozen=True)
class BreakoutVariant:
    """Uma combinação de parâmetros pra testar. `name` só identifica o resultado no
    relatório, não afeta a simulação."""

    name: str
    max_concurrent_positions: int | None = None


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def run_backtest(
    candles_by_symbol: dict[str, list[Candle]],
    variant: BreakoutVariant,
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
    # (symbol, data calendário) já rompido hoje — não persegue o mesmo rompimento duas vezes
    # nem troca de direção no mesmo dia, mesmo depois da posição fechar.
    triggered_today: set[tuple[str, str]] = set()

    for now_ms in all_timestamps:
        now_dt = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
        today_key = now_dt.date().isoformat()
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

        # Fora da janela de rompimento (07h-11h UTC) não vale a pena nem avaliar sinal novo —
        # a estratégia só dispara nessa janela por definição (ver analysis/breakout_signals.py)
        if not (BREAKOUT_START_HOUR <= now_dt.hour < BREAKOUT_END_HOUR):
            continue

        # 2) O candle anterior acabou de fechar. Avalia o sinal nele e abre no preço de
        # abertura DESTE candle.
        opened_this_candle: list[SignalRecord] = []
        for symbol, candles in candles_by_symbol.items():
            if symbol in occupied_at_signal_close or symbol in open_positions:
                continue
            if (symbol, today_key) in triggered_today:
                continue
            idx = time_to_index[symbol].get(now_ms)
            if idx is None or idx < WINDOW_SIZE:
                continue

            window = candles[idx - WINDOW_SIZE : idx]
            signal = generate_signal(symbol, window)
            if signal is None:
                continue

            if variant.max_concurrent_positions is not None:
                if len(open_positions) >= variant.max_concurrent_positions:
                    continue

            # Só marca como "rompido hoje" quando a posição é de fato aberta — um sinal
            # bloqueado só pelo limite de concorrência pode tentar de novo num candle
            # seguinte ainda dentro da janela, se abrir vaga.
            triggered_today.add((symbol, today_key))

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
