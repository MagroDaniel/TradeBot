import backtest.history as history
from data.binance_client import Candle


class _FakeClient:
    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles
        self.calls = 0

    def get_historical_klines(self, symbol, interval, start_time_ms, end_time_ms):
        self.calls += 1
        return self.candles


def test_fetch_candles_hits_the_client_on_first_call(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "CACHE_DIR", tmp_path)
    candles = [Candle(open_time_ms=0, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0)]
    client = _FakeClient(candles)

    result = history.fetch_candles(client, "BTCUSDT", "15m", 0, 1000)

    assert client.calls == 1
    assert result == candles


def test_fetch_candles_uses_cache_on_second_call(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "CACHE_DIR", tmp_path)
    candles = [Candle(open_time_ms=0, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0)]
    client = _FakeClient(candles)

    first = history.fetch_candles(client, "BTCUSDT", "15m", 0, 1000)
    second = history.fetch_candles(client, "BTCUSDT", "15m", 0, 1000)

    assert client.calls == 1  # segunda chamada veio do cache, não bateu no client de novo
    assert second == first == candles


def test_fetch_candles_uses_separate_cache_per_symbol_and_range(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "CACHE_DIR", tmp_path)
    client = _FakeClient([Candle(open_time_ms=0, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0)])

    history.fetch_candles(client, "BTCUSDT", "15m", 0, 1000)
    history.fetch_candles(client, "ETHUSDT", "15m", 0, 1000)
    history.fetch_candles(client, "BTCUSDT", "15m", 1000, 2000)

    assert client.calls == 3
