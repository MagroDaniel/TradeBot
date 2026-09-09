from backtest.filters import passes_adx_filter
from data.binance_client import Candle


def _candles_from_closes(closes: list[float]) -> list[Candle]:
    return [
        Candle(open_time_ms=i, open=c, high=c + 1.0, low=c - 1.0, close=c, volume=100.0)
        for i, c in enumerate(closes)
    ]


def test_adx_filter_passes_for_a_steady_uptrend():
    closes = [100.0 + i for i in range(40)]
    assert passes_adx_filter(_candles_from_closes(closes), min_adx=25.0) is True


def test_adx_filter_blocks_a_sideways_market():
    closes = [100.0 + (2.0 if i % 2 == 0 else -2.0) for i in range(40)]
    assert passes_adx_filter(_candles_from_closes(closes), min_adx=25.0) is False


def test_adx_filter_blocks_when_not_enough_history():
    assert passes_adx_filter(_candles_from_closes([100.0, 101.0]), min_adx=25.0) is False
