from datetime import datetime, timezone

from data.binance_client import BinanceClient, Candle, closed_candles


class _FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_get_top_symbols_by_volume_sorts_descending(monkeypatch):
    payload = [
        {"symbol": "BTCUSDT", "quoteVolume": "1000"},
        {"symbol": "ETHUSDT", "quoteVolume": "5000"},
        {"symbol": "ADAUSDT", "quoteVolume": "2000"},
    ]
    monkeypatch.setattr(
        "data.binance_client.requests.get", lambda url, timeout: _FakeResponse(200, payload)
    )

    symbols = BinanceClient().get_top_symbols_by_volume(limit=25)

    assert symbols == ["ETHUSDT", "ADAUSDT", "BTCUSDT"]


def test_get_top_symbols_by_volume_filters_other_quote_assets(monkeypatch):
    payload = [
        {"symbol": "BTCUSDT", "quoteVolume": "1000"},
        {"symbol": "BTCBUSD", "quoteVolume": "9999"},  # cotado em BUSD, não USDT
    ]
    monkeypatch.setattr(
        "data.binance_client.requests.get", lambda url, timeout: _FakeResponse(200, payload)
    )

    symbols = BinanceClient().get_top_symbols_by_volume(quote_asset="USDT", limit=25)

    assert symbols == ["BTCUSDT"]


def test_get_top_symbols_by_volume_excludes_stablecoins(monkeypatch):
    payload = [
        {"symbol": "USDCUSDT", "quoteVolume": "999999"},  # volume alto, mas é stablecoin
        {"symbol": "BTCUSDT", "quoteVolume": "1000"},
    ]
    monkeypatch.setattr(
        "data.binance_client.requests.get", lambda url, timeout: _FakeResponse(200, payload)
    )

    symbols = BinanceClient().get_top_symbols_by_volume(limit=25)

    assert "USDCUSDT" not in symbols
    assert symbols == ["BTCUSDT"]


def test_get_top_symbols_by_volume_respects_limit(monkeypatch):
    payload = [{"symbol": f"COIN{i}USDT", "quoteVolume": str(i)} for i in range(10)]
    monkeypatch.setattr(
        "data.binance_client.requests.get", lambda url, timeout: _FakeResponse(200, payload)
    )

    symbols = BinanceClient().get_top_symbols_by_volume(limit=3)

    assert len(symbols) == 3


def test_get_klines_parses_candles(monkeypatch):
    raw = [[1788857100000, "100.0", "105.0", "95.0", "102.0", "50.0", 1788857999999, "0", 0, "0", "0", "0"]]
    monkeypatch.setattr(
        "data.binance_client.requests.get",
        lambda url, params, timeout: _FakeResponse(200, raw),
    )

    candles = BinanceClient().get_klines("BTCUSDT", interval="15m", limit=1)

    assert len(candles) == 1
    c = candles[0]
    assert c.open_time_ms == 1788857100000
    assert c.open == 100.0
    assert c.high == 105.0
    assert c.low == 95.0
    assert c.close == 102.0
    assert c.volume == 50.0
    assert c.close_time_ms == 1788857999999


def test_closed_candles_excludes_the_kline_still_in_formation():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    finished = Candle(0, 1, 1, 1, 1, 1, close_time_ms=now_ms - 1)
    open_now = Candle(1, 1, 1, 1, 1, 1, close_time_ms=now_ms + 1)

    assert closed_candles([finished, open_now], now=now) == [finished]


def _raw_candle(open_time_ms: int) -> list:
    return [open_time_ms, "100.0", "105.0", "95.0", "102.0", "50.0", 0, "0", 0, "0", "0", "0"]


def test_get_historical_klines_stops_when_page_is_short(monkeypatch):
    # só 1 candle devolvido (< 1000) — sinal de que já é a última página, não pagina de novo
    monkeypatch.setattr(
        "data.binance_client.requests.get",
        lambda url, params, timeout: _FakeResponse(200, [_raw_candle(1000)]),
    )

    candles = BinanceClient().get_historical_klines("BTCUSDT", "15m", start_time_ms=0, end_time_ms=10_000)

    assert len(candles) == 1
    assert candles[0].open_time_ms == 1000


def test_get_historical_klines_pages_until_a_short_page(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append(params["startTime"])
        if params["startTime"] == 0:
            # primeira página cheia (1000 candles) -> tem que pedir mais uma página
            return _FakeResponse(200, [_raw_candle(i) for i in range(1000)])
        # segunda página, curta -> é a última
        return _FakeResponse(200, [_raw_candle(1000)])

    monkeypatch.setattr("data.binance_client.requests.get", fake_get)

    candles = BinanceClient().get_historical_klines(
        "BTCUSDT", "15m", start_time_ms=0, end_time_ms=2000
    )

    assert len(calls) == 2
    assert calls[1] == 1000  # open_time do último candle da 1a página (999) + 1ms
    assert len(candles) == 1001


def test_get_historical_klines_stops_on_empty_page(monkeypatch):
    monkeypatch.setattr(
        "data.binance_client.requests.get", lambda url, params, timeout: _FakeResponse(200, [])
    )

    candles = BinanceClient().get_historical_klines("BTCUSDT", "15m", start_time_ms=0, end_time_ms=10_000)

    assert candles == []


def test_get_current_price_returns_none_on_error(monkeypatch):
    monkeypatch.setattr(
        "data.binance_client.requests.get",
        lambda url, params, timeout: _FakeResponse(400, {}),
    )

    assert BinanceClient().get_current_price("NAOEXISTE") is None


def test_get_current_price_returns_value_on_success(monkeypatch):
    monkeypatch.setattr(
        "data.binance_client.requests.get",
        lambda url, params, timeout: _FakeResponse(200, {"price": "102.5"}),
    )

    assert BinanceClient().get_current_price("BTCUSDT") == 102.5
