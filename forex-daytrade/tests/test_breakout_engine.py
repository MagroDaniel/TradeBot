from datetime import datetime, timedelta, timezone

import pytest

from backtest.breakout_engine import BreakoutVariant, run_backtest
from backtest.engine import ExecutionCosts
from data.twelvedata_client import Candle

_DAY_START = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)


def _candle(hour_offset: float, open_, high, low, close) -> Candle:
    ts = int((_DAY_START + timedelta(hours=hour_offset)).timestamp() * 1000)
    return Candle(open_time_ms=ts, open=open_, high=high, low=low, close=close, volume=0.0)


def _padding_candles(hours: int = 30) -> list[Candle]:
    """WINDOW_SIZE candles de "ontem" (fora do dia calendário testado, não interferem no
    range asiático) só pra dar histórico suficiente pro motor considerar `idx >= WINDOW_SIZE`.
    """
    return [_candle(-hours + i, 1.1000, 1.1005, 1.0995, 1.1000) for i in range(hours)]


def _range_then_breakout(
    asian_high=1.1010, asian_low=1.0990, breakout_close=1.1030, outcome_high=1.1200, outcome_low=1.0900
) -> list[Candle]:
    """Candles de padding + 9 candles de 1h do dia testado: horas 0-6 dentro do range (sessão
    asiática), hora 7 rompe acima da máxima (candle de sinal), hora 8 é o candle seguinte
    (entrada + resolução, high/low controlados)."""
    mid = (asian_high + asian_low) / 2
    candles = _padding_candles()
    candles += [_candle(i, mid, asian_high, asian_low, mid) for i in range(7)]
    candles.append(_candle(7, asian_high, breakout_close + 0.0005, asian_high - 0.0002, breakout_close))
    candles.append(_candle(8, breakout_close, outcome_high, outcome_low, breakout_close))
    return candles


def test_opens_and_resolves_a_long_signal_that_hits_target():
    candles = _range_then_breakout(outcome_high=1.1200, outcome_low=1.1000)

    result = run_backtest({"EUR/USD": candles}, BreakoutVariant(name="baseline"))

    assert len(result.closed) == 1
    assert result.closed[0].symbol == "EUR/USD"
    assert result.closed[0].direction == "long"
    assert result.closed[0].status == "target_hit"


def test_opens_and_resolves_a_signal_that_hits_stop():
    candles = _range_then_breakout(outcome_high=1.1035, outcome_low=1.0800)

    result = run_backtest({"EUR/USD": candles}, BreakoutVariant(name="baseline"))

    assert len(result.closed) == 1
    assert result.closed[0].status == "stop_hit"


def test_enters_at_next_candle_open_not_at_the_signal_candle_close():
    candles = _range_then_breakout(outcome_high=1.1200, outcome_low=1.1000)
    # candle das 8h (30 de padding + índice 8) abre com gap em relação ao close que gerou o sinal
    candles[38] = _candle(8, 1.1040, 1.1200, 1.1000, 1.1100)

    result = run_backtest({"EUR/USD": candles}, BreakoutVariant(name="baseline"))

    assert len(result.closed) == 1
    assert result.closed[0].entry == pytest.approx(1.1040)
    assert result.closed[0].entry_mode == "next_candle_open"


def test_backtest_applies_conservative_slippage_to_entry():
    candles = _range_then_breakout(outcome_high=1.1200, outcome_low=1.1000)

    result = run_backtest(
        {"EUR/USD": candles}, BreakoutVariant(name="com custos"), costs=ExecutionCosts(slippage_rate=0.01)
    )

    assert len(result.closed) == 1
    entry_without_slippage = candles[38].open
    assert result.closed[0].entry > entry_without_slippage  # long compra pior (mais caro)


def test_no_signal_when_price_stays_inside_the_asian_range():
    mid = 1.1000
    candles = _padding_candles() + [_candle(i, mid, 1.1010, 1.0990, mid) for i in range(9)]

    result = run_backtest({"EUR/USD": candles}, BreakoutVariant(name="baseline"))

    assert result.closed == []
    assert result.still_open == []


def test_only_one_signal_per_symbol_per_day_even_after_the_first_closes():
    # candle de rompimento (hora 7) resolve imediatamente (stop batido no mesmo candle de
    # entrada, hora 8) — um segundo rompimento na hora 9, mesmo dia, não deveria abrir de novo
    candles = _range_then_breakout(outcome_high=1.1035, outcome_low=1.0800)
    candles.append(_candle(9, 1.0900, 1.1250, 1.0850, 1.1200))  # "rompimento" novo, mesmo dia

    result = run_backtest({"EUR/USD": candles}, BreakoutVariant(name="baseline"))

    assert len(result.closed) == 1  # só o primeiro, não um segundo no mesmo dia


def test_max_concurrent_positions_caps_new_opens():
    candles = _range_then_breakout(outcome_high=1.1200, outcome_low=1.1000)
    two_symbols = {"EUR/USD": candles, "GBP/USD": list(candles)}

    capped = run_backtest(two_symbols, BreakoutVariant(name="máx 1 posição", max_concurrent_positions=1))

    assert len(capped.closed) + len(capped.still_open) == 1
