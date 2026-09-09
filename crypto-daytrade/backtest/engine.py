"""Simulador walk-forward multi-símbolo: reproduz exatamente a lógica de `main.py` (mesmo
`generate_signal`, mesmo `check_outcome`, mesma regra de expiração) candle a candle, na ordem
cronológica real, com todos os símbolos processados no mesmo "relógio" — isso é essencial pro
`max_concurrent_same_direction` fazer sentido (precisa saber quantas posições de outros
símbolos já estão abertas NAQUELE instante, não no fim de cada símbolo processado isoladamente).

Sem isso, testar o limite de correlação entre pares seria só decoração — cada símbolo sendo
simulado do início ao fim antes do próximo não capturaria "esses 8 abriram juntos porque o
mercado inteiro subiu ao mesmo tempo", que foi exatamente o padrão observado em produção em
2026-09-08 (ver CLAUDE.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from analysis.outcomes import check_outcome
from analysis.signals import generate_signal
from backtest.filters import passes_adx_filter, passes_higher_timeframe_trend_filter
from data.binance_client import Candle
from storage.signals_store import SignalRecord

WINDOW_SIZE = 100  # mesmo `limit=100` que `scan_for_new_signals` usa em produção
HTF_WINDOW_SIZE = 50


@dataclass(frozen=True)
class Variant:
    """Uma combinação de filtros pra testar contra a mesma janela de histórico. `name` só
    identifica o resultado no relatório, não afeta a simulação."""

    name: str
    min_adx: float | None = None  # None = sem filtro de ADX
    use_htf_trend_filter: bool = False
    max_concurrent_same_direction: int | None = None  # None = sem limite


@dataclass
class BacktestResult:
    variant_name: str
    closed: list[SignalRecord]
    still_open: list[SignalRecord]  # abertos no fim do período — não contam pro win rate


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def run_backtest(
    candles_by_symbol: dict[str, list[Candle]],
    variant: Variant,
    higher_tf_candles_by_symbol: dict[str, list[Candle]] | None = None,
    expiry_hours: float = 24.0,
) -> BacktestResult:
    higher_tf_candles_by_symbol = higher_tf_candles_by_symbol or {}

    # índice por timestamp pra achar rápido "o candle 1h vigente nesse instante" sem
    # re-percorrer a lista inteira a cada checagem
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
        # último candle 1h cujo open_time já começou (<=  now) — bisect manual, listas curtas
        idx = None
        for i, t in enumerate(timestamps):
            if t <= now_ms:
                idx = i
            else:
                break
        if idx is None:
            return None
        return candles[max(0, idx - HTF_WINDOW_SIZE + 1) : idx + 1]

    for now_ms in all_timestamps:
        now_dt = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)

        # 1) resolve posições abertas primeiro (mesma ordem de main.py: fecha o que já
        # aconteceu antes de abrir coisa nova)
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
            signal.close_price = close_price
            closed.append(signal)
            del open_positions[symbol]

        # 2) escaneia sinal novo nos símbolos sem posição aberta
        for symbol, candles in candles_by_symbol.items():
            if symbol in open_positions:
                continue
            idx = time_to_index[symbol].get(now_ms)
            if idx is None or idx + 1 < WINDOW_SIZE:
                continue  # ainda não tem histórico suficiente pros indicadores

            window = candles[idx + 1 - WINDOW_SIZE : idx + 1]
            signal = generate_signal(symbol, window)
            if signal is None:
                continue

            if variant.min_adx is not None and not passes_adx_filter(window, variant.min_adx):
                continue

            if variant.use_htf_trend_filter:
                htf_window = _higher_tf_window(symbol, now_ms)
                if htf_window is None or not passes_higher_timeframe_trend_filter(
                    htf_window, signal.direction
                ):
                    continue

            if variant.max_concurrent_same_direction is not None:
                if _count_open_same_direction(signal.direction) >= variant.max_concurrent_same_direction:
                    continue

            open_positions[symbol] = SignalRecord(
                symbol=signal.symbol,
                direction=signal.direction,
                entry=signal.entry,
                stop_loss=signal.stop_loss,
                target=signal.target,
                rsi_value=signal.rsi_value,
                reason=signal.reason,
                opened_at=_ms_to_iso(now_ms),
            )

    return BacktestResult(
        variant_name=variant.name,
        closed=closed,
        still_open=list(open_positions.values()),
    )
