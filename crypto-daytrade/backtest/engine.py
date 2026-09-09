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
from analysis.signals import (
    ATR_STOP_MULTIPLIER,
    LONG_RSI_RANGE,
    SHORT_RSI_RANGE,
    STRATEGY_VERSION,
    generate_signal,
    reprice_signal_for_entry,
)
from backtest.filters import passes_adx_filter, passes_signal_candle_quality_filter
from data.binance_client import Candle
from storage.signals_store import SignalRecord

WINDOW_SIZE = 100  # mesmo `limit=100` que `scan_for_new_signals` usa em produção
HTF_WINDOW_SIZE = 50


@dataclass(frozen=True)
class ExecutionCosts:
    """Hipóteses explícitas de execução usadas exclusivamente no backtest.

    Taxas e slippage são percentuais decimais por lado (``0.0004`` = 0,04%).
    Funding é tratado de forma conservadora como custo, por intervalo de 8h, em
    qualquer direção; em futuros reais ele pode ser pago ou recebido.
    """

    taker_fee_rate: float = 0.0
    slippage_rate: float = 0.0
    funding_rate_per_8h: float = 0.0

    def __post_init__(self) -> None:
        if any(value < 0 for value in (self.taker_fee_rate, self.slippage_rate, self.funding_rate_per_8h)):
            raise ValueError("Custos de execução não podem ser negativos")


@dataclass(frozen=True)
class Variant:
    """Uma combinação de filtros pra testar contra a mesma janela de histórico. `name` só
    identifica o resultado no relatório, não afeta a simulação."""

    name: str
    min_adx: float | None = None  # None = sem filtro de ADX
    use_htf_trend_filter: bool = False
    max_concurrent_same_direction: int | None = None  # None = sem limite
    max_concurrent_positions: int | None = None  # None = sem limite total
    min_signal_candle_close_position: float | None = None  # None = sem filtro de qualidade
    atr_stop_multiplier: float | None = None  # None = usa o default de produção (ATR_STOP_MULTIPLIER)
    long_rsi_range: tuple[float, float] | None = None  # None = usa LONG_RSI_RANGE de produção
    short_rsi_range: tuple[float, float] | None = None  # None = usa SHORT_RSI_RANGE de produção
    min_range_expansion: float | None = None  # None = sem filtro de range por estrutura de preço


@dataclass
class BacktestResult:
    variant_name: str
    closed: list[SignalRecord]
    still_open: list[SignalRecord]  # abertos no fim do período — não contam pro win rate


def apply_entry_slippage(price: float, direction: str, costs: ExecutionCosts) -> float:
    """Pior preço plausível para uma entrada a mercado."""
    return price * (1 + costs.slippage_rate) if direction == "long" else price * (1 - costs.slippage_rate)


def apply_exit_slippage(price: float, direction: str, costs: ExecutionCosts) -> float:
    """Pior preço plausível para encerrar uma posição a mercado."""
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
        """Só retorna candles de 1h fechados antes da abertura atual.

        O sinal de 15m é decidido no fechamento do candle anterior e entra na
        abertura de ``now_ms``. Portanto, a kline de 1h em andamento neste instante
        não pode confirmar uma tendência: seu fechamento ainda é desconhecido.
        """
        timestamps = htf_index.get(symbol)
        if not timestamps:
            return None
        candles = higher_tf_candles_by_symbol[symbol]
        # Último candle cujo fechamento já ocorreu. Para caches legados sem
        # close_time, o próximo open_time é o melhor limite disponível.
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
        # Mesmo que uma posição feche dentro deste candle, ela existia no fechamento
        # anterior que está sendo usado para gerar o próximo setup. Não permita um
        # segundo sinal retroativamente sobre a mesma posição.
        occupied_at_signal_close = set(open_positions)

        # 1) Resolve posições abertas durante o candle que acabou de abrir. Elas já
        # existiam antes deste candle, logo high/low dele são informação legítima.
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

        # 2) O candle anterior acabou de fechar. Avalia o sinal nele e abre no preço
        # de abertura DESTE candle, nunca no mesmo candle que forneceu EMA/RSI/ATR.
        # Isto remove o look-ahead que existia quando o motor usava o close/high/low
        # de um candle antes de ele terminar.
        opened_this_candle: list[SignalRecord] = []
        for symbol, candles in candles_by_symbol.items():
            if symbol in occupied_at_signal_close or symbol in open_positions:
                continue
            idx = time_to_index[symbol].get(now_ms)
            if idx is None or idx < WINDOW_SIZE:
                continue  # ainda não tem histórico suficiente pros indicadores

            window = candles[idx - WINDOW_SIZE : idx]

            htf_window = None
            if variant.use_htf_trend_filter:
                htf_window = _higher_tf_window(symbol, now_ms)
                if htf_window is None:
                    continue  # sem histórico de 1h suficiente ainda pra confirmar

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

            # Entrada executável no candle seguinte ao fechamento que confirmou o
            # setup. Stop/alvo mantêm o mesmo risco ATR, mesmo que haja gap.
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
                market_mode="spot" if allowed_directions == frozenset({"long"}) else "futures",
            )
            open_positions[symbol] = record
            opened_this_candle.append(record)

        # Uma entrada na abertura está exposta ao restante deste candle. Aplicamos a
        # mesma convenção conservadora de check_outcome (stop antes do alvo se ambos
        # forem tocados) usada para posições antigas.
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
