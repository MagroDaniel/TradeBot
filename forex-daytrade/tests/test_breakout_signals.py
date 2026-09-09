from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from analysis.breakout_signals import asian_session_range, generate_signal, reprice_signal_for_entry
from data.twelvedata_client import Candle

_DAY_START = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)  # segunda-feira


def _hourly_candles(hours: int, price_fn) -> list[Candle]:
    """`price_fn(hour_index)` -> (open, high, low, close) pra cada candle de 1h a partir de
    `_DAY_START`."""
    candles = []
    for i in range(hours):
        o, h, l, c = price_fn(i)
        ts = int((_DAY_START + timedelta(hours=i)).timestamp() * 1000)
        candles.append(Candle(open_time_ms=ts, open=o, high=h, low=l, close=c, volume=0.0))
    return candles


def _asian_range_then_breakout_up(hours=9, asian_high=1.1010, asian_low=1.0990, breakout_close=1.1030):
    """Sessão asiática (horas 0-6 UTC) oscilando num range apertado, seguida de um candle às
    07h UTC (índice 7, início da janela de rompimento) que fecha bem acima da máxima do range."""
    def price_fn(i):
        if i < 7:  # sessão asiática — dentro do range
            mid = (asian_high + asian_low) / 2
            return mid, asian_high, asian_low, mid
        if i == 7:  # candle de rompimento
            return asian_high, breakout_close + 0.0005, asian_high - 0.0002, breakout_close
        return breakout_close, breakout_close + 0.0002, breakout_close - 0.0002, breakout_close
    return _hourly_candles(hours, price_fn)


def _asian_range_then_breakout_down(hours=9, asian_high=1.1010, asian_low=1.0990, breakout_close=1.0970):
    def price_fn(i):
        if i < 7:
            mid = (asian_high + asian_low) / 2
            return mid, asian_high, asian_low, mid
        if i == 7:
            return asian_low, asian_low + 0.0002, breakout_close - 0.0005, breakout_close
        return breakout_close, breakout_close + 0.0002, breakout_close - 0.0002, breakout_close
    return _hourly_candles(hours, price_fn)


def test_asian_session_range_computes_high_and_low_of_the_window():
    candles = _asian_range_then_breakout_up()
    result = asian_session_range(candles, _DAY_START.date())

    assert result == (1.1010, 1.0990)


def test_asian_session_range_returns_none_without_any_candle_in_the_window():
    candles = _hourly_candles(3, lambda i: (1.1, 1.1, 1.1, 1.1))  # só 3 candles, não cobre 0-7h
    result = asian_session_range(candles, (_DAY_START + timedelta(days=1)).date())

    assert result is None


def test_generates_long_signal_on_breakout_above_asian_high():
    candles = _asian_range_then_breakout_up()

    signal = generate_signal("EUR/USD", candles)

    assert signal is not None
    assert signal.direction == "long"
    assert signal.symbol == "EUR/USD"
    assert signal.entry == pytest.approx(1.1030)
    assert signal.stop_loss == pytest.approx(1.0990)  # mínima da sessão asiática
    assert signal.target > signal.entry


def test_generates_short_signal_on_breakout_below_asian_low():
    candles = _asian_range_then_breakout_down()

    signal = generate_signal("EUR/USD", candles)

    assert signal is not None
    assert signal.direction == "short"
    assert signal.entry == pytest.approx(1.0970)
    assert signal.stop_loss == pytest.approx(1.1010)  # máxima da sessão asiática
    assert signal.target < signal.entry


def test_no_signal_when_price_stays_inside_the_asian_range():
    candles = _hourly_candles(9, lambda i: (1.1000, 1.1010, 1.0990, 1.1000))

    assert generate_signal("EUR/USD", candles) is None


def test_no_signal_outside_the_breakout_window():
    # mesmo candle de rompimento, mas fora da janela 07h-11h UTC (ex: 12h) -> ignorado
    candles = _asian_range_then_breakout_up(hours=13)
    late = candles[:7] + [candles[7]] * 5  # empurra o "candle mais recente" pra hora 12
    # substitui o horário do último candle pra simular avaliação fora da janela
    ts_12h = int((_DAY_START + timedelta(hours=12)).timestamp() * 1000)
    late[-1] = replace(candles[7], open_time_ms=ts_12h)

    assert generate_signal("EUR/USD", late) is None


def test_reprice_signal_for_entry_preserves_risk_and_target_distance():
    candles = _asian_range_then_breakout_up()
    signal = generate_signal("EUR/USD", candles)
    assert signal is not None

    risk = abs(signal.entry - signal.stop_loss)
    target_distance = abs(signal.target - signal.entry)

    gapped_entry = signal.entry + 0.0010
    repriced = reprice_signal_for_entry(signal, gapped_entry)

    assert repriced.entry == pytest.approx(gapped_entry)
    assert abs(repriced.entry - repriced.stop_loss) == pytest.approx(risk)
    assert abs(repriced.target - repriced.entry) == pytest.approx(target_distance)


def test_reprice_signal_for_entry_rejects_non_positive_price():
    candles = _asian_range_then_breakout_up()
    signal = generate_signal("EUR/USD", candles)
    assert signal is not None

    with pytest.raises(ValueError):
        reprice_signal_for_entry(signal, 0.0)
