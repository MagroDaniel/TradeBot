import pytest

from backtest.engine import ExecutionCosts, WINDOW_SIZE, Variant, run_backtest
from data.twelvedata_client import Candle

_STEP_MS = 15 * 60 * 1000  # candle de 15min


def _decline_then_rise_closes(decline_candles=40, decline_step=0.1, rise_candles=9, rise_step=0.18):
    """Mesmo fixture (validado empiricamente) de tests/test_signals.py — cruzamento de EMA9
    acima da EMA21 com RSI dentro da faixa que confirma sinal long."""
    closes = []
    price = 100.0
    for _ in range(decline_candles):
        price -= decline_step
        closes.append(price)
    for _ in range(rise_candles):
        price += rise_step
        closes.append(price)
    return closes


def _crossover_candles_with_outcome(outcome_high: float, outcome_low: float) -> list[Candle]:
    tail = _decline_then_rise_closes()
    flat_prefix = [100.0] * (WINDOW_SIZE - len(tail))
    closes = flat_prefix + tail

    candles = [
        Candle(open_time_ms=i * _STEP_MS, open=c, high=c + 0.3, low=c - 0.3, close=c, volume=0.0)
        for i, c in enumerate(closes)
    ]
    candles.append(
        Candle(
            open_time_ms=len(closes) * _STEP_MS,
            open=closes[-1],
            high=outcome_high,
            low=outcome_low,
            close=(outcome_high + outcome_low) / 2,
            volume=0.0,
        )
    )
    return candles


def test_opens_and_resolves_a_signal_that_hits_target():
    candles = _crossover_candles_with_outcome(outcome_high=200.0, outcome_low=100.0)

    result = run_backtest({"EUR/USD": candles}, Variant(name="baseline"))

    assert len(result.closed) == 1
    assert result.closed[0].symbol == "EUR/USD"
    assert result.closed[0].status == "target_hit"
    assert result.still_open == []


def test_enters_at_next_candle_open_not_at_the_signal_candle_close():
    candles = _crossover_candles_with_outcome(outcome_high=200.0, outcome_low=100.0)
    candles[-1] = Candle(
        open_time_ms=candles[-1].open_time_ms,
        open=110.0,
        high=200.0,
        low=109.5,
        close=150.0,
        volume=0.0,
    )

    result = run_backtest({"EUR/USD": candles}, Variant(name="baseline"))

    assert len(result.closed) == 1
    assert result.closed[0].entry == 110.0
    assert result.closed[0].entry_mode == "next_candle_open"


def test_backtest_applies_conservative_slippage_to_entry_and_exit():
    candles = _crossover_candles_with_outcome(outcome_high=200.0, outcome_low=109.5)
    candles[-1] = Candle(
        open_time_ms=candles[-1].open_time_ms,
        open=110.0,
        high=200.0,
        low=109.5,
        close=150.0,
        volume=0.0,
    )

    result = run_backtest(
        {"EUR/USD": candles},
        Variant(name="com custos"),
        costs=ExecutionCosts(slippage_rate=0.01),
    )

    assert len(result.closed) == 1
    assert result.closed[0].entry == pytest.approx(111.1)
    assert result.closed[0].close_price < result.closed[0].target


def test_opens_and_resolves_a_signal_that_hits_stop():
    candles = _crossover_candles_with_outcome(outcome_high=110.0, outcome_low=50.0)

    result = run_backtest({"EUR/USD": candles}, Variant(name="baseline"))

    assert len(result.closed) == 1
    assert result.closed[0].status == "stop_hit"


def test_adx_filter_blocks_a_signal_that_would_otherwise_open():
    candles = _crossover_candles_with_outcome(outcome_high=200.0, outcome_low=100.0)

    result = run_backtest({"EUR/USD": candles}, Variant(name="adx", min_adx=99.0))

    assert result.closed == []
    assert result.still_open == []


def test_max_concurrent_same_direction_caps_new_opens():
    candles = _crossover_candles_with_outcome(outcome_high=200.0, outcome_low=100.0)
    two_symbols = {"EUR/USD": candles, "GBP/USD": list(candles)}

    uncapped = run_backtest(two_symbols, Variant(name="sem limite"))
    capped = run_backtest(
        two_symbols, Variant(name="máx 1 correlacionado", max_concurrent_same_direction=1)
    )

    assert len(uncapped.closed) + len(uncapped.still_open) == 2
    assert len(capped.closed) + len(capped.still_open) == 1


def test_max_concurrent_positions_caps_total_opens():
    candles = _crossover_candles_with_outcome(outcome_high=200.0, outcome_low=100.0)
    two_symbols = {"EUR/USD": candles, "GBP/USD": list(candles)}

    capped = run_backtest(two_symbols, Variant(name="máx 1 posição", max_concurrent_positions=1))

    assert len(capped.closed) + len(capped.still_open) == 1


def test_no_signal_when_history_shorter_than_window():
    short_candles = _crossover_candles_with_outcome(200.0, 100.0)[: WINDOW_SIZE - 1]

    result = run_backtest({"EUR/USD": short_candles}, Variant(name="baseline"))

    assert result.closed == []
    assert result.still_open == []


def test_allowed_directions_blocks_a_direction_when_configured():
    candles = _crossover_candles_with_outcome(outcome_high=200.0, outcome_low=100.0)

    result = run_backtest(
        {"EUR/USD": candles},
        Variant(name="direção bloqueada"),
        allowed_directions=frozenset({"short"}),
    )

    assert result.closed == []
    assert result.still_open == []


def test_htf_trend_filter_blocks_when_no_higher_tf_history_available():
    candles = _crossover_candles_with_outcome(outcome_high=200.0, outcome_low=100.0)

    # variante pede filtro de 1h, mas nenhum histórico de 1h foi passado -> nunca confirma
    result = run_backtest({"EUR/USD": candles}, Variant(name="1h sem dado", use_htf_trend_filter=True))

    assert result.closed == []
    assert result.still_open == []
