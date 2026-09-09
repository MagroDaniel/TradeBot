from analysis.outcomes import check_outcome
from data.binance_client import Candle
from storage.signals_store import SignalRecord


def _make_candle(low: float, high: float, close: float | None = None) -> Candle:
    return Candle(open_time_ms=0, open=low, high=high, low=low, close=close or low, volume=1.0)


def _make_signal(direction: str, stop_loss: float, target: float) -> SignalRecord:
    return SignalRecord(
        symbol="BTCUSDT",
        direction=direction,
        entry=100.0,
        stop_loss=stop_loss,
        target=target,
        rsi_value=50.0,
        reason="teste",
        opened_at="2026-01-01T00:00:00+00:00",
    )


def test_long_hits_target_when_high_reaches_it():
    signal = _make_signal("long", stop_loss=90.0, target=110.0)
    candles = [_make_candle(low=95.0, high=111.0)]

    assert check_outcome(signal, candles) == ("target_hit", 110.0)


def test_long_hits_stop_when_low_reaches_it():
    signal = _make_signal("long", stop_loss=90.0, target=110.0)
    candles = [_make_candle(low=89.0, high=100.0)]

    assert check_outcome(signal, candles) == ("stop_hit", 90.0)


def test_long_checks_stop_before_target_in_the_same_candle():
    # candle único que tocaria os dois — padrão conservador assume que o stop bateu primeiro
    signal = _make_signal("long", stop_loss=90.0, target=110.0)
    candles = [_make_candle(low=89.0, high=111.0)]

    assert check_outcome(signal, candles) == ("stop_hit", 90.0)


def test_short_hits_target_when_low_reaches_it():
    signal = _make_signal("short", stop_loss=110.0, target=90.0)
    candles = [_make_candle(low=89.0, high=100.0)]

    assert check_outcome(signal, candles) == ("target_hit", 90.0)


def test_short_hits_stop_when_high_reaches_it():
    signal = _make_signal("short", stop_loss=110.0, target=90.0)
    candles = [_make_candle(low=95.0, high=111.0)]

    assert check_outcome(signal, candles) == ("stop_hit", 110.0)


def test_returns_none_when_neither_touched():
    signal = _make_signal("long", stop_loss=90.0, target=110.0)
    candles = [_make_candle(low=95.0, high=105.0)]

    assert check_outcome(signal, candles) is None
