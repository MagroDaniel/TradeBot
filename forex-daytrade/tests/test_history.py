import backtest.history as history
from data.twelvedata_client import Candle


class _FakeClient:
    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles
        self.calls = 0

    def get_historical_candles(self, symbol, interval, start_time_ms, end_time_ms):
        self.calls += 1
        return self.candles


def test_fetch_candles_hits_the_client_on_first_call(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "CACHE_DIR", tmp_path)
    candles = [Candle(open_time_ms=0, open=1.0, high=2.0, low=0.5, close=1.5, volume=0.0)]
    client = _FakeClient(candles)

    result = history.fetch_candles(client, "EUR/USD", "15min", 0, 1000)

    assert client.calls == 1
    assert result == candles


def test_fetch_candles_uses_cache_on_second_call(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "CACHE_DIR", tmp_path)
    candles = [Candle(open_time_ms=0, open=1.0, high=2.0, low=0.5, close=1.5, volume=0.0)]
    client = _FakeClient(candles)

    first = history.fetch_candles(client, "EUR/USD", "15min", 0, 1000)
    second = history.fetch_candles(client, "EUR/USD", "15min", 0, 1000)

    assert client.calls == 1  # segunda chamada veio do cache, não bateu no client de novo
    assert second == first == candles


def test_fetch_candles_uses_separate_cache_per_symbol_and_range(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "CACHE_DIR", tmp_path)
    client = _FakeClient([Candle(open_time_ms=0, open=1.0, high=2.0, low=0.5, close=1.5, volume=0.0)])

    history.fetch_candles(client, "EUR/USD", "15min", 0, 1000)
    history.fetch_candles(client, "GBP/USD", "15min", 0, 1000)
    history.fetch_candles(client, "EUR/USD", "15min", 1000, 2000)

    assert client.calls == 3


def test_fetch_candles_handles_symbol_with_slash_in_cache_filename(tmp_path, monkeypatch):
    # "EUR/USD" tem "/" — não pode virar path literal, senão quebra o filesystem
    monkeypatch.setattr(history, "CACHE_DIR", tmp_path)
    client = _FakeClient([Candle(open_time_ms=0, open=1.0, high=2.0, low=0.5, close=1.5, volume=0.0)])

    history.fetch_candles(client, "EUR/USD", "15min", 0, 1000)

    assert list(tmp_path.glob("EUR-USD_*"))
