import pytest

from backtest.engine import ExecutionCosts
from backtest.mean_reversion_engine import WINDOW_SIZE, MeanReversionVariant, run_backtest
from data.twelvedata_client import Candle

_STEP_MS = 60 * 60 * 1000  # candle de 1h


def _touch_lower_band_candles(outcome_high: float, outcome_low: float) -> list[Candle]:
    """WINDOW_SIZE candles: preço estável seguido de uma queda de 1 candle (RSI sobrevendido,
    toca a banda inferior — mesmo fixture validado em test_mean_reversion_signals.py) + 1
    candle seguinte com o high/low informado, pra controlar deterministicamente o desfecho."""
    flat = [1.1000] * (WINDOW_SIZE - 1)
    closes = flat + [1.1000 - 0.0002]

    candles = [
        Candle(open_time_ms=i * _STEP_MS, open=c, high=c + 0.00005, low=c - 0.00005, close=c, volume=0.0)
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
    # ATR fica minúsculo nesse fixture (histórico quase todo plano) -> stop/alvo ficam bem
    # perto da entrada (~1.0998); low do candle seguinte precisa ficar ACIMA do stop calculado
    # (~1.09963) pra não bater stop antes do alvo (~1.09999)
    candles = _touch_lower_band_candles(outcome_high=1.1010, outcome_low=1.0997)

    result = run_backtest({"EUR/USD": candles}, MeanReversionVariant(name="baseline"))

    assert len(result.closed) == 1
    assert result.closed[0].symbol == "EUR/USD"
    assert result.closed[0].direction == "long"
    assert result.closed[0].status == "target_hit"


def test_opens_and_resolves_a_signal_that_hits_stop():
    candles = _touch_lower_band_candles(outcome_high=1.1005, outcome_low=1.0800)

    result = run_backtest({"EUR/USD": candles}, MeanReversionVariant(name="baseline"))

    assert len(result.closed) == 1
    assert result.closed[0].status == "stop_hit"


def test_enters_at_next_candle_open_not_at_the_signal_candle_close():
    candles = _touch_lower_band_candles(outcome_high=1.1050, outcome_low=1.0900)
    candles[-1] = Candle(
        open_time_ms=candles[-1].open_time_ms,
        open=1.0995,  # gap na abertura em relação ao close que gerou o sinal
        high=1.1050,
        low=1.0900,
        close=1.1020,
        volume=0.0,
    )

    result = run_backtest({"EUR/USD": candles}, MeanReversionVariant(name="baseline"))

    assert len(result.closed) == 1
    assert result.closed[0].entry == pytest.approx(1.0995)
    assert result.closed[0].entry_mode == "next_candle_open"


def test_backtest_applies_conservative_slippage_to_entry_and_exit():
    candles = _touch_lower_band_candles(outcome_high=1.1050, outcome_low=1.0900)

    result = run_backtest(
        {"EUR/USD": candles},
        MeanReversionVariant(name="com custos"),
        costs=ExecutionCosts(slippage_rate=0.01),
    )

    assert len(result.closed) == 1
    # long compra pior (mais caro) na entrada com slippage positivo
    entry_without_slippage = candles[-1].open
    assert result.closed[0].entry > entry_without_slippage


def test_no_signal_when_history_shorter_than_window():
    short_candles = _touch_lower_band_candles(1.1050, 1.0900)[: WINDOW_SIZE - 1]

    result = run_backtest({"EUR/USD": short_candles}, MeanReversionVariant(name="baseline"))

    assert result.closed == []
    assert result.still_open == []


def test_session_hours_filter_blocks_signal_outside_the_window():
    candles = _touch_lower_band_candles(outcome_high=1.1050, outcome_low=1.0900)
    # candles[WINDOW_SIZE].open_time_ms cai em 1970-01-05 04:00 UTC (época + 100 candles de 1h)
    # — hora calculada empiricamente pro fixture deste arquivo.

    result = run_backtest(
        {"EUR/USD": candles}, MeanReversionVariant(name="sessão estreita", session_hours_utc=(10, 12))
    )

    assert result.closed == []
    assert result.still_open == []


def test_max_concurrent_positions_caps_new_opens():
    candles = _touch_lower_band_candles(outcome_high=1.1050, outcome_low=1.0900)
    two_symbols = {"EUR/USD": candles, "GBP/USD": list(candles)}

    capped = run_backtest(
        two_symbols, MeanReversionVariant(name="máx 1 posição", max_concurrent_positions=1)
    )

    assert len(capped.closed) + len(capped.still_open) == 1
